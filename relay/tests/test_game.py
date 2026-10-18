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


class _Room:
	def __init__(self):
		self.peers, self.notices = {}, []

	def notice(self, text):
		self.notices.append(text)


class _Peer:
	def __init__(self, pid, name):
		self.pid, self.name = pid, name


class OthelloTestCase(unittest.TestCase):
	def setup(self):
		logic, room = mj_game.OthelloLogic(), _Room()
		a, b = _Peer("a", "흑돌"), _Peer("b", "백돌")
		logic.on_message(room, a, {"type": "sit", "seat": "black"})
		logic.on_message(room, b, {"type": "sit", "seat": "white"})
		return logic, room, a, b

	def test_start_flip_and_illegal(self):
		logic, room, a, b = self.setup()
		st = logic.snapshot(room)
		self.assertEqual((st["status"], st["counts"]), ("playing", {"black": 2, "white": 2}))
		self.assertEqual(sorted(map(tuple, st["legal"])), [(2, 3), (3, 2), (4, 5), (5, 4)])
		ok, err = logic.on_message(room, a, {"type": "move", "x": 0, "y": 0})
		self.assertIn("끼워서", err)
		logic.on_message(room, a, {"type": "move", "x": 2, "y": 3})  # (3,3) 백이 뒤집힘
		st = logic.snapshot(room)
		self.assertEqual(st["counts"], {"black": 4, "white": 1})
		self.assertEqual(st["flipped"], [[3, 3]])
		self.assertEqual(st["turn"], "white")
		# 무르기
		logic.on_message(room, a, {"type": "undo-req"})
		logic.on_message(room, b, {"type": "undo-ok"})
		st = logic.snapshot(room)
		self.assertEqual((st["counts"], st["turn"], st["move_count"]), ({"black": 2, "white": 2}, "black", 0))

	def test_pass_and_finish(self):
		logic, room, a, b = self.setup()
		n = 8
		# 흑이 거의 다 차지하고, 백이 둘 곳이 없게 만들어 봄: 빈칸 하나(7,7), 그 옆에 백 하나
		logic.board = ["b"] * (n * n)
		logic.board[7 * n + 7] = "."
		logic.board[7 * n + 6] = "w"
		logic.board[0] = "."
		logic.board[1] = "w"
		logic.history = []
		# 흑이 (0,0)에 두면 (1,0) 백이 뒤집힘 → 백은 둘 곳 없음 → 흑이 한 번 더
		logic.on_message(room, a, {"type": "move", "x": 0, "y": 0})
		st = logic.snapshot(room)
		self.assertEqual((st["turn"], st["passed"]), ("black", "white"))
		self.assertIn("쉬어요", room.notices[-1])
		logic.on_message(room, a, {"type": "move", "x": 7, "y": 7})
		st = logic.snapshot(room)
		self.assertEqual((st["status"], st["winner"]), ("over", "black"))
		self.assertEqual(st["counts"], {"black": 64, "white": 0})
		self.assertIn("64 대 0", st["reason"])
		# 다시 하기 → 흑백 바뀌고 처음 판
		logic.on_message(room, b, {"type": "rematch"})
		st = logic.snapshot(room)
		self.assertEqual((st["status"], st["counts"], st["seats"]["black"]["name"]), ("playing", {"black": 2, "white": 2}, "백돌"))


class DotsTestCase(unittest.TestCase):
	def setup(self, size=3):
		import random
		logic, room = mj_game.DotsLogic(rng=random.Random(0)), _Room()
		a, b = _Peer("a", "가"), _Peer("b", "나")
		logic.on_message(room, a, {"type": "sit"})
		logic.on_message(room, b, {"type": "sit"})
		logic.on_message(room, a, {"type": "size", "size": size})
		return logic, room, a, b

	def move(self, logic, room, peer, line):
		return logic.on_message(room, peer, {"type": "move", "line": line})

	def test_needs_two_and_turns(self):
		import random
		logic, room = mj_game.DotsLogic(rng=random.Random(0)), _Room()
		a = _Peer("a", "가")
		logic.on_message(room, a, {"type": "sit"})
		self.assertIn("두 명", logic.on_message(room, a, {"type": "start"})[1])
		logic, room, a, b = self.setup()
		logic.on_message(room, a, {"type": "start"})
		st = logic.snapshot(room)
		self.assertEqual((st["status"], st["turn"], st["size"]), ("playing", "p1", 3))
		self.assertEqual((len(st["h"]), len(st["v"])), (12, 12))  # 3×3 칸 → 가로 4줄×3, 세로 3줄×4
		self.assertIn("내 차례", self.move(logic, room, b, ["h", 0, 0])[1])
		self.assertEqual(self.move(logic, room, a, ["h", 0, 0]), (True, None))
		self.assertIn("이미 그은", self.move(logic, room, b, ["h", 0, 0])[1])
		self.assertIn("이미 그은", self.move(logic, room, b, ["h", 5, 0])[1])  # 판 밖
		self.assertEqual(logic.snapshot(room)["turn"], "p2")
		self.assertIn("진행 중", logic.on_message(room, _Peer("c", "다"), {"type": "sit"})[1])  # 진행 중엔 못 앉음

	def test_closing_box_gives_point_and_extra_turn(self):
		logic, room, a, b = self.setup()
		logic.on_message(room, a, {"type": "start"})
		self.move(logic, room, a, ["h", 0, 0])  # 칸 (0,0) 위
		self.move(logic, room, b, ["v", 0, 0])  # 왼쪽
		self.move(logic, room, a, ["h", 0, 1])  # 아래 → 세 변
		self.move(logic, room, b, ["v", 1, 0])  # 오른쪽 → 나가 닫음
		st = logic.snapshot(room)
		self.assertEqual(st["boxes"][0], 1)
		self.assertEqual(st["last_boxes"], [[0, 0]])
		self.assertEqual((st["turn"], st["seats"]["p2"]["score"]), ("p2", 1))  # 닫으면 한 번 더

	def test_double_box_and_finish(self):
		logic, room, a, b = self.setup()
		logic.on_message(room, a, {"type": "start"})
		# 선을 다 그어 끝까지: 차례인 사람이 아무 선이나
		while logic.status == "playing":
			peer = a if logic.turn == "p1" else b
			self.move(logic, room, peer, list(logic._free_lines()[0]))
		st = logic.snapshot(room)
		self.assertEqual(st["status"], "over")
		sc = (st["seats"]["p1"]["score"], st["seats"]["p2"]["score"])
		self.assertEqual(sum(sc), 9)
		self.assertTrue(st["winners"])
		self.assertIn("🏁", room.notices[-1])
		# 다시 하기 → 다음 사람부터 새 판
		logic.on_message(room, b, {"type": "rematch"})
		st = logic.snapshot(room)
		self.assertEqual((st["status"], st["turn"], st["move_count"]), ("playing", "p2", 0))

	def test_bot_takes_box_avoids_third_side_and_plays_on_tick(self):
		logic, room, a, b = self.setup()
		logic.on_message(room, b, {"type": "stand"})
		logic.on_message(room, a, {"type": "add-bot"})
		self.assertEqual(logic.snapshot(room)["seats"]["p2"]["name"], "🤖 컴퓨터 1")
		logic.on_message(room, a, {"type": "start"})
		# 칸 (1,1) 에 세 변을 만들어 둠 → 컴퓨터는 그 칸을 먹어야 함
		for ln in (("h", 1, 1), ("h", 1, 2), ("v", 1, 1)):
			logic._set(logic.h, logic.v, *ln, 0)
		self.assertEqual(logic.bot_line(), ("v", 2, 1))
		# 세 변짜리가 없으면 어느 칸에도 세 번째 변을 만들지 않는 선
		logic._set(logic.h, logic.v, "v", 2, 1, 0)
		logic.boxes[1 * 3 + 1] = 0
		line = logic.bot_line()
		self.assertTrue(all(logic._sides(logic.h, logic.v, bx, by) < 2 for bx, by in logic._adjacent(*line)))
		# 사람이 두면 컴퓨터 차례 → tick 이 두어 줌 (BOT_DELAY 뒤)
		self.move(logic, room, a, list(logic._free_lines()[0]))
		self.assertEqual(logic.turn, "p2")
		self.assertFalse(logic.tick(room, logic.bot_due - 0.1))
		self.assertTrue(logic.tick(room, logic.bot_due + 0.1))
		self.assertEqual(logic.moves, 2)

	def test_leaving_player_is_replaced_by_bot(self):
		logic, room, a, b = self.setup()
		logic.on_message(room, a, {"type": "start"})
		self.assertIsNone(logic.on_leave(room, "b"))
		self.assertIn("컴퓨터가 대신", room.notices[-1])
		st = logic.snapshot(room)
		self.assertTrue(st["seats"]["p2"]["bot"])
		self.assertIsNone(logic.seat_of("b"))
		self.assertEqual(logic.on_message(room, b, {"type": "resign"}), (False, None))  # 이미 자리가 없음


class _EmitRoom(_Room):
	def __init__(self):
		super().__init__()
		self.events = []

	def emit(self, data, to=None, exclude=None):
		self.events.append(data)


class AlkkagiTestCase(unittest.TestCase):
	def setup(self, count=5):
		import random
		logic, room = mj_game.AlkkagiLogic(rng=random.Random(0)), _EmitRoom()
		a, b = _Peer("a", "흑"), _Peer("b", "백")
		logic.on_message(room, a, {"type": "sit", "seat": "black"})
		logic.on_message(room, b, {"type": "sit", "seat": "white"})
		logic.on_message(room, a, {"type": "options", "count": count})
		logic.on_message(room, a, {"type": "start"})
		return logic, room, a, b

	def place(self, logic, *stones):
		logic.stones = [{"id": i, "owner": o, "x": x, "y": y} for i, o, x, y in stones]

	def flick(self, logic, room, peer, sid, vx, vy, **kw):
		import time as _t
		logic.busy_until = 0  # 장면 재생을 기다리지 않음
		return logic.on_message(room, peer, {"type": "flick", "stone": sid, "vx": vx, "vy": vy, **kw})

	def test_head_on_knocks_out_and_turn_passes(self):
		logic, room, a, b = self.setup()
		self.place(logic, (0, "black", 200, 500), (1, "black", 200, 900), (100, "white", 300, 500), (101, "white", 500, 100))
		self.assertIn("내 차례", self.flick(logic, room, b, 100, -500, 0)[1])
		self.assertIn("내 돌만", self.flick(logic, room, a, 100, 500, 0)[1])
		self.assertEqual(self.flick(logic, room, a, 0, 900, 0), (True, None))
		shot = room.events[-1]
		self.assertEqual((shot["type"], shot["out"]), ("shot", [100]))
		self.assertGreater(len(shot["frames"]), 5)
		st = logic.snapshot(room)
		self.assertEqual((st["turn"], st["seats"]["white"]["left"]), ("white", 1))
		self.assertIn("쳐냈어요", room.notices[-1])

	def test_win_when_opponent_has_no_stones(self):
		logic, room, a, b = self.setup()
		self.place(logic, (0, "black", 200, 500), (100, "white", 300, 500))
		self.flick(logic, room, a, 0, 900, 0)
		st = logic.snapshot(room)
		self.assertEqual((st["status"], st["winner"], st["seats"]["black"]["wins"]), ("over", "black", 1))
		logic.on_message(room, b, {"type": "rematch"})  # 다음 판은 백부터, 돌 5개씩
		st = logic.snapshot(room)
		self.assertEqual((st["status"], st["turn"], len(st["stones"])), ("playing", "white", 10))

	def test_skills_heavy_ice_shield_and_limits(self):
		logic, room, a, b = self.setup()
		far = lambda: next(s for s in logic.stones if s["id"] == 100)["x"]
		# 같은 힘이라도 빙판이면 더 멀리 감
		self.place(logic, (0, "black", 100, 500), (100, "white", 160, 500), (101, "white", 900, 900))
		import copy
		base = copy.deepcopy(logic.stones)
		logic.simulate(logic.stones, 0, 400, 0)
		plain = far()
		logic.stones = copy.deepcopy(base)
		logic.simulate(logic.stones, 0, 400, 0, skill="ice")
		self.assertGreater(far(), plain + 50)
		# 방패: 상대 턴에 내 돌이 3배 무거워 덜 밀림
		logic.stones = copy.deepcopy(base)
		logic.simulate(logic.stones, 0, 400, 0, shield="white")
		self.assertLess(far(), plain - 20)
		# 스킬 쓰면 줄고, 같은 스킬은 한 번만
		logic.stones = copy.deepcopy(base)
		self.assertEqual(self.flick(logic, room, a, 0, 300, 0, skill="shield"), (True, None))
		self.assertEqual(logic.shield, "black")
		self.assertNotIn("shield", logic.snapshot(room)["skills"]["black"]["left"])
		self.flick(logic, room, b, 100, -50, 0)  # 백 차례에 흑 돌들이 무거움 → 끝나면 방패 꺼짐
		self.assertIsNone(logic.shield)
		self.assertIn("쓸 수 없어요", self.flick(logic, room, a, 0, 300, 0, skill="shield")[1])

	def test_curve_and_bomb_change_paths(self):
		logic, _, _, _ = self.setup()
		import copy
		self.place(logic, (0, "black", 500, 900), (101, "white", 900, 100))
		base = copy.deepcopy(logic.stones)
		logic.simulate(logic.stones, 0, 0, -600)
		straight = logic.stones[0]["x"]
		logic.stones = copy.deepcopy(base)
		logic.simulate(logic.stones, 0, 0, -600, skill="curve", curve=1)
		self.assertNotAlmostEqual(logic.stones[0]["x"], straight, delta=30)  # 옆으로 휨
		# 폭탄: 옆에 있던 돌까지 밀려남
		self.place(logic, (0, "black", 500, 800), (100, "white", 500, 600), (101, "white", 600, 600))
		logic.simulate(logic.stones, 0, 0, -500, skill="bomb")
		side = next(s for s in logic.stones if s["id"] == 101)
		self.assertGreater(side["x"], 640)

	def test_bot_finds_clear_shot(self):
		logic, room, a, b = self.setup()
		logic.on_message(room, b, {"type": "resign"})
		logic.on_message(room, b, {"type": "stand"})
		logic.on_message(room, a, {"type": "add-bot"})
		self.assertEqual(logic.snapshot(room)["seats"]["white"]["name"], "🤖 컴퓨터")
		self.place(logic, (100, "white", 300, 300), (101, "white", 900, 900), (0, "black", 300, 420), (1, "black", 700, 100))
		logic.status, logic.turn = "playing", "white"
		sid, vx, vy, _ = logic.bot_shot("white")
		self.assertIn(sid, (100, 101))
		logic._arm_bot()
		self.assertFalse(logic.tick(room, logic.bot_due - 0.1))
		self.assertTrue(logic.tick(room, logic.bot_due + 0.1))
		self.assertEqual(logic.shots, 1)
		self.assertEqual(room.events[-1]["type"], "shot")


class AugOmokTestCase(unittest.TestCase):
	def setup(self):
		import random
		from relay import mj_augomok as A
		self.A = A
		logic, room = A.AugOmokLogic(rng=random.Random(0)), _EmitRoom()
		a, b = _Peer("a", "흑"), _Peer("b", "백")
		logic.on_message(room, a, {"type": "sit", "seat": "black"})
		logic.on_message(room, b, {"type": "sit", "seat": "white"})
		logic.on_message(room, a, {"type": "start"})
		return logic, room, a, b

	def mv(self, logic, room, peer, x, y):
		return logic.on_message(room, peer, {"type": "move", "x": x, "y": y})

	def test_points_fast_bonus_and_stones_fade(self):
		logic, room, a, b = self.setup()
		self.assertEqual(self.mv(logic, room, a, 7, 7), (True, None))
		self.assertEqual(logic.points["black"], 2 + 2)  # 시작 2 + 빠르게 둬서 2
		logic.turn_started -= 10  # 백은 천천히
		self.mv(logic, room, b, 0, 0)
		self.assertEqual(logic.points["white"], 2 + 1)
		self.assertEqual(logic.at(7, 7)["ttl"], 4)  # 흑 턴이 한 번 끝남
		# 흑 돌은 흑 턴 5번 뒤 사라짐 (중간에 판 끝나지 않게 떨어뜨려 둠)
		spots = [(1, 13), (13, 1), (4, 10), (10, 4)]
		for i in range(4):
			self.mv(logic, room, a, *spots[i])
			if i < 3:
				self.mv(logic, room, b, 14, 14 - i * 3)
		self.assertIsNone(logic.at(7, 7))
		self.assertTrue(any(e["type"] == "fade" for e in room.events))
		self.assertIn("거기에는", self.mv(logic, room, b, 1, 13)[1])

	def test_draw_buy_and_pity(self):
		logic, room, a, b = self.setup()
		logic.points["black"] = 3
		self.assertIn("4포인트", logic.on_message(room, a, {"type": "draw"})[1])
		logic.points["black"] = 4
		self.assertEqual(logic.on_message(room, a, {"type": "draw"}), (True, None))
		self.assertEqual(logic.points["black"], 0)
		self.assertEqual(logic.turn, "white")  # 뽑으면 턴 끝
		self.assertTrue(any(e["type"] == "draw" for e in room.events))
		# 천장: 9번 연속 영웅 미만이면 10번째는 영웅 이상 (처음 뽑힌 '일반' 을 영웅 이상으로 다시 뽑음)
		logic.pity["white"] = 9
		real = logic.rng.choices
		rolls = iter([["common"], ["epic"]])
		logic.rng.choices = lambda *args, **kw: next(rolls)
		cid = logic._roll("white")
		logic.rng.choices = real
		self.assertEqual(self.A.CARDS[cid][0], "epic")
		self.assertEqual(logic.pity["white"], 0)
		# 골라 사기
		import random
		logic.rng = random.Random(1)
		logic.shop["white"] = ["gust", "candle", "joker"]
		logic.points["white"] = 3
		self.assertIn("6포인트", logic.on_message(room, b, {"type": "buy", "slot": 0})[1])
		self.assertEqual(logic.on_message(room, b, {"type": "buy", "slot": 1}), (True, None))
		self.assertIn("candle", logic.hand["white"])

	def give(self, logic, seat, *cards):
		logic.hand[seat] = list(cards)

	def test_cards_gust_twin_one_per_turn(self):
		logic, room, a, b = self.setup()
		self.mv(logic, room, a, 7, 7)
		self.give(logic, "white", "gust", "twin")
		self.assertIn("상대 돌", logic.on_message(room, b, {"type": "use", "card": "gust", "target": [0, 0]})[1])
		self.assertEqual(logic.on_message(room, b, {"type": "use", "card": "gust", "target": [7, 7]}), (True, None))
		self.assertIsNone(logic.at(7, 7))
		self.assertIn("한 장만", logic.on_message(room, b, {"type": "use", "card": "twin"})[1])
		self.mv(logic, room, b, 3, 3)
		self.give(logic, "black", "twin")
		logic.on_message(room, a, {"type": "use", "card": "twin"})
		self.mv(logic, room, a, 7, 7)
		self.assertEqual(logic.turn, "black")  # 한 번 더
		self.assertIn("3칸 이상", self.mv(logic, room, a, 8, 8)[1])
		self.mv(logic, room, a, 11, 11)
		self.assertEqual(logic.turn, "white")

	def test_joker_and_steal_make_five(self):
		logic, room, a, b = self.setup()
		for x in range(4):
			logic.cells[logic.key(x, 5)] = {"o": "b", "ttl": 5, "by": "black", "perm": False}
		self.give(logic, "black", "joker")
		logic.on_message(room, a, {"type": "use", "card": "joker", "target": [4, 5]})
		self.assertEqual((logic.status, logic.winner), ("over", "black"))
		self.assertEqual(len(logic.win_line), 5)
		# 강탈로 상대 돌을 빼앗아 다섯
		logic, room, a, b = self.setup()
		for x in range(4):
			logic.cells[logic.key(x, 9)] = {"o": "b", "ttl": 5, "by": "black", "perm": False}
		logic.cells[logic.key(4, 9)] = {"o": "w", "ttl": 5, "by": "white", "perm": False}
		self.give(logic, "black", "steal")
		logic.on_message(room, a, {"type": "use", "card": "steal", "target": [4, 9]})
		self.assertEqual(logic.winner, "black")

	def test_puppet_eternal_blackhole_ruler(self):
		logic, room, a, b = self.setup()
		self.give(logic, "black", "puppet")
		logic.on_message(room, a, {"type": "use", "card": "puppet", "target": [0, 14]})
		self.mv(logic, room, a, 7, 7)
		# 백 차례가 오자마자 (0,14) 에 강제로 놓이고 다시 흑 차례
		self.assertEqual(logic.at(0, 14)["o"], "w")
		self.assertEqual(logic.turn, "black")
		self.assertTrue(any(e["type"] == "puppet" for e in room.events))
		self.give(logic, "black", "eternal")
		logic.on_message(room, a, {"type": "use", "card": "eternal", "target": [7, 7]})
		self.assertTrue(logic.at(7, 7)["perm"])
		self.mv(logic, room, a, 7, 9)
		self.give(logic, "white", "blackhole")
		logic.on_message(room, b, {"type": "use", "card": "blackhole", "target": [7, 8]})
		self.assertIsNotNone(logic.at(7, 7))  # 불멸은 안 삼켜짐
		self.assertIsNone(logic.at(7, 9))
		self.mv(logic, room, b, 2, 2)
		# 지배자: 상대의 가장 긴 줄 돌 2개를 가져옴
		for x in range(3):
			logic.cells[logic.key(10 + x, 12)] = {"o": "w", "ttl": 5, "by": "white", "perm": False}
		self.give(logic, "black", "ruler")
		logic.on_message(room, a, {"type": "use", "card": "ruler"})
		self.assertEqual(sum(1 for x in range(3) if logic.at(10 + x, 12)["o"] == "b"), 2)

	def test_instant_piggy_and_life_grows(self):
		logic, room, a, b = self.setup()
		logic._gain_card(room, "black", "piggy", "buy")
		self.assertEqual((logic.points["black"], logic.hand["black"]), (7, []))
		logic.turns = self.A.GROW_EVERY * 2
		self.mv(logic, room, a, 5, 5)
		self.assertEqual(logic.at(5, 5)["ttl"], logic.life + 2 - 1)  # 놓을 때 7, 내 턴 끝나며 -1

	def test_bot_plays_on_tick(self):
		logic, room, a, b = self.setup()
		logic.on_message(room, b, {"type": "resign"})
		logic.on_message(room, b, {"type": "stand"})
		logic.on_message(room, a, {"type": "add-bot"})
		logic.on_message(room, a, {"type": "rematch"})  # 다음 판은 백(컴퓨터)부터
		self.assertEqual(logic.turn, "white")
		self.assertFalse(logic.tick(room, logic.bot_due - 0.1))
		self.assertTrue(logic.tick(room, logic.bot_due + 0.1))
		self.assertEqual(logic.turn, "black")
		self.assertTrue(logic.cells or logic.hand["white"])
