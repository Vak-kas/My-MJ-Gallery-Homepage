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


class _GameBase(unittest.IsolatedAsyncioTestCase):
	"""실시간 게임 방 테스트 공통 (서버 띄우기·접속·메시지 기다리기)."""

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

class GameTestCase(_GameBase):
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


class CatchTestCase(_GameBase):
	async def create_catch(self):
		resp = await self.client.post("/games", json={"kind": "catchmind", "title": "그림", "owner": "seo"}, headers=HEAD)
		self.assertEqual(resp.status, 201)
		return await resp.json()

	async def latest_state(self, ws, pred, tries=30):
		for _ in range(tries):
			msg = await self.recv(ws, "state")
			if pred(msg["state"]):
				return msg["state"]
		self.fail("원하는 상태가 오지 않음")

	async def test_full_turn(self):
		room = await self.create_catch()
		logic = self.hub.rooms[room["id"]].logic
		logic.words = ["고양이"]  # 제시어 고정
		a, b, c = await self.join(room, "a", "가"), await self.join(room, "b", "나"), await self.join(room, "c", "다")
		await b.send_json({"type": "start"})
		self.assertIn("방장", (await self.recv(b, "error"))["text"])  # 방장은 처음 들어온 a
		await a.send_json({"type": "start"})
		st_a = await self.latest_state(a, lambda s: s["status"] == "choosing")
		self.assertTrue(st_a["is_drawer"])
		self.assertEqual(st_a["options"], ["고양이"])
		st_b = await self.latest_state(b, lambda s: s["status"] == "choosing")
		self.assertIsNone(st_b["options"])  # 다른 사람에겐 제시어 안 보임
		await a.send_json({"type": "choose", "i": 0})
		st_b = await self.latest_state(b, lambda s: s["status"] == "drawing")
		self.assertEqual((st_b["word"], st_b["mask"]), (None, "○○○"))
		# 그림 → 다른 사람에게 바로 전달
		await a.send_json({"type": "draw", "id": 1, "c": "#111111", "w": 7, "p": [[10, 10], [20, 20]]})
		draw = await self.recv(c, "draw")
		self.assertEqual(draw["p"], [[10, 10], [20, 20]])
		await a.send_json({"type": "draw", "id": 2, "c": "#abcdef", "w": 7, "p": [[1, 1]]})  # 없는 색은 무시
		# 늦게 온 사람도 지금까지 그림을 받음
		d = await self.client.ws_connect(f"/relay/ws/game/{room['id']}?token={room['token']}&pid={'d' * 16}&name=라")
		sync = await self.recv(d, "sync")
		self.assertEqual(len(sync["strokes"]), 1)
		# 거의 맞음 → 나에게만, 정답 → '정답!' 알림 (답 자체는 채팅에 안 나감)
		await b.send_json({"type": "chat", "text": "고양"})
		self.assertIn("거의", (await self.recv(b, "close"))["text"])
		await asyncio.sleep(0.7)
		await b.send_json({"type": "chat", "text": "고 양 이"})
		note = await self.recv(c, "chat")
		while "정답" not in note["text"]:
			note = await self.recv(c, "chat")
		self.assertNotIn("고양이", note["text"])
		# 맞힌 사람·그린 사람은 답이 들어간 말을 못 보냄
		await asyncio.sleep(0.7)
		await b.send_json({"type": "chat", "text": "고양이 쉽네"})
		self.assertIn("보낼 수 없어요", (await self.recv(b, "error"))["text"])
		# 나머지도 맞히면 정답 공개
		await c.send_json({"type": "chat", "text": "고양이"})
		await d.send_json({"type": "chat", "text": "고양이"})
		st = await self.latest_state(c, lambda s: s["status"] == "reveal")
		self.assertEqual(st["word"], "고양이")
		scores = {p["name"]: p["score"] for p in st["players"]}
		self.assertGreater(scores["나"], scores["다"])  # 먼저 맞힐수록 점수 큼
		self.assertEqual(scores["가"], 60)  # 그린 사람: 맞힌 사람마다 +20
		for ws in (a, b, c, d):
			await ws.close()

	async def test_timer_hint_and_game_end(self):
		import time as _t

		room = await self.create_catch()
		r = self.hub.rooms[room["id"]]
		logic = r.logic
		logic.words = ["바나나우유"]
		a, b = await self.join(room, "a", "가"), await self.join(room, "b", "나")
		await a.send_json({"type": "settings", "rounds": 1, "turn_time": 40})
		await a.send_json({"type": "start"})
		await self.latest_state(b, lambda s: s["status"] == "choosing")
		now = _t.time()
		await self.hub.tick(now + 13)  # 고르지 않으면 자동으로
		st = await self.latest_state(b, lambda s: s["status"] == "drawing")
		self.assertEqual(st["mask"], "○○○○○")
		await self.hub.tick(logic.started + 21)  # 절반 → 글자 하나 공개
		st = await self.latest_state(b, lambda s: s["mask"] and s["mask"].count("○") == 4)
		await self.hub.tick(logic.started + 41)  # 시간 끝 → 정답 공개
		await self.latest_state(b, lambda s: s["status"] == "reveal")
		await self.hub.tick(logic.deadline + 0.1)  # 다음 사람(나) 차례
		st = await self.latest_state(b, lambda s: s["status"] == "choosing")
		self.assertTrue(st["is_drawer"])
		await b.send_json({"type": "pass"})
		await self.latest_state(b, lambda s: s["status"] == "reveal")
		await self.hub.tick(logic.deadline + 0.1)  # 1바퀴 끝
		await self.latest_state(a, lambda s: s["status"] == "end")
		await a.close()
		await b.close()

	async def test_drawer_leaving_moves_on(self):
		room = await self.create_catch()
		logic = self.hub.rooms[room["id"]].logic
		a, b, c = await self.join(room, "a", "가"), await self.join(room, "b", "나"), await self.join(room, "c", "다")
		await a.send_json({"type": "start"})
		await self.latest_state(b, lambda s: s["status"] == "choosing")
		await a.send_json({"type": "choose", "i": 0})
		await self.latest_state(b, lambda s: s["status"] == "drawing")
		await a.close()
		await asyncio.sleep(0.3)
		await self.hub.reap()  # 그리던 사람이 안 돌아옴 → 정답 공개, 방장은 다음 사람
		st = await self.latest_state(b, lambda s: s["status"] == "reveal")
		self.assertTrue(st["is_host"])
		self.assertEqual([p["name"] for p in st["players"]], ["나", "다"])
		await b.close()
		await c.close()
