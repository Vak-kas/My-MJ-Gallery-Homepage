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

	async def recv(self, sock, timeout=2.0):
		return await asyncio.wait_for(sock.recv_multipart(), timeout)


class RoomRelayTests(RelayTestCase):
	async def test_iq_bytes_and_multipart_pass_through_unchanged(self):
		room = await self.relay.create_room({"kind": "iq", "meta": {"format": "fc32", "sample_rate": 2e6}})
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
		room = await self.relay.create_room({"kind": "raw"})
		rx1, rx2 = self.receiver(room), self.receiver(room)
		tx = self.sender(room)
		await asyncio.sleep(0.3)
		await tx.send(b"hello")
		self.assertEqual(await self.recv(rx1), [b"hello"])
		self.assertEqual(await self.recv(rx2), [b"hello"])

	async def test_file_room_uses_push_and_tracks_progress(self):
		room = await self.relay.create_room({"kind": "file", "meta": {"filename": "cap.iq"}})
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
		room = await self.relay.create_room({"kind": "raw", "rate_limit": 64 * 1024})
		tx = self.sender(room)
		chunk = b"x" * 16 * 1024
		for _ in range(20):  # 320KB 를 한 번에 → 1초 분량(64KB) 넘는 건 버려져야 함
			await tx.send(chunk)
		await asyncio.sleep(0.5)
		self.assertGreater(room.bytes_dropped, 0)
		self.assertLessEqual(room.bytes_in, 64 * 1024 + len(chunk))

	async def test_total_limit_closes_room_and_frees_ports(self):
		room = await self.relay.create_room({"kind": "raw", "total_limit": 1024 * 1024})
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

	async def test_ip_allowlist_blocks_other_senders(self):
		blocked = await self.relay.create_room({"kind": "raw", "allow_ips": ["10.0.0.1"]})
		rx = self.receiver(blocked)
		tx = self.sender(blocked)
		await asyncio.sleep(0.3)
		await tx.send(b"should not pass")
		with self.assertRaises(asyncio.TimeoutError):
			await self.recv(rx, timeout=0.8)
		self.assertEqual(blocked.bytes_in, 0)

		allowed = await self.relay.create_room({"kind": "raw", "allow_ips": ["127.0.0.0/8"]})
		rx2 = self.receiver(allowed)
		tx2 = self.sender(allowed)
		await asyncio.sleep(0.3)
		await tx2.send(b"ok")
		self.assertEqual(await self.recv(rx2), [b"ok"])

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

	async def test_websocket_needs_room_token_and_streams_stats(self):
		room = await self.relay.create_room({"kind": "iq"})
		resp = await self.client.get(f"/relay/ws/{room.id}?token=wrong")
		self.assertEqual(resp.status, 404)
		ws = await self.client.ws_connect(f"/relay/ws/{room.id}?token={room.token}")
		hello = await ws.receive_json(timeout=2)
		self.assertEqual(hello["type"], "hello")
		self.assertNotIn("token", hello)
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
