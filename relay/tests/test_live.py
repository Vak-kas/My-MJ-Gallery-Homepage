"""라이브 방송 시그널링(mj_live) 테스트.

실행: venv/bin/python -m unittest discover -s relay/tests -t .
"""

import asyncio
import os
import sys
import unittest

from aiohttp.test_utils import TestClient, TestServer

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mj_live  # noqa: E402
import mj_relay  # noqa: E402

API_KEY = "test-key"
HEAD = {"X-Relay-Key": API_KEY}


class LiveTestCase(unittest.IsolatedAsyncioTestCase):
	async def asyncSetUp(self):
		self.relay = mj_relay.Relay(mj_relay.Config(api_key=API_KEY, bind_host="127.0.0.1", port_min=5670, port_max=5679))
		await self.relay.start()
		self.hub = mj_live.LiveHub(max_rooms=2)
		await self.hub.start()
		self.client = TestClient(TestServer(mj_relay.build_app(self.relay, self.hub)))
		await self.client.start_server()

	async def asyncTearDown(self):
		await self.client.close()
		await self.hub.stop()
		await self.relay.stop()

	async def create(self, **payload):
		resp = await self.client.post("/live", json={"title": "테스트 방송", "owner_id": 7, "owner": "seo", **payload}, headers=HEAD)
		self.assertEqual(resp.status, 201)
		return await resp.json()

	async def recv(self, ws, kind, timeout=2):
		"""kind 타입 메시지가 올 때까지 읽음."""
		while True:
			msg = await asyncio.wait_for(ws.receive_json(), timeout)
			if msg.get("type") == kind:
				return msg

	async def test_api_requires_key(self):
		resp = await self.client.post("/live", json={})
		self.assertEqual(resp.status, 401)

	async def test_bad_token_rejected(self):
		room = await self.create()
		resp = await self.client.get(f"/relay/ws/live/{room['id']}?token=nope")
		self.assertEqual(resp.status, 404)

	async def test_signal_relay_between_host_and_viewer(self):
		room = await self.create()
		host = await self.client.ws_connect(f"/relay/ws/live/{room['id']}?token={room['token']}")
		hello = await self.recv(host, "hello")
		self.assertEqual(hello["viewers"], [])

		viewer = await self.client.ws_connect(f"/relay/ws/live/{room['id']}?token={room['viewer_token']}&name=민재친구")
		vhello = await self.recv(viewer, "hello")
		self.assertEqual(vhello["role"], "viewer")
		joined = await self.recv(host, "viewer-join")
		self.assertEqual(joined["name"], "민재친구")

		await host.send_json({"type": "signal", "to": joined["id"], "data": {"sdp": "offer"}})
		got = await self.recv(viewer, "signal")
		self.assertEqual(got["data"], {"sdp": "offer"})
		await viewer.send_json({"type": "signal", "data": {"sdp": "answer"}})
		back = await self.recv(host, "signal")
		self.assertEqual((back["from"], back["data"]), (joined["id"], {"sdp": "answer"}))

		await host.send_json({"type": "meta", "data": {"screen": "s1"}})
		self.assertEqual((await self.recv(viewer, "meta"))["data"], {"screen": "s1"})

		await viewer.close()
		left = await self.recv(host, "viewer-leave")
		self.assertEqual(left["id"], joined["id"])
		await host.close()

	async def test_viewer_cannot_signal_other_viewers_or_kick(self):
		room = await self.create()
		host = await self.client.ws_connect(f"/relay/ws/live/{room['id']}?token={room['token']}")
		a = await self.client.ws_connect(f"/relay/ws/live/{room['id']}?token={room['viewer_token']}")
		a_id = (await self.recv(a, "hello"))["id"]
		b = await self.client.ws_connect(f"/relay/ws/live/{room['id']}?token={room['viewer_token']}")
		await self.recv(b, "hello")
		await b.send_json({"type": "kick", "id": a_id})
		await b.send_json({"type": "meta", "data": {"screen": "fake"}})
		await asyncio.sleep(0.2)
		self.assertIn(a_id, self.hub.rooms[room["id"]].viewers)
		for ws in (host, a, b):
			await ws.close()

	async def test_chat_broadcast_and_history(self):
		room = await self.create()
		host = await self.client.ws_connect(f"/relay/ws/live/{room['id']}?token={room['token']}")
		await self.recv(host, "hello")
		viewer = await self.client.ws_connect(f"/relay/ws/live/{room['id']}?token={room['viewer_token']}&name=친구")
		await self.recv(viewer, "hello")
		await viewer.send_json({"type": "chat", "text": "  안녕하세요  "})
		msg = await self.recv(host, "chat")
		self.assertEqual((msg["name"], msg["text"], msg["host"]), ("친구", "안녕하세요", False))
		await viewer.send_json({"type": "chat", "text": "도배"})  # 너무 빨리 보내면 무시
		late = await self.client.ws_connect(f"/relay/ws/live/{room['id']}?token={room['viewer_token']}")
		self.assertEqual([c["text"] for c in (await self.recv(late, "hello"))["chat"]], ["안녕하세요"])
		for ws in (host, viewer, late):
			await ws.close()

	async def test_viewer_limit_and_room_limit(self):
		room = await self.create(max_viewers=1)
		v1 = await self.client.ws_connect(f"/relay/ws/live/{room['id']}?token={room['viewer_token']}")
		await self.recv(v1, "hello")
		resp = await self.client.get(f"/relay/ws/live/{room['id']}?token={room['viewer_token']}")
		self.assertEqual(resp.status, 429)
		await self.create()
		resp = await self.client.post("/live", json={}, headers=HEAD)
		self.assertEqual(resp.status, 409)
		await v1.close()

	async def test_host_end_closes_room(self):
		room = await self.create()
		host = await self.client.ws_connect(f"/relay/ws/live/{room['id']}?token={room['token']}")
		await self.recv(host, "hello")
		viewer = await self.client.ws_connect(f"/relay/ws/live/{room['id']}?token={room['viewer_token']}")
		await self.recv(viewer, "hello")
		await host.send_json({"type": "end"})
		self.assertIn("끝냈", (await self.recv(viewer, "end"))["reason"])
		self.assertNotIn(room["id"], self.hub.rooms)

	async def test_expired_room_is_reaped(self):
		room = await self.create(ttl=60)
		self.hub.rooms[room["id"]].expires_at = 0
		viewer = await self.client.ws_connect(f"/relay/ws/live/{room['id']}?token={room['viewer_token']}")
		await self.recv(viewer, "hello")
		self.assertIn("끝났", (await self.recv(viewer, "end", timeout=8))["reason"])


if __name__ == "__main__":
	unittest.main()
