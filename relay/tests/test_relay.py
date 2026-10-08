"""mj-relay 동작 테스트 (실제 ZMQ 소켓을 localhost 에서 사용).

실행: venv/bin/python -m unittest discover -s relay/tests -t .
"""

import asyncio
import json
import os
import sys
import unittest

import zmq
import zmq.asyncio
from aiohttp.test_utils import TestClient, TestServer

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mj_relay  # noqa: E402

API_KEY = "test-key"


def make_config(**overrides):
	return mj_relay.Config(api_key=API_KEY, bind_host="127.0.0.1", port_min=5650, port_max=5669, **overrides)


class RelayTestCase(unittest.IsolatedAsyncioTestCase):
	async def asyncSetUp(self):
		self.relay = mj_relay.Relay(make_config())
		await self.relay.start()
		self.client_ctx = zmq.asyncio.Context()
		self.client_socks = []

	async def asyncTearDown(self):
		for sock in self.client_socks:
			sock.close(0)
		await self.relay.stop()
		self.client_ctx.term()

	def sender(self, room):
		sock = self.client_ctx.socket(zmq.PUSH)
		self.client_socks.append(sock)
		sock.linger = 0
		sock.connect(f"tcp://127.0.0.1:{room.in_port}")
		return sock

	def receiver(self, room, kind=zmq.SUB):
		sock = self.client_ctx.socket(kind)
		self.client_socks.append(sock)
		sock.linger = 0
		if kind == zmq.SUB:
			sock.setsockopt(zmq.SUBSCRIBE, b"")
		sock.connect(f"tcp://127.0.0.1:{room.out_port}")
		return sock

	async def open_room(self, payload, join=("sender", "receiver")):
		"""방을 만들고 이 테스트(127.0.0.1)를 보내는/받는 쪽으로 입장시킴."""
		room = await self.relay.create_room(payload)
		for role in join:
			self.relay.join(room.id, role, getattr(room, f"{role}_token"), "127.0.0.1")
		return room

	async def recv(self, sock, timeout=2.0):
		return await asyncio.wait_for(sock.recv_multipart(), timeout)


class RoomRelayTests(RelayTestCase):
	async def test_iq_bytes_and_multipart_pass_through_unchanged(self):
		room = await self.open_room({"kind": "iq", "meta": {"format": "fc32", "sample_rate": 2e6}})
		rx = self.receiver(room)
		tx = self.sender(room)
		await asyncio.sleep(0.3)  # SUB 구독이 전달될 시간
		payload = os.urandom(8 * 4096)
		await tx.send(payload)
		self.assertEqual(await self.recv(rx), [payload])
		await tx.send_multipart([b"tag-header", b"samples"])
		self.assertEqual(await self.recv(rx), [b"tag-header", b"samples"])
		self.assertEqual(room.bytes_in, len(payload) + len(b"tag-header") + len(b"samples"))
		self.assertEqual(len(room.snapshot), mj_relay.SNAPSHOT_SAMPLES * 8)

	async def test_multiple_receivers_get_same_stream(self):
		room = await self.open_room({"kind": "raw"})
		rx1, rx2 = self.receiver(room), self.receiver(room)
		tx = self.sender(room)
		await asyncio.sleep(0.3)
		await tx.send(b"hello")
		self.assertEqual(await self.recv(rx1), [b"hello"])
		self.assertEqual(await self.recv(rx2), [b"hello"])

	async def test_file_room_uses_push_and_tracks_progress(self):
		room = await self.open_room({"kind": "file", "meta": {"filename": "cap.iq"}})
		rx = self.receiver(room, zmq.PULL)
		tx = self.sender(room)
		header = json.dumps({"name": "cap.iq", "size": 6}).encode()
		await tx.send_multipart([mj_relay.FILE_HEADER, header])
		await tx.send(b"abc")
		await tx.send(b"def")
		await tx.send_multipart([mj_relay.FILE_END, b"{}"])
		got = [await self.recv(rx) for _ in range(4)]
		self.assertEqual(got[1:3], [[b"abc"], [b"def"]])
		self.assertEqual(room.file_info["received"], 6)
		self.assertTrue(room.file_info["done"])

	async def test_rate_limit_drops_excess_for_realtime(self):
		room = await self.open_room({"kind": "raw", "rate_limit": 64 * 1024})
		tx = self.sender(room)
		chunk = b"x" * 16 * 1024
		for _ in range(20):  # 320KB 를 한 번에 → 1초 분량(64KB) 넘는 건 버려져야 함
			await tx.send(chunk)
		await asyncio.sleep(0.5)
		self.assertGreater(room.bytes_dropped, 0)
		self.assertLessEqual(room.bytes_in, 64 * 1024 + len(chunk))

	async def test_total_limit_closes_room_and_frees_ports(self):
		room = await self.open_room({"kind": "raw", "total_limit": 1024 * 1024})
		ports = {room.in_port, room.out_port}
		tx = self.sender(room)
		for _ in range(20):
			await tx.send(b"y" * 64 * 1024)
		for _ in range(40):
			if room.id not in self.relay.rooms:
				break
			await asyncio.sleep(0.05)
		self.assertNotIn(room.id, self.relay.rooms)
		self.assertIn("총 전송량", room.closed_reason)
		again = await self.relay.create_room({"kind": "raw"})
		self.assertTrue({again.in_port, again.out_port} & ports)  # 반납된 포트 재사용

	async def test_expired_room_is_closed(self):
		room = await self.relay.create_room({"kind": "raw", "ttl": 60})
		room.expires_at = 0
		await asyncio.sleep(1.3)
		self.assertNotIn(room.id, self.relay.rooms)

	async def test_not_joined_cannot_send_or_receive(self):
		room = await self.relay.create_room({"kind": "raw"})  # 아무도 입장 안 함
		rx = self.receiver(room)
		tx = self.sender(room)
		await asyncio.sleep(0.3)
		await tx.send(b"nobody joined")
		with self.assertRaises(asyncio.TimeoutError):
			await self.recv(rx, timeout=0.8)
		self.assertEqual(room.bytes_in, 0)

	async def test_clients_started_before_join_connect_after_join(self):
		"""GNU Radio 를 먼저 켜 두고 나중에 링크로 입장해도 자동으로 붙어야 함."""
		room = await self.relay.create_room({"kind": "raw"})
		rx = self.receiver(room)
		tx = self.sender(room)
		await asyncio.sleep(0.8)  # 입장 전: 거절당하며 재시도 중
		self.assertEqual(room.bytes_in, 0)
		for role in ("sender", "receiver"):
			self.relay.join(room.id, role, getattr(room, f"{role}_token"), "127.0.0.1")
		for _ in range(100):  # 입장 후 최대 ~2초(handshake_ivl) 안에 재접속
			if room.stats()["ready"]:
				break
			await asyncio.sleep(0.05)
		self.assertTrue(room.stats()["ready"])
		await asyncio.sleep(0.3)  # SUB 구독 전달
		await tx.send(b"after join")
		self.assertEqual(await self.recv(rx), [b"after join"])

	async def test_join_sender_only_still_blocks_receiver(self):
		room = await self.open_room({"kind": "raw"}, join=("sender",))
		rx = self.receiver(room)
		tx = self.sender(room)
		await asyncio.sleep(0.3)
		await tx.send(b"data")
		await asyncio.sleep(0.3)
		self.assertEqual(room.bytes_in, 4)  # 보내는 쪽은 들어옴
		with self.assertRaises(asyncio.TimeoutError):
			await self.recv(rx, timeout=0.8)  # 입장 안 한 받는 쪽은 못 받음
		self.assertEqual(room.receivers, 0)

	async def test_static_allow_ips_work_for_sender_without_join(self):
		blocked = await self.open_room({"kind": "raw", "allow_ips": ["10.0.0.1"]}, join=("receiver",))
		rx = self.receiver(blocked)
		tx = self.sender(blocked)
		await asyncio.sleep(0.3)
		await tx.send(b"should not pass")
		with self.assertRaises(asyncio.TimeoutError):
			await self.recv(rx, timeout=0.8)

		allowed = await self.open_room({"kind": "raw", "allow_ips": ["127.0.0.0/8"]}, join=("receiver",))
		rx2 = self.receiver(allowed)
		tx2 = self.sender(allowed)
		await asyncio.sleep(0.3)
		await tx2.send(b"ok")
		self.assertEqual(await self.recv(rx2), [b"ok"])

	async def test_join_checks_role_token_and_expires(self):
		room = await self.relay.create_room({"kind": "raw"})
		with self.assertRaises(mj_relay.RoomError) as ctx:
			self.relay.join(room.id, "sender", room.receiver_token, "1.2.3.4")  # 다른 역할 토큰
		self.assertEqual(ctx.exception.status, 403)
		with self.assertRaises(mj_relay.RoomError):
			self.relay.join(room.id, "sender", room.sender_token, "not-an-ip")
		self.relay.join(room.id, "sender", room.sender_token, "1.2.3.4")
		self.relay.join(room.id, "receiver", room.token, "5.6.7.8")  # 관리자 토큰은 어느 역할이든 가능
		self.assertTrue(room.allows("sender", "1.2.3.4"))
		self.assertFalse(room.allows("receiver", "1.2.3.4"))
		self.assertTrue(room.allows("receiver", "5.6.7.8"))
		room.joined["sender"]["1.2.3.4"] -= mj_relay.JOIN_TTL + 1  # 오래된 등록
		self.assertFalse(room.allows("sender", "1.2.3.4"))

	async def test_ready_when_both_sides_connected(self):
		room = await self.open_room({"kind": "raw"})
		self.assertFalse(room.stats()["ready"])
		self.receiver(room)
		self.sender(room)
		for _ in range(30):
			if room.stats()["ready"]:
				break
			await asyncio.sleep(0.05)
		self.assertTrue(room.stats()["ready"])

	async def test_room_count_and_validation(self):
		with self.assertRaises(mj_relay.RoomError):
			await self.relay.create_room({"kind": "video"})
		with self.assertRaises(mj_relay.RoomError):
			await self.relay.create_room({"kind": "iq", "meta": {"format": "fc64"}})
		with self.assertRaises(mj_relay.RoomError):
			await self.relay.create_room({"kind": "raw", "allow_ips": ["not-an-ip"]})
		for _ in range(self.relay.config.max_rooms):
			await self.relay.create_room({"kind": "raw"})
		with self.assertRaises(mj_relay.RoomError) as ctx:
			await self.relay.create_room({"kind": "raw"})
		self.assertEqual(ctx.exception.status, 409)


class ApiTests(RelayTestCase):
	async def asyncSetUp(self):
		await super().asyncSetUp()
		self.client = TestClient(TestServer(mj_relay.build_app(self.relay)))
		await self.client.start_server()

	async def asyncTearDown(self):
		await self.client.close()
		await super().asyncTearDown()

	async def test_api_requires_key(self):
		resp = await self.client.post("/rooms", json={"kind": "raw"})
		self.assertEqual(resp.status, 401)
		resp = await self.client.get("/rooms", headers={"X-Relay-Key": "wrong"})
		self.assertEqual(resp.status, 401)

	async def test_create_list_delete(self):
		headers = {"X-Relay-Key": API_KEY}
		resp = await self.client.post("/rooms", json={"kind": "iq", "meta": {"format": "sc8"}}, headers=headers)
		self.assertEqual(resp.status, 201)
		room = await resp.json()
		self.assertEqual(room["out_socket"], "PUB")
		listing = await (await self.client.get("/rooms", headers=headers)).json()
		self.assertEqual([r["id"] for r in listing["rooms"]], [room["id"]])
		resp = await self.client.delete(f"/rooms/{room['id']}", headers=headers)
		self.assertEqual(resp.status, 200)
		self.assertEqual(self.relay.rooms, {})

	async def test_join_endpoint(self):
		headers = {"X-Relay-Key": API_KEY}
		room = await self.relay.create_room({"kind": "raw"})
		resp = await self.client.post(f"/rooms/{room.id}/join", json={"role": "sender", "token": "wrong", "ip": "1.2.3.4"}, headers=headers)
		self.assertEqual(resp.status, 403)
		resp = await self.client.post(f"/rooms/{room.id}/join", json={"role": "sender", "token": room.sender_token, "ip": "1.2.3.4"}, headers=headers)
		self.assertEqual(resp.status, 200)
		self.assertEqual((await resp.json())["joined"]["sender"], ["1.2.3.4"])

	async def test_websocket_needs_room_token_and_streams_stats(self):
		room = await self.open_room({"kind": "iq"})
		resp = await self.client.get(f"/relay/ws/{room.id}?token=wrong")
		self.assertEqual(resp.status, 404)
		ws = await self.client.ws_connect(f"/relay/ws/{room.id}?token={room.receiver_token}")
		hello = await ws.receive_json(timeout=2)
		self.assertEqual(hello["type"], "hello")
		for key in ("token", "sender_token", "receiver_token"):
			self.assertNotIn(key, hello)
		tx = self.sender(room)
		await tx.send(os.urandom(8 * 2048))
		got_stats = got_snapshot = False
		for _ in range(20):
			msg = await ws.receive(timeout=2)
			if msg.type.name == "TEXT" and json.loads(msg.data)["type"] == "stats":
				got_stats = True
			elif msg.type.name == "BINARY":
				got_snapshot = len(msg.data) == mj_relay.SNAPSHOT_SAMPLES * 8
			if got_stats and got_snapshot:
				break
		self.assertTrue(got_stats and got_snapshot)
		await ws.close()


if __name__ == "__main__":
	unittest.main()


class WebFileTransferTests(RelayTestCase):
	async def asyncSetUp(self):
		await super().asyncSetUp()
		self.client = TestClient(TestServer(mj_relay.build_app(self.relay)))
		await self.client.start_server()

	async def asyncTearDown(self):
		await self.client.close()
		await super().asyncTearDown()

	async def _recv_file(self, ws):
		"""file-start → 조각 → file-end 까지 받아 (헤더, 바이트) 반환."""
		header, chunks = None, []
		while True:
			msg = await ws.receive(timeout=3)
			if msg.type.name == "TEXT":
				data = json.loads(msg.data)
				if data["type"] == "file-start":
					header = data
				elif data["type"] == "file-end":
					return header, b"".join(chunks), data
			elif msg.type.name == "BINARY":
				chunks.append(msg.data)

	async def _send_file(self, ws, name, payload, chunk=64 * 1024):
		await ws.send_json({"type": "start", "name": name, "size": len(payload)})
		self.assertEqual((await ws.receive_json(timeout=3))["type"], "started")
		for i in range(0, len(payload), chunk):
			await ws.send_bytes(payload[i:i + chunk])
			ack = await ws.receive_json(timeout=3)
			self.assertEqual(ack["type"], "ack")
		await ws.send_json({"type": "end"})
		return await ws.receive_json(timeout=3)

	async def test_browser_to_browser(self):
		room = await self.relay.create_room({"kind": "file"})
		rx = await self.client.ws_connect(f"/relay/ws/{room.id}/recv?token={room.receiver_token}")
		self.assertEqual((await rx.receive_json(timeout=2))["type"], "ready")
		tx = await self.client.ws_connect(f"/relay/ws/{room.id}/send?token={room.sender_token}")
		payload = os.urandom(300_000)
		recv_task = asyncio.create_task(self._recv_file(rx))
		done = await self._send_file(tx, "photo.jpg", payload)
		header, data, end = await recv_task
		self.assertEqual(done, {"type": "done", "received": len(payload)})
		self.assertEqual(header["name"], "photo.jpg")
		self.assertEqual(data, payload)
		self.assertEqual(end["size"], len(payload))
		self.assertTrue(room.file_info["done"])
		await tx.close()
		await rx.close()

	async def test_browser_to_cli_zmq_receiver(self):
		room = await self.open_room({"kind": "file"})
		zrx = self.receiver(room, zmq.PULL)
		for _ in range(40):
			if room.receivers:
				break
			await asyncio.sleep(0.05)
		tx = await self.client.ws_connect(f"/relay/ws/{room.id}/send?token={room.sender_token}")
		payload = os.urandom(100_000)
		await self._send_file(tx, "a.bin", payload, chunk=40_000)
		frames = [await self.recv(zrx) for _ in range(5)]  # 헤더 + 조각 3 + 끝
		self.assertEqual(frames[0][0], mj_relay.FILE_HEADER)
		self.assertEqual(b"".join(f[0] for f in frames[1:4]), payload)
		self.assertEqual(frames[4][0], mj_relay.FILE_END)
		await tx.close()

	async def test_cli_zmq_sender_to_browser(self):
		room = await self.open_room({"kind": "file"})
		rx = await self.client.ws_connect(f"/relay/ws/{room.id}/recv?token={room.receiver_token}")
		await rx.receive_json(timeout=2)
		tx = self.sender(room)
		recv_task = asyncio.create_task(self._recv_file(rx))
		await tx.send_multipart([mj_relay.FILE_HEADER, json.dumps({"name": "cli.bin", "size": 6}).encode()])
		await tx.send(b"abc")
		await tx.send(b"def")
		await tx.send_multipart([mj_relay.FILE_END, b'{"size": 6}'])
		header, data, _ = await recv_task
		self.assertEqual((header["name"], data), ("cli.bin", b"abcdef"))
		await rx.close()

	async def test_no_receiver_and_token_checks(self):
		room = await self.relay.create_room({"kind": "file"})
		tx = await self.client.ws_connect(f"/relay/ws/{room.id}/send?token={room.sender_token}")
		await tx.send_json({"type": "start", "name": "x", "size": 1})
		self.assertEqual(await tx.receive_json(timeout=2), {"type": "error", "error": "no-receiver"})
		self.assertTrue(room.stats()["ready"] is False)
		await tx.close()
		resp = await self.client.get(f"/relay/ws/{room.id}/send?token={room.receiver_token}")
		self.assertEqual(resp.status, 404)  # 받는 쪽 토큰으로는 보낼 수 없음
		resp = await self.client.get(f"/relay/ws/{room.id}/recv?token={room.sender_token}")
		self.assertEqual(resp.status, 404)
		raw = await self.relay.create_room({"kind": "raw"})
		resp = await self.client.get(f"/relay/ws/{raw.id}/send?token={raw.sender_token}")
		self.assertEqual(resp.status, 404)  # 파일 방에서만
