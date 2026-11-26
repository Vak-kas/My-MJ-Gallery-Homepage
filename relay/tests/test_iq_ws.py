"""IQ 방의 WebSocket 길(iq-relay/1) 테스트 — /relay/ws/<방>/iq/send · /iq/recv.

실행: venv/bin/python -m unittest discover -s relay/tests -t .
"""

import asyncio
import json
import os
import sys
import unittest
from unittest import mock

import zmq
from aiohttp import WSMsgType, WSServerHandshakeError
from aiohttp.test_utils import TestClient, TestServer

sys.path.insert(0, os.path.dirname(__file__))
from test_relay import RelayTestCase, mj_relay  # noqa: E402

HELLO = {"type": "hello", "proto": 1, "format": "sc16", "sample_rate_hz": 250000.0, "center_hz": 433.92e6, "source": "file", "name": "probe-tone"}


class IqWsTestCase(RelayTestCase):
	async def asyncSetUp(self):
		await super().asyncSetUp()
		self.client = TestClient(TestServer(mj_relay.build_app(self.relay)))
		await self.client.start_server()

	async def asyncTearDown(self):
		await self.client.close()
		await super().asyncTearDown()

	async def room(self, **payload):
		return await self.open_room({"kind": "iq", "meta": {"format": "fc32", "sample_rate": 2e6}, **payload})

	def send_url(self, room, token=None):
		return f"/relay/ws/{room.id}/iq/send?token={token or room.sender_token}"

	def recv_url(self, room, token=None):
		return f"/relay/ws/{room.id}/iq/recv?token={token or room.receiver_token}"

	async def open_sender(self, room, hello=None):
		ws = await self.client.ws_connect(self.send_url(room), max_msg_size=4 * mj_relay.MB)
		await ws.send_json(hello or HELLO)
		return ws, await ws.receive_json(timeout=2)

	async def open_receiver(self, room):
		ws = await self.client.ws_connect(self.recv_url(room), max_msg_size=4 * mj_relay.MB)
		return ws, await ws.receive_json(timeout=2)

	async def take(self, ws, count, timeout=2):
		"""메시지 count 개: 글은 dict, 샘플은 bytes."""
		out = []
		for _ in range(count):
			msg = await ws.receive(timeout=timeout)
			self.assertIn(msg.type, (WSMsgType.TEXT, WSMsgType.BINARY), msg)
			out.append(json.loads(msg.data) if msg.type == WSMsgType.TEXT else msg.data)
		return out

	async def refused(self, room, hello):
		ws = await self.client.ws_connect(self.send_url(room))
		if hello is not None:
			await ws.send_json(hello)
		reply = await ws.receive_json(timeout=3)
		self.assertEqual((await ws.receive(timeout=2)).type, WSMsgType.CLOSE)
		await asyncio.sleep(0.1)   # 서버가 닫기를 마칠 시간
		self.assertIsNone(room.iq_sender)
		return reply


class SenderTests(IqWsTestCase):
	async def test_hello_ready_and_room_meta_follow_sender(self):
		room = await self.room()
		ws, ready = await self.open_sender(room)
		self.assertEqual({k: ready[k] for k in ("type", "proto", "room", "rate_limit", "total_limit", "max_message", "receivers")},
						 {"type": "ready", "proto": 1, "room": room.id, "rate_limit": room.rate_limit, "total_limit": room.total_limit, "max_message": 1048576, "receivers": 0})
		self.assertGreater(ready["expires_in"], 3500)
		self.assertEqual((room.meta["format"], room.meta["sample_rate"], room.meta["center_freq"]), ("sc16", 250000.0, 433.92e6))
		stats = room.stats()
		self.assertEqual((stats["senders"], stats["ws_sender"], stats["ready"]), (1, True, False))   # 방 화면의 '보내는 쪽 연결됨'
		self.assertEqual(room.diag_public()["expected_bps"], 1_000_000)
		# 1초마다 통계
		with mock.patch.object(mj_relay, "IQ_SENDER_STATS", 0.05):
			ws2_room = await self.room()
			ws2, _ = await self.open_sender(ws2_room)
			st = await ws2.receive_json(timeout=2)
			self.assertEqual(set(st), {"type", "bytes_in", "bytes_dropped", "receivers", "expires_in"})
			await ws2.close()
		await ws.close()
		await asyncio.sleep(0.1)
		self.assertIsNone(room.iq_sender)
		self.assertEqual(room.stats()["senders"], 0)

	async def test_bad_hello_proto_and_too_fast(self):
		room = await self.room(rate_limit=1_000_000)
		self.assertEqual((await self.refused(room, {"type": "meta"}))["error"], "bad-hello")
		self.assertEqual((await self.refused(room, {**HELLO, "proto": 2}))["error"], "proto")
		self.assertEqual((await self.refused(room, {**HELLO, "format": "cf32"}))["error"], "bad-hello")
		self.assertEqual((await self.refused(room, {**HELLO, "sample_rate_hz": 0}))["error"], "bad-hello")
		self.assertEqual((await self.refused(room, {k: v for k, v in HELLO.items() if k != "sample_rate_hz"}))["error"], "bad-hello")
		reply = await self.refused(room, {**HELLO, "sample_rate_hz": 250001})   # × 4바이트 > 1,000,000
		self.assertEqual((reply["type"], reply["error"]), ("error", "too-fast"))
		self.assertTrue(reply["message"])
		self.assertEqual(room.meta["format"], "fc32")   # 거절한 hello 는 방 설정을 안 바꿈
		with mock.patch.object(mj_relay, "IQ_HELLO_WAIT", 0.2):   # hello 가 안 옴
			self.assertEqual((await self.refused(room, None))["error"], "bad-hello")
		ws, ready = await self.open_sender(room)   # 딱 상한이면 됨
		self.assertEqual(ready["type"], "ready")
		await ws.close()

	async def test_misaligned_and_too_big_close_the_sender(self):
		room = await self.room()
		ws, _ = await self.open_sender(room)
		await ws.send_bytes(b"\x00" * 1002)   # sc16 = 4바이트 단위
		self.assertEqual((await ws.receive_json(timeout=2))["error"], "misaligned")
		self.assertEqual((await ws.receive(timeout=2)).type, WSMsgType.CLOSE)
		ws, _ = await self.open_sender(room)
		await ws.send_bytes(b"\x00" * (mj_relay.IQ_MAX_MESSAGE + 4))
		self.assertEqual((await ws.receive_json(timeout=2))["error"], "too-big")
		self.assertEqual(room.bytes_in, 0)

	async def test_second_sender_409_and_wrong_token_404(self):
		room = await self.room()
		ws, _ = await self.open_sender(room)
		for url, status in ((self.send_url(room), 409), (self.send_url(room, "wrong"), 404), (self.send_url(room, room.receiver_token), 404),
							(self.recv_url(room, room.sender_token), 404), (self.recv_url(room, "wrong"), 404), ("/relay/ws/nope/iq/send?token=x", 404)):
			with self.assertRaises(WSServerHandshakeError) as ctx:
				await self.client.ws_connect(url)
			self.assertEqual(ctx.exception.status, status, url)
		raw = await self.relay.create_room({"kind": "raw"})   # IQ 방이 아니면 없음
		with self.assertRaises(WSServerHandshakeError) as ctx:
			await self.client.ws_connect(self.send_url(raw))
		self.assertEqual(ctx.exception.status, 404)
		await ws.close()
		await asyncio.sleep(0.1)
		ws, ready = await self.open_sender(room)   # 나가면 자리가 남
		self.assertEqual(ready["type"], "ready")
		admin = await self.client.ws_connect(self.recv_url(room, room.token))   # 관리자 토큰은 두 길 모두
		self.assertEqual((await admin.receive_json(timeout=2))["type"], "ready")
		await admin.close()
		await ws.close()

	async def test_rate_limit_drops_and_quota_closes_room(self):
		room = await self.room(rate_limit=64 * 1024)
		ws, _ = await self.open_sender(room, {**HELLO, "sample_rate_hz": 16000})
		for _ in range(10):   # 160KB 를 한꺼번에 → 1초 분량(64KB) 넘는 것은 버림
			await ws.send_bytes(b"\x00" * 16 * 1024)
		await asyncio.sleep(0.3)
		self.assertGreater(room.bytes_dropped, 0)
		self.assertLessEqual(room.bytes_in, 64 * 1024)
		await ws.close()
		room = await self.room(total_limit=mj_relay.MB)
		ws, _ = await self.open_sender(room, {**HELLO, "sample_rate_hz": 1e6})
		for _ in range(5):
			await ws.send_bytes(b"\x00" * 256 * 1024)
		kinds = []
		for _ in range(6):
			msg = await ws.receive(timeout=3)
			if msg.type != WSMsgType.TEXT:
				break
			kinds.append(json.loads(msg.data).get("error") or json.loads(msg.data)["type"])
		self.assertIn("quota", kinds)
		await asyncio.sleep(0.2)
		self.assertNotIn(room.id, self.relay.rooms)


class ReceiverTests(IqWsTestCase):
	async def test_receiver_gets_hello_binary_meta_gap_bye_in_order(self):
		room = await self.room()
		rx, ready = await self.open_receiver(room)
		self.assertEqual(ready, {"type": "ready", "proto": 1, "room": room.id, "sending": False})
		tx, tx_ready = await self.open_sender(room)
		self.assertEqual(tx_ready["receivers"], 1)
		a, b = os.urandom(4 * 1000), os.urandom(4 * 3)
		await tx.send_bytes(a)
		await tx.send_json({"type": "meta", "center_hz": 434.0e6})
		await tx.send_json({"type": "gap", "lost_samples": 7, "filled": True, "where": "device"})
		await tx.send_json({"type": "whatever", "x": 1})   # 모르는 type 은 무시
		await tx.send_bytes(b)
		await tx.send_json({"type": "bye"})
		await tx.close()
		got = await self.take(rx, 6)
		self.assertEqual(got, [HELLO, a, {"type": "meta", "center_hz": 434.0e6}, {"type": "gap", "lost_samples": 7, "filled": True, "where": "device"}, b, {"type": "bye"}])
		self.assertEqual(room.meta["center_freq"], 434.0e6)   # meta 가 방 설정도 고침
		self.assertEqual((room.bytes_in, room.messages), (len(a) + len(b), 2))
		self.assertEqual(room.stats()["receivers"], 1)
		self.assertEqual(room.receiver_count(), 1)
		with self.assertRaises(asyncio.TimeoutError):   # bye 는 한 번만
			await rx.receive(timeout=0.3)
		await rx.close()
		await asyncio.sleep(0.1)
		self.assertEqual(room.receiver_count(), 0)

	async def test_bye_even_without_bye_and_late_receiver_gets_current_hello(self):
		room = await self.room()
		tx, _ = await self.open_sender(room)
		await tx.send_json({"type": "meta", "sample_rate_hz": 500000.0, "format": "sc8"})
		await asyncio.sleep(0.1)
		rx, ready = await self.open_receiver(room)   # 늦게 붙어도 지금의 hello (meta 를 합친 값)
		self.assertTrue(ready["sending"])
		self.assertEqual((await self.take(rx, 1))[0], {**HELLO, "sample_rate_hz": 500000.0, "format": "sc8"})
		self.assertEqual((room.meta["format"], room.meta["sample_rate"]), ("sc8", 500000.0))
		await tx.send_bytes(b"\x01\x02")   # 이제 샘플은 2바이트
		self.assertEqual(await self.take(rx, 1), [b"\x01\x02"])
		await tx.close()   # bye 없이 끊김
		self.assertEqual(await self.take(rx, 1), [{"type": "bye"}])
		self.assertEqual(room.stats()["senders"], 0)
		await rx.close()

	async def test_probe_tells_receivers_nothing(self):
		room = await self.room()
		rx, _ = await self.open_receiver(room)
		probe, ready = await self.open_sender(room, {"type": "hello", "proto": 1, "format": "sc16", "sample_rate_hz": 1.0, "probe": True})
		self.assertEqual((ready["type"], ready["receivers"]), ("ready", 1))
		await probe.send_bytes(b"\x00" * 400)   # 연결 확인용이라 받지 않음
		await asyncio.sleep(0.1)
		self.assertEqual((room.meta["format"], room.bytes_in, room.stats()["senders"]), ("fc32", 0, 0))
		await probe.close()
		with self.assertRaises(asyncio.TimeoutError):
			await rx.receive(timeout=0.4)
		await rx.close()

	async def test_too_many_receivers_429_and_closed_on_room_close(self):
		room = await self.room()
		rxs = [(await self.open_receiver(room))[0] for _ in range(mj_relay.MAX_VIEWERS_PER_ROOM)]
		with self.assertRaises(WSServerHandshakeError) as ctx:
			await self.client.ws_connect(self.recv_url(room))
		self.assertEqual(ctx.exception.status, 429)
		tx, _ = await self.open_sender(room)
		await self.take(rxs[0], 1)   # hello
		await self.relay.close_room(room.id, "관리자가 닫았습니다")
		self.assertEqual(await self.take(rxs[0], 1), [{"type": "closed", "reason": "관리자가 닫았습니다"}])
		kinds = []
		for _ in range(3):
			msg = await tx.receive(timeout=2)
			if msg.type != WSMsgType.TEXT:
				break
			kinds.append(json.loads(msg.data)["type"])
		self.assertIn("closed", kinds)


class _FakeWs:
	"""막을 수 있는 받는 쪽: gate 가 닫혀 있으면 send 가 기다림."""

	def __init__(self):
		self.gate = asyncio.Event()
		self.gate.set()
		self.got = []

	async def send_str(self, text):
		await self.gate.wait()
		self.got.append(json.loads(text))

	async def send_bytes(self, data):
		await self.gate.wait()
		self.got.append(bytes(data))


class SlowReceiverTests(unittest.IsolatedAsyncioTestCase):
	async def test_slow_receiver_gets_relay_gap_and_others_are_not_delayed(self):
		room = mj_relay.Room(id="r", token="t", sender_token="s", receiver_token="v", kind="iq", meta={"format": "sc16"}, allow_ips=[],
							 in_port=0, out_port=0, rate_limit=1, total_limit=1, created_at=0, expires_at=0)
		slow, fast = mj_relay.IqReceiver(_FakeWs(), limit=4), mj_relay.IqReceiver(_FakeWs(), limit=4)
		slow.ws.gate.clear()
		for rx in (slow, fast):
			room.iq_receivers.add(rx)
			rx.task = asyncio.create_task(rx.run())
		chunks = [bytes([i]) * 8 for i in range(20)]
		for chunk in chunks:
			room.fan_iq(chunk)        # 넣는 쪽은 기다리지 않음 (await 가 없음)
			await asyncio.sleep(0)    # 빠른 받는 쪽은 그때그때 가져감
			await asyncio.sleep(0)
		self.assertEqual(fast.ws.got, chunks)             # 다른 받는 쪽은 안 밀림
		self.assertEqual(slow.ws.got, [])
		self.assertEqual(slow.lost_bytes, 8 * 16)         # 줄(4개)을 넘은 16개를 버림
		slow.ws.gate.set()
		await asyncio.sleep(0.05)
		self.assertEqual(slow.ws.got, chunks[:4])
		room.fan_iq(b"\xff" * 8)                          # 자리가 나면 gap 부터
		room.fan_iq(json.dumps({"type": "bye"}))
		await asyncio.sleep(0.05)
		self.assertEqual(slow.ws.got[4:], [{"type": "gap", "where": "relay", "lost_bytes": 128, "lost_samples": 32, "filled": False}, b"\xff" * 8, {"type": "bye"}])
		self.assertEqual(fast.ws.got[-2:], [b"\xff" * 8, {"type": "bye"}])
		for rx in (slow, fast):
			rx.task.cancel()

	async def test_gap_comes_before_text_when_stream_ends_while_behind(self):
		rx = mj_relay.IqReceiver(_FakeWs(), limit=1)
		rx.ws.gate.clear()
		rx.task = asyncio.create_task(rx.run())
		rx.offer(b"\x00" * 4, 4)
		rx.offer(b"\x01" * 4, 4)   # 버려짐
		rx.offer(json.dumps({"type": "bye"}), 4)
		rx.ws.gate.set()
		await asyncio.sleep(0.05)
		self.assertEqual(rx.ws.got, [b"\x00" * 4, {"type": "gap", "where": "relay", "lost_bytes": 4, "lost_samples": 1, "filled": False}, {"type": "bye"}])
		rx.task.cancel()


class BridgeTests(IqWsTestCase):
	async def test_websocket_in_goes_out_zmq_sub_and_snapshot(self):
		room = await self.room()
		sub = self.receiver(room)
		tx, _ = await self.open_sender(room)
		await asyncio.sleep(0.3)   # SUB 구독이 전달될 시간
		self.assertTrue(room.stats()["ready"])   # WebSocket 보내는 쪽 + ZMQ 받는 쪽
		payload = os.urandom(4 * 2048)
		await tx.send_bytes(payload)
		self.assertEqual(await self.recv(sub), [payload])
		self.assertEqual(room.snapshot, payload[-mj_relay.SNAPSHOT_SAMPLES * 4:])   # 스냅샷 길이도 hello 의 형식(sc16)으로
		self.assertGreater(room.stats()["rate_bps"], 0)
		await tx.close()

	async def test_zmq_push_in_goes_to_websocket_receivers_with_built_hello(self):
		room = await self.room()
		rx, ready = await self.open_receiver(room)
		self.assertFalse(ready["sending"])
		push = self.sender(room)
		payload = os.urandom(8 * 512)
		for _ in range(40):   # PUSH 가 붙을 때까지
			if room.senders:
				break
			await asyncio.sleep(0.05)
		await push.send(payload)
		await push.send_multipart([b"tag", payload[:16]])   # 마지막 조각(샘플)만
		await push.send(b"\x00" * 7)                        # 샘플이 쪼개진 것은 안 넘김
		await push.send(payload[:8])
		got = await self.take(rx, 4)
		self.assertEqual(got, [{"type": "hello", "proto": 1, "format": "fc32", "sample_rate_hz": 2e6}, payload, payload[:16], payload[:8]])
		late, ready = await self.open_receiver(room)        # ZMQ 보내는 쪽이 있을 때 붙으면 바로 hello
		self.assertTrue(ready["sending"])
		self.assertEqual((await self.take(late, 1))[0]["format"], "fc32")
		push.close(0)
		self.client_socks.remove(push)
		self.assertEqual(await self.take(rx, 1, timeout=4), [{"type": "bye"}])   # ZMQ 보내는 쪽이 나가면 끝을 알림
		await rx.close()
		await late.close()

	async def test_big_zmq_frame_is_split_into_aligned_messages(self):
		room = await self.room(rate_limit=8 * mj_relay.MB)
		rx, _ = await self.open_receiver(room)
		push = self.sender(room)
		for _ in range(40):
			if room.senders:
				break
			await asyncio.sleep(0.05)
		payload = os.urandom(mj_relay.IQ_MAX_MESSAGE + 8 * 100)
		await push.send(payload)
		got = await self.take(rx, 3)
		self.assertEqual([len(x) for x in got[1:]], [mj_relay.IQ_MAX_MESSAGE, 800])
		self.assertEqual(b"".join(got[1:]), payload)
		await rx.close()


if __name__ == "__main__":
	unittest.main()
