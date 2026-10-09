"""실시간 게임 방(mj_game) 테스트.

실행: venv/bin/python -m unittest discover -s relay/tests -t .
"""

import asyncio
import os
import sys
import unittest

from aiohttp.test_utils import TestClient, TestServer

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mj_game  # noqa: E402
import mj_relay  # noqa: E402

API_KEY = "test-key"
HEAD = {"X-Relay-Key": API_KEY}


class GameTestCase(unittest.IsolatedAsyncioTestCase):
	async def asyncSetUp(self):
		self.relay = mj_relay.Relay(mj_relay.Config(api_key=API_KEY, bind_host="127.0.0.1", port_min=5680, port_max=5689))
		await self.relay.start()
		self.hub = mj_game.GameHub(max_rooms=3, seat_grace=0.2)
		await self.hub.start()
		self.client = TestClient(TestServer(mj_relay.build_app(self.relay, game_hub=self.hub)))
		await self.client.start_server()

	async def asyncTearDown(self):
		await self.client.close()
		await self.hub.stop()
		await self.relay.stop()

	async def create(self, **payload):
		resp = await self.client.post("/games", json={"kind": "omok", "title": "한 판", "owner": "seo", **payload}, headers=HEAD)
		self.assertEqual(resp.status, 201)
		return await resp.json()

	async def join(self, room, pid, name):
		ws = await self.client.ws_connect(f"/relay/ws/game/{room['id']}?token={room['token']}&pid={pid * 16}&name={name}")
		await self.recv(ws, "hello")
		return ws

	async def recv(self, ws, kind, timeout=2):
		while True:
			msg = await asyncio.wait_for(ws.receive_json(), timeout)
			if msg.get("type") == kind:
				return msg

	async def state(self, ws):
		return (await self.recv(ws, "state"))["state"]

	async def test_api_key_and_token(self):
		self.assertEqual((await self.client.post("/games", json={"kind": "omok"})).status, 401)
		self.assertEqual((await self.client.post("/games", json={"kind": "chess"}, headers=HEAD)).status, 400)
		room = await self.create()
		resp = await self.client.get(f"/relay/ws/game/{room['id']}?token=nope&pid={'a' * 16}")
		self.assertEqual(resp.status, 404)

	async def test_play_to_five_in_a_row(self):
		room = await self.create()
		a = await self.join(room, "a", "흑돌")
		b = await self.join(room, "b", "백돌")
		await a.send_json({"type": "sit", "seat": "black"})
		await b.send_json({"type": "sit"})
		st = await self.state(b)
		while st["status"] != "playing":
			st = await self.state(b)
		self.assertEqual(st["seats"]["white"]["name"], "백돌")
		msg = await self.recv(a, "state")
		while msg["state"]["status"] != "playing":
			msg = await self.recv(a, "state")
		self.assertEqual(msg["you"], "black")  # 각자 자기 자리를 받음
		# 백이 먼저 두려 하면 거절
		await b.send_json({"type": "move", "x": 0, "y": 0})
		self.assertIn("차례", (await self.recv(b, "error"))["text"])
		for i in range(5):
			await a.send_json({"type": "move", "x": 3 + i, "y": 7})
			if i < 4:
				await b.send_json({"type": "move", "x": 3 + i, "y": 8})
		st = await self.state(a)
		while st["status"] != "over":
			st = await self.state(a)
		self.assertEqual(st["winner"], "black")
		self.assertEqual(len(st["win_line"]), 5)
		self.assertEqual(st["wins"], {"black": 1, "white": 0})
		# 다시 하기 → 흑백이 바뀜
		await b.send_json({"type": "rematch"})
		st = await self.state(a)
		while st["status"] != "playing":
			st = await self.state(a)
		self.assertEqual(st["seats"]["black"]["name"], "백돌")
		self.assertEqual(st["wins"], {"black": 0, "white": 1})
		await a.close()
		await b.close()

	async def test_occupied_cell_and_undo(self):
		room = await self.create()
		a, b = await self.join(room, "a", "A"), await self.join(room, "b", "B")
		await a.send_json({"type": "sit", "seat": "black"})
		await b.send_json({"type": "sit", "seat": "white"})
		await a.send_json({"type": "move", "x": 7, "y": 7})
		await b.send_json({"type": "move", "x": 7, "y": 7})
		self.assertIn("둘 수 없어요", (await self.recv(b, "error"))["text"])
		await b.send_json({"type": "move", "x": 8, "y": 8})
		await b.send_json({"type": "undo-req"})
		await a.send_json({"type": "undo-ok"})
		st = await self.state(a)
		while st["move_count"] != 1 or st["undo_from"]:
			st = await self.state(a)
		self.assertEqual(st["turn"], "white")
		self.assertEqual(st["board"].count("w"), 0)
		await a.close()
		await b.close()

	async def test_reconnect_keeps_seat_and_leaving_forfeits(self):
		room = await self.create()
		a, b = await self.join(room, "a", "A"), await self.join(room, "b", "B")
		await a.send_json({"type": "sit", "seat": "black"})
		await b.send_json({"type": "sit", "seat": "white"})
		await a.send_json({"type": "move", "x": 1, "y": 1})
		await self.state(b)
		await a.close()
		a2 = await self.client.ws_connect(f"/relay/ws/game/{room['id']}?token={room['token']}&pid={'a' * 16}&name=A")
		hello = await self.recv(a2, "hello")
		self.assertEqual(hello["seat"], "black")  # 같은 pid 면 자리 그대로
		await a2.close()
		await asyncio.sleep(0.3)
		await self.hub.reap()
		st = self.hub.rooms[room["id"]].logic.snapshot(self.hub.rooms[room["id"]])
		self.assertEqual((st["status"], st["winner"]), ("over", "white"))  # 안 돌아오면 상대 승
		await b.close()

	async def test_spectator_cannot_play(self):
		room = await self.create()
		a, b, c = await self.join(room, "a", "A"), await self.join(room, "b", "B"), await self.join(room, "c", "C")
		await a.send_json({"type": "sit"})
		await b.send_json({"type": "sit"})
		await c.send_json({"type": "sit"})
		self.assertIn("찼어요", (await self.recv(c, "error"))["text"])
		await c.send_json({"type": "move", "x": 0, "y": 0})
		self.assertIn("구경", (await self.recv(c, "error"))["text"])
		for ws in (a, b, c):
			await ws.close()
