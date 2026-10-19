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
		if logic.pending:  # 대상 카드가 나왔으면 버림
			logic.on_message(room, a, {"type": "discard"})
		self.assertEqual(logic.turn, "white")  # 뽑기는 돌 두기 대신 → 턴 끝
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


class _ToRoom(_EmitRoom):
	def emit(self, data, to=None, exclude=None):
		self.events.append(data)
		self.sent = getattr(self, "sent", []) + [(data, to, exclude)]


class BaseballTestCase(unittest.TestCase):
	def setup(self, digits=3, skills=True):
		import random
		from relay import mj_baseball as B
		self.B = B
		logic, room = B.BaseballLogic(rng=random.Random(0)), _ToRoom()
		a, b = _Peer("a", "가"), _Peer("b", "나")
		room.peers = {"a": a, "b": b}
		logic.on_message(room, a, {"type": "sit", "seat": "p1"})
		logic.on_message(room, b, {"type": "sit", "seat": "p2"})
		logic.on_message(room, a, {"type": "options", "digits": digits, "skills": skills})
		logic.on_message(room, a, {"type": "start"})
		return logic, room, a, b

	def play(self, logic, room, a, b, sa="123", sb="456"):
		logic.on_message(room, a, {"type": "secret", "value": sa})
		logic.on_message(room, b, {"type": "secret", "value": sb})

	def g(self, logic, room, peer, v):
		return logic.on_message(room, peer, {"type": "guess", "value": v})

	def test_judge(self):
		from relay.mj_baseball import judge, marks, valid_number
		self.assertEqual(judge("123", "132"), (1, 2))
		self.assertEqual(judge("123", "456"), (0, 0))
		self.assertEqual(marks("123", "321"), ["B", "S", "B"])
		self.assertFalse(valid_number("112", 3))
		self.assertTrue(valid_number("0123", 4))

	def test_secret_hidden_and_turns(self):
		logic, room, a, b = self.setup()
		self.assertEqual(logic.status, "setup")
		self.assertIn("서로 다른", logic.on_message(room, a, {"type": "secret", "value": "112"})[1])
		self.play(logic, room, a, b)
		self.assertEqual(logic.status, "playing")
		self.assertEqual(logic.turn, "p1")
		self.assertIsNone(logic.snapshot(room, "b")["secrets"])
		self.assertEqual(logic.snapshot(room, "b")["my_secret"], "456")
		self.assertIsNone(logic.snapshot(room, "x")["my_secret"])  # 구경꾼은 못 봄
		self.assertIn("차례", self.g(logic, room, b, "123")[1])
		self.assertEqual(self.g(logic, room, a, "465"), (True, None))
		self.assertEqual(logic.history["p1"][-1]["s"], 1)
		self.assertEqual(logic.history["p1"][-1]["b"], 2)
		self.assertEqual(logic.turn, "p2")

	def test_last_chance_and_draw(self):
		logic, room, a, b = self.setup()
		self.play(logic, room, a, b)
		self.g(logic, room, a, "456")  # 선공이 맞힘 → 후공 마지막 기회
		self.assertEqual(logic.status, "playing")
		self.assertTrue(logic.snapshot(room, "b")["last_chance"])
		self.g(logic, room, b, "123")
		self.assertEqual(logic.status, "over")
		self.assertIsNone(logic.winner)
		# 다음 판: 후공(이번엔 p2 선공)이 놓치면 선공 승
		logic.on_message(room, a, {"type": "rematch"})
		self.play(logic, room, a, b)
		self.assertEqual(logic.turn, "p2")
		self.g(logic, room, b, "123")
		self.g(logic, room, a, "789")
		self.assertEqual(logic.winner, "p2")

	def test_skills_scout_exclude_pos_double(self):
		logic, room, a, b = self.setup()
		self.play(logic, room, a, b)
		logic.on_message(room, a, {"type": "skill", "id": "scout"})
		self.assertEqual(len(logic.known["p1"]["in"]), 1)
		self.assertIn(logic.known["p1"]["in"][0], "456")
		self.assertIn("한 턴에", logic.on_message(room, a, {"type": "skill", "id": "exclude"})[1])
		intel = [(d, to) for d, to, ex in room.sent if d["type"] == "intel"]
		self.assertEqual([to for _, to in intel], ["a"])  # 정찰 결과는 쓴 사람에게만
		self.g(logic, room, a, "789")
		self.g(logic, room, b, "789")
		logic.on_message(room, a, {"type": "skill", "id": "exclude"})
		self.assertTrue(set(logic.known["p1"]["out"]).isdisjoint("456"))
		self.assertIn("이미", logic.on_message(room, a, {"type": "skill", "id": "scout"})[1])
		self.g(logic, room, a, "789")
		self.g(logic, room, b, "789")
		logic.on_message(room, a, {"type": "skill", "id": "double"})
		self.g(logic, room, a, "654")
		self.assertEqual(logic.turn, "p1")  # 한 번 더
		self.g(logic, room, a, "465")
		self.assertEqual(logic.turn, "p2")
		self.g(logic, room, b, "789")
		logic.on_message(room, a, {"type": "skill", "id": "pos"})
		self.g(logic, room, a, "465")
		self.assertEqual(logic.history["p1"][-1]["pos"], ["S", "B", "B"])
		self.assertIsNone(logic.snapshot(room, "x")["history"]["p1"][-1]["pos"])  # 구경꾼은 자리 표시 못 봄

	def test_fog_shield_swap(self):
		logic, room, a, b = self.setup()
		self.play(logic, room, a, b)
		logic.on_message(room, a, {"type": "skill", "id": "shield"})
		self.g(logic, room, a, "789")
		logic.on_message(room, b, {"type": "skill", "id": "fog"})  # 방패에 막힘
		self.assertFalse(logic.fog["p1"])
		self.assertFalse(logic.shield["p1"])
		self.g(logic, room, b, "789")
		logic.on_message(room, a, {"type": "skill", "id": "fog"})
		self.g(logic, room, a, "789")
		room.sent = []
		self.g(logic, room, b, "132")  # 안개: b 에게만 결과가 가려짐
		to_b = [d for d, to, ex in room.sent if d["type"] == "result" and to == "b"]
		to_rest = [d for d, to, ex in room.sent if d["type"] == "result" and ex == "b"]
		self.assertIsNone(to_b[0]["s"])
		self.assertEqual((to_rest[0]["s"], to_rest[0]["b"]), (1, 2))
		self.assertIsNone(logic.snapshot(room, "b")["history"]["p2"][-1]["s"])
		self.assertEqual(logic.snapshot(room, "a")["history"]["p2"][-1]["s"], 1)
		# 바꿔치기: 내 숫자에 있는 숫자로는 못 바꿈, 바꾸면 상대 기록에 표시
		self.assertIn("없는 숫자", logic.on_message(room, a, {"type": "skill", "id": "swap", "pos": 0, "digit": "2"})[1])
		logic.on_message(room, a, {"type": "skill", "id": "swap", "pos": 0, "digit": "9"})
		self.assertEqual(logic.secret["p1"], "923")
		self.assertTrue(logic.history["p2"][-1]["swap"])

	def test_bot_level_option(self):
		logic, room, a, b = self.setup()
		logic.on_message(room, a, {"type": "resign"})
		logic.on_message(room, a, {"type": "options", "bot_level": "easy"})
		self.assertEqual(logic.bot_level, "easy")
		logic.on_message(room, a, {"type": "options", "bot_level": "nope"})
		self.assertEqual(logic.bot_level, "easy")
		self.assertEqual(logic.snapshot(room, "a")["bot_level"], "easy")
		# 쉬움은 스킬을 안 씀
		self.assertEqual(logic._bot_skill("p1", "p2", ["123"] * 3), (None, None))

	def test_timeout_passes_turn(self):
		import time
		logic, room, a, b = self.setup()
		self.play(logic, room, a, b)
		logic.turn_started = time.time() - self.B.TURN_LIMIT - 1
		self.assertTrue(logic.tick(room, time.time()))
		self.assertEqual(logic.turn, "p2")
		self.assertEqual(logic.turns["p1"], 1)

	def test_bot_plays_and_games_finish(self):
		import random, time
		from relay import mj_baseball as B
		logic, room, a, b = self.setup()
		logic.on_message(room, b, {"type": "resign"})
		logic.on_message(room, b, {"type": "stand"})
		logic.on_message(room, a, {"type": "add-bot"})
		logic.on_message(room, a, {"type": "start"})
		self.assertIsNotNone(logic.secret["p2"])  # 컴퓨터는 바로 정함
		logic.on_message(room, a, {"type": "secret", "value": "012"})
		self.assertEqual(logic.status, "playing")
		for _ in range(200):
			if logic.status != "playing":
				break
			if logic.turn == "p1":
				self.g(logic, room, a, "".join(random.Random(_).sample("0123456789", 3)))
			else:
				logic.bot_due = 0
				logic.tick(room, time.time())
		self.assertEqual(logic.status, "over")
		for digits in (3, 4):  # 컴퓨터끼리
			for seed in range(30):
				L = B.BaseballLogic(rng=random.Random(seed))
				L.digits = digits
				r = _ToRoom()
				for s in L.SEATS:
					L.seats[s], L.names[s] = f"bot:{s}", "봇"
					L.bots.add(s)
					L.secret[s] = "".join(L.rng.sample("0123456789", digits))
				L._begin_play(r)
				for _ in range(300):
					if L.status != "playing":
						break
					L.bot_act(r)
				self.assertEqual(L.status, "over")


class AugOmokMoreCardsTestCase(unittest.TestCase):
	setup = AugOmokTestCase.setup
	mv = AugOmokTestCase.mv
	give = AugOmokTestCase.give

	def use(self, logic, room, peer, card, target=None):
		seat = logic.seat_of(peer.pid)
		self.give(logic, seat, card)
		logic.used_card = False
		return logic.on_message(room, peer, {"type": "use", "card": card, **({"target": target} if target else {})})

	def test_vital_and_wither_stack_permanently(self):
		logic, room, a, b = self.setup()
		logic.events_on = False
		base = logic.current_life()
		self.use(logic, room, a, "vital")
		self.use(logic, room, a, "vital")
		self.use(logic, room, a, "wither")
		self.assertEqual(logic.life_for("black"), base + 2)
		self.assertEqual(logic.life_for("white"), base - 1)
		self.mv(logic, room, a, 7, 7)
		self.assertEqual(logic.at(7, 7)["ttl"], base + 2 - 1)  # 흑 턴 하나 끝남
		self.mv(logic, room, b, 0, 0)
		self.assertEqual(logic.at(0, 0)["ttl"], base - 1 - 1)
		for _ in range(5):  # 시듦은 최소 수명 아래로는 못 깎음
			logic.life_bonus["white"] -= 1
		self.assertEqual(logic.life_for("white"), self.A.MIN_LIFE)
		snap = logic.snapshot(room, "a")
		self.assertEqual(snap["life_of"]["black"], base + 2)
		self.assertTrue(any("수명" in e["name"] for e in snap["effects"]["black"]))

	def test_coupon_clover_peek_freeze_swap_jackpot(self):
		logic, room, a, b = self.setup()
		logic.events_on = False
		self.use(logic, room, a, "coupon")
		cid = logic.shop["black"][0]
		full = self.A.PRICE[self.A.CARDS[cid][0]]
		self.assertEqual(logic.snapshot(room, "a")["shop"][0]["price"], (full + 1) // 2)
		self.use(logic, room, a, "clover")
		logic.rng.choices = lambda *aa, **kk: ["common"]  # 일반이 나와도 한 단계 위(희귀)
		self.assertEqual(self.A.CARDS[logic._roll("black")][0], "rare")
		self.assertFalse(logic.clover["black"])
		del logic.rng.choices
		self.use(logic, room, a, "peek")
		logic.hand["white"] = ["gust"]
		self.assertEqual([c["id"] for c in logic.snapshot(room, "a")["opp_hand"]], ["gust"])
		self.assertIsNone(logic.snapshot(room, "b")["opp_hand"])
		logic.points["black"] = 4
		self.use(logic, room, a, "jackpot")
		self.assertEqual(logic.points["black"], 8)
		logic.hand["black"] = ["swap", "candle"]
		logic.used_card = False
		logic.on_message(room, a, {"type": "use", "card": "swap"})
		self.assertEqual(logic.hand["black"], ["gust"])
		self.assertEqual(logic.hand["white"], ["candle"])
		self.use(logic, room, a, "freeze")
		self.mv(logic, room, a, 7, 7)
		logic.points["white"] = 20
		self.assertIn("얼어", logic.on_message(room, b, {"type": "draw"})[1])
		self.assertIn("얼어", logic.on_message(room, b, {"type": "use", "card": "candle"})[1])
		self.assertEqual(self.mv(logic, room, b, 0, 0), (True, None))  # 돌은 둘 수 있음
		self.mv(logic, room, a, 7, 8)
		self.assertEqual(logic.freeze["white"], 0)  # 한 턴만

	def test_seed_and_timebomb(self):
		logic, room, a, b = self.setup()
		logic.events_on = False
		self.use(logic, room, a, "seed", [3, 3])
		self.assertIn("씨앗", self.mv(logic, room, a, 3, 3)[1])
		self.use(logic, room, a, "timebomb", [10, 10])
		logic.cells[logic.key(11, 11)] = {"o": "w", "ttl": 9, "by": "white", "perm": False}
		logic.cells[logic.key(9, 10)] = {"o": "b", "ttl": 9, "by": "black", "perm": False}
		for i in range(3):
			self.mv(logic, room, a, 0, i * 2)
			if i == 1:
				self.assertEqual(logic.at(3, 3)["o"], "b")  # 내 턴 2번 뒤 싹
			self.mv(logic, room, b, 14, i * 2)
		self.assertIsNone(logic.at(11, 11))
		self.assertIsNone(logic.at(9, 10))  # 내 돌도 터짐
		self.assertNotIn(logic.key(10, 10), logic.locks)

	def test_mirror_clone_ghost(self):
		logic, room, a, b = self.setup()
		logic.events_on = False
		self.mv(logic, room, a, 7, 7)
		self.mv(logic, room, b, 2, 3)
		self.use(logic, room, a, "mirror")
		self.assertEqual(logic.at(12, 11)["o"], "b")
		self.use(logic, room, a, "clone", [7, 7])
		self.assertEqual(len(logic.stones_of("black")), 3)
		self.use(logic, room, a, "ghost", [0, 14])
		self.assertTrue(logic.at(0, 14)["ghost"])
		self.assertFalse(any((c["x"], c["y"]) == (0, 14) for c in logic.snapshot(room, "b")["cells"]))
		self.assertTrue(any((c["x"], c["y"]) == (0, 14) for c in logic.snapshot(room, "a")["cells"]))
		self.mv(logic, room, a, 14, 0)
		self.assertEqual(self.mv(logic, room, b, 0, 14), (True, None))  # 모르고 둠 → 유령 깨짐, 백 돌
		self.assertEqual(logic.at(0, 14)["o"], "w")
		self.assertTrue(any(e.get("icon") == "👻" for e in room.events))

	def test_vortex_thief_tsunami(self):
		logic, room, a, b = self.setup()
		logic.events_on = False
		logic.cells[logic.key(4, 5)] = {"o": "w", "ttl": 5, "by": "white", "perm": False}  # 위
		self.use(logic, room, a, "vortex", [5, 6])
		self.assertIsNone(logic.at(4, 5))
		self.assertEqual(logic.at(5, 5)["o"], "w")  # 시계 방향 한 칸
		logic.cells[logic.key(9, 9)] = {"o": "b", "ttl": 5, "by": "black", "perm": False}
		self.use(logic, room, a, "thief")
		self.assertEqual(logic.at(9, 9)["ttl"], 7)
		self.assertEqual(logic.at(5, 5)["ttl"], 3)
		logic.cells[logic.key(0, 0)] = {"o": "b", "ttl": 5, "by": "black", "perm": False}
		logic.cells[logic.key(14, 14)] = {"o": "b", "ttl": 5, "by": "black", "perm": False}
		n = len(logic.cells)
		self.use(logic, room, a, "tsunami")
		self.assertEqual(len(logic.cells), n - 1)  # 한쪽 모서리 돌만 밀려 나감
		self.assertIsNone(logic.at(9, 9))

	def test_bot_waits_after_card_so_people_can_read(self):
		import time
		logic, room, a, b = self.setup()
		logic.events_on = False
		logic.on_message(room, b, {"type": "stand"})  # 판 중이라 못 일어남 → 직접 컴퓨터로
		logic.bots.add("white")
		self.mv(logic, room, a, 7, 7)
		self.assertGreaterEqual(logic.bot_due - time.time(), self.A.BOT_DELAY - 0.2)
		logic.hand["white"] = ["vital"]
		logic.bot_act(room)  # 카드만 쓰고 아직 안 둠
		self.assertEqual(logic.turn, "white")
		self.assertEqual(logic.hand["white"], [])
		self.assertGreater(logic.bot_due - time.time(), self.A.BOT_READ_DELAY - 0.5)
		logic.bot_act(room)  # 다음 틱에 둠
		self.assertEqual(logic.turn, "black")

	def test_bot_games_still_finish_with_new_cards(self):
		import random
		from relay import mj_augomok as A
		done = 0
		for seed in range(12):
			logic, room = A.AugOmokLogic(rng=random.Random(seed)), _EmitRoom()
			for s in A.AugOmokLogic.SEATS:
				logic.seats[s], logic.names[s] = f"bot:{s}", "봇"
				logic.bots.add(s)
			logic.status, logic.turn = "playing", "black"
			logic._restock("black")
			for s in logic.SEATS:
				logic.hand[s] = random.Random(seed).sample(["vital", "wither", "clone", "ghost", "thief", "jackpot", "seed", "freeze", "clover", "coupon"], 3)
			for _ in range(600):
				if logic.status != "playing":
					break
				logic.bot_act(room)
			done += logic.status == "over"
		self.assertGreaterEqual(done, 11)


class AugOmokAutoUseTestCase(unittest.TestCase):
	"""뽑으면 바로 발동, 대상 카드는 판에서 고르고, 방어 카드만 손에 보관."""
	setup = AugOmokTestCase.setup
	mv = AugOmokTestCase.mv

	def draw_as(self, logic, room, peer, cid):
		logic._roll = lambda s, count_pity=True: cid
		logic.points[logic.seat_of(peer.pid)] = 20
		logic.drew = False
		return logic.on_message(room, peer, {"type": "draw"})

	def test_none_card_fires_at_once_and_turn_continues(self):
		logic, room, a, b = self.setup()
		logic.events_on = False
		logic.cells[logic.key(0, 0)] = {"o": "w", "ttl": 5, "by": "white", "perm": False}
		self.assertEqual(self.draw_as(logic, room, a, "eclipse"), (True, None))
		self.assertEqual(logic.at(0, 0)["ttl"], 4)
		self.assertEqual(logic.hand["black"], [])
		self.assertFalse(logic.used_card)
		draw = [e for e in room.events if e["type"] == "draw"][-1]
		use = [e for e in room.events if e["type"] == "use"][-1]
		self.assertEqual(draw["fate"], "now")
		self.assertTrue(use["auto"])  # 화면은 카드 연출을 한 번만
		self.assertEqual(logic.turn, "white")  # 뽑기 = 돌 두기 대신 → 턴 끝

	def test_this_turn_cards_continue(self):
		logic, room, a, b = self.setup()
		self.draw_as(logic, room, a, "double")
		self.assertEqual(logic.turn, "black")  # 연속 두기는 이어서 둠
		self.assertTrue([e for e in room.events if e["type"] == "draw"][-1]["cont"])
		self.assertIn("한 번", logic.on_message(room, a, {"type": "draw"})[1])
		self.mv(logic, room, a, 7, 7)
		self.assertEqual(logic.turn, "black")
		self.mv(logic, room, a, 9, 9)
		self.assertEqual(logic.turn, "white")

	def test_defense_card_goes_to_hand(self):
		logic, room, a, b = self.setup()
		self.draw_as(logic, room, a, "hourglass")
		self.assertEqual(logic.hand["black"], ["hourglass"])
		self.assertEqual(logic.turn, "white")
		self.assertEqual([e for e in room.events if e["type"] == "draw"][-1]["fate"], "hand")
		self.assertTrue(self.A.card_info("hourglass")["defense"])

	def test_target_card_waits_for_target(self):
		logic, room, a, b = self.setup()
		logic.events_on = False
		# 상대 돌이 없으면 손에 보관 (턴 끝)
		self.draw_as(logic, room, a, "gust")
		self.assertEqual(logic.hand["black"], ["gust"])
		self.assertIsNone(logic.pending)
		self.mv(logic, room, b, 3, 3)
		self.mv(logic, room, a, 7, 7)
		self.mv(logic, room, b, 3, 4)
		# 상대 돌이 있으면 바로 대상 고르기 — 고를 때까지 두기·뽑기 막힘, 고르면 턴 끝
		logic.hand["black"] = []
		self.draw_as(logic, room, a, "gust")
		self.assertEqual(logic.pending, {"seat": "black", "card": "gust"})
		self.assertEqual(logic.snapshot(room, "a")["pending"]["id"], "gust")
		self.assertIsNone(logic.snapshot(room, "b")["pending"])
		self.assertIn("대상", self.mv(logic, room, a, 8, 8)[1])
		self.assertIn("상대 돌", logic.on_message(room, a, {"type": "use", "card": "gust", "target": [7, 7]})[1])
		self.assertEqual(logic.on_message(room, a, {"type": "use", "card": "gust", "target": [3, 3]}), (True, None))
		self.assertIsNone(logic.at(3, 3))
		self.assertIsNone(logic.pending)
		self.assertEqual(logic.turn, "white")
		# 버리기 (역시 턴 끝)
		self.mv(logic, room, b, 3, 3)
		self.draw_as(logic, room, a, "steal")
		self.assertTrue(logic.on_message(room, a, {"type": "discard"})[0])
		self.assertIsNone(logic.pending)
		self.assertEqual(logic.at(3, 3)["o"], "w")
		self.assertEqual(logic.turn, "white")

	def test_bot_resolves_pending_target(self):
		logic, room, a, b = self.setup()
		logic.events_on = False
		self.mv(logic, room, a, 7, 7)
		logic.bots.add("white")
		logic.pending = {"seat": "white", "card": "gust"}
		logic.bot_act(room)
		self.assertIsNone(logic.pending)
		self.assertIsNone(logic.at(7, 7))
		self.assertEqual(logic.turn, "black")  # 대상을 고르면 턴 끝

	def test_dice_reward_and_luck_event_cards_are_granted(self):
		logic, room, a, b = self.setup()
		logic.rng.randint = lambda lo, hi: 4  # 주사위 4: 일반 카드 1장
		logic.rng.choice = lambda seq: "candle" if "candle" in seq else seq[0]
		self.draw_as(logic, room, a, "dice")
		self.assertEqual(logic.hand["black"], ["candle"])
		types = [e["type"] for e in room.events]
		self.assertLess(types.index("dice"), len(types) - 1 - types[::-1].index("draw"))  # 보상 카드 연출은 주사위 뒤에
		logic.hand = {"black": [], "white": []}
		logic.rng.choice = lambda seq: "luck" if "luck" in seq else ("candle" if "candle" in seq else seq[0])
		logic._event(room)
		self.assertEqual(logic.hand, {"black": ["candle"], "white": ["candle"]})


class AugOmokResetCardsTestCase(unittest.TestCase):
	setup = AugOmokTestCase.setup  # 판 준비·두기·카드 주기만 빌려 씀 (기존 시험은 다시 안 돌림)
	mv = AugOmokTestCase.mv
	give = AugOmokTestCase.give

	def test_quake_myreset_grandreset(self):
		logic, room, a, b = self.setup()
		for i in range(4):
			logic.cells[logic.key(i, 0)] = {"o": "b", "ttl": 5, "by": "black", "perm": False}
			logic.cells[logic.key(i, 2)] = {"o": "w", "ttl": 5, "by": "white", "perm": False}
		logic.cells[logic.key(9, 9)] = {"o": "b", "ttl": 5, "by": "black", "perm": True}
		# 지진: 무작위 4개 (불멸 빼고)
		self.give(logic, "black", "quake")
		logic.on_message(room, a, {"type": "use", "card": "quake"})
		self.assertEqual(len(logic.cells), 9 - 4)
		self.assertIn(logic.key(9, 9), logic.cells)
		self.assertEqual(room.events[-1]["type"], "use")
		# 나의 회귀: 내 돌(불멸 빼고) 다 거두고 하나에 2P, 내 턴은 그대로
		logic.used_card = False
		mine = sum(1 for k, v in logic.stones_of("black") if not v["perm"])
		pts = logic.points["black"]
		self.give(logic, "black", "myreset")
		logic.on_message(room, a, {"type": "use", "card": "myreset"})
		self.assertEqual(logic.points["black"], pts + 2 * mine)
		self.assertEqual([k for k, v in logic.stones_of("black")], [logic.key(9, 9)])
		self.assertEqual(logic.turn, "black")
		self.assertEqual(self.mv(logic, room, a, 7, 7), (True, None))  # 이어서 둠
		# 대회귀: 판 전체 (불멸까지) 비우고 쓴 사람 턴부터
		self.give(logic, "white", "grandreset")
		logic.on_message(room, b, {"type": "use", "card": "grandreset"})
		self.assertEqual(logic.cells, {})
		self.assertEqual(logic.turn, "white")
		self.assertEqual(self.mv(logic, room, b, 3, 3), (True, None))

	def test_draw_is_shown_to_everyone(self):
		logic, room, a, b = self.setup()
		logic.points["black"] = 10
		logic.on_message(room, a, {"type": "draw"})
		draw = next(e for e in room.events if e["type"] == "draw")
		self.assertIsNotNone(draw["card"])  # 모두에게 카드 이름까지

	def test_undo_points_and_charity(self):
		logic, room, a, b = self.setup()
		self.mv(logic, room, a, 7, 7)
		logic.turn_started -= 10
		self.mv(logic, room, b, 3, 3)
		self.give(logic, "black", "undo")
		logic.on_message(room, a, {"type": "use", "card": "undo"})
		self.assertIsNone(logic.at(3, 3))  # 상대 마지막 돌을 물림
		logic.points.update(black=1, white=5)
		logic.used_card = False
		self.give(logic, "black", "pickpocket")
		logic.on_message(room, a, {"type": "use", "card": "pickpocket"})
		self.assertEqual(logic.points, {"black": 4, "white": 2})
		logic.used_card = False
		ttl = logic.at(7, 7)["ttl"]
		self.give(logic, "black", "charity")
		logic.on_message(room, a, {"type": "use", "card": "charity"})
		self.assertEqual((logic.points["black"], logic.points["white"], logic.at(7, 7)["ttl"]), (1, 5, ttl + 1))

	def test_timed_and_permanent_effects(self):
		logic, room, a, b = self.setup()
		self.assertEqual(self.A.card_info("compound")["dur"], "지속 3턴")
		self.assertEqual(self.A.card_info("fifth")["dur"], "영구")
		self.assertEqual(self.A.card_info("gust")["dur"], "1회용")
		self.give(logic, "black", "fifth", "sturdy", "compound")
		logic.on_message(room, a, {"type": "use", "card": "fifth"})
		st = logic.snapshot(room)
		self.assertEqual([e["dur"] for e in st["effects"]["black"]], ["영구"])  # 상대도 보는 효과 목록
		spots = [(0, 0), (4, 0), (8, 0), (12, 0), (0, 4)]
		for i, (x, y) in enumerate(spots):
			logic.used_card = False
			if i == 0:
				logic.on_message(room, a, {"type": "use", "card": "sturdy"})
			if i == 1:
				pts = logic.points["black"]
				logic.on_message(room, a, {"type": "use", "card": "compound"})
			self.mv(logic, room, a, x, y)
			if i == 0:
				self.assertEqual(logic.at(0, 0)["ttl"], logic.life + 1 - 1)  # 단단한 돌 +1, 턴 끝 -1
			if i == 1:
				self.assertEqual(logic.points["black"], pts + 3)  # 빠르게 2 + 복리 1
			if i < 4:
				logic.turn_started -= 10
				self.mv(logic, room, b, 14, 14 - i * 3)
		# 다섯 번째 돌 → 한 번 더 (2칸 이상)
		self.assertEqual(logic.turn, "black")
		self.assertTrue(logic.extra and logic.extra.get("bonus"))
		self.assertIn("2칸 이상", self.mv(logic, room, a, 1, 4)[1])
		self.assertEqual(self.mv(logic, room, a, 7, 9), (True, None))
		self.assertEqual(logic.turn, "white")
		# 영구는 두 번 켤 수 없음
		logic.turn = "black"
		logic.used_card = False
		self.give(logic, "black", "fifth")
		self.assertIn("이미 켜져", logic.on_message(room, a, {"type": "use", "card": "fifth"})[1])

	def test_dark_memory_sleep_points(self):
		logic, room, a, b = self.setup()
		room.peers = {"a": 1, "b": 1}
		self.mv(logic, room, a, 7, 7)
		self.give(logic, "white", "dark")
		logic.on_message(room, b, {"type": "use", "card": "dark"})
		self.assertEqual(logic.snapshot(room, "a")["cells"], [])  # 흑 화면엔 안 보임
		self.assertTrue(logic.snapshot(room, "b")["cells"])        # 백은 보임
		self.mv(logic, room, b, 3, 3)
		self.assertIn("거기에는", self.mv(logic, room, a, 3, 3)[1])  # 안 보여도 못 둠
		# 기억력: 모두에게 회색
		logic.used_card = False
		self.give(logic, "black", "memory")
		logic.on_message(room, a, {"type": "use", "card": "memory"})
		st = logic.snapshot(room, "b")
		self.assertEqual({c["o"] for c in st["cells"]}, {"g"})
		self.assertIsNone(st["cells"][0]["ttl"])
		# 동반 성장·공멸
		logic.points.update(black=1, white=2)
		logic.used_card = False
		self.give(logic, "black", "together")
		logic.on_message(room, a, {"type": "use", "card": "together"})
		self.assertEqual(logic.points, {"black": 5, "white": 6})
		self.mv(logic, room, a, 10, 10)  # 빠르게 둬서 흑 +2 → 7
		self.assertEqual(logic.points, {"black": 7, "white": 6})
		self.give(logic, "white", "famine")
		logic.on_message(room, b, {"type": "use", "card": "famine"})
		self.assertEqual(logic.points, {"black": 3, "white": 2})
		self.give(logic, "white", "sleep")
		self.assertIn("한 장만", logic.on_message(room, b, {"type": "use", "card": "sleep"})[1])  # 이번 턴엔 이미 씀

	def test_sleep_seal_lock_unlock_events(self):
		logic, room, a, b = self.setup()
		self.give(logic, "black", "sleep")
		logic.on_message(room, a, {"type": "use", "card": "sleep"})
		self.mv(logic, room, a, 7, 7)
		self.assertEqual(logic.turn, "black")  # 백은 쉼
		self.assertTrue(any(e["type"] == "event" for e in room.events))
		# 봉인: 3×3 빈칸에 못 둠, 시간 지나면 풀림
		logic.used_card = False
		self.give(logic, "black", "seal")
		logic.on_message(room, a, {"type": "use", "card": "seal", "target": [3, 3]})
		self.assertIn("봉인", self.mv(logic, room, a, 3, 4)[1])
		# 금고(잠금) → 3P 로 해금 (턴 안 씀)
		logic.locks[logic.key(12, 12)] = {"kind": "lock", "ttl": 0, "region": 9}
		logic.locks[logic.key(12, 13)] = {"kind": "lock", "ttl": 0, "region": 9}
		self.assertIn("해금", self.mv(logic, room, a, 12, 12)[1])
		logic.points["black"] = 3
		self.assertEqual(logic.on_message(room, a, {"type": "unlock", "x": 12, "y": 12}), (True, None))
		self.assertNotIn(logic.key(12, 13), logic.locks)
		self.assertEqual((logic.points["black"], logic.turn), (0, "black"))
		self.assertIn("봉인은", logic.on_message(room, a, {"type": "unlock", "x": 3, "y": 3})[1])
		# 만능 열쇠
		logic.used_card = False
		self.give(logic, "black", "key")
		logic.on_message(room, a, {"type": "use", "card": "key"})
		self.assertEqual(logic.locks, {})
		# 이벤트: EVENT_EVERY 턴마다
		before = sum(1 for e in room.events if e["type"] == "event")
		logic.turns = self.A.EVENT_EVERY - 1
		self.mv(logic, room, a, 9, 9)
		self.assertEqual(sum(1 for e in room.events if e["type"] == "event"), before + 1)

	def test_stack_duel_dice_roulette_oracle(self):
		logic, room, a, b = self.setup()
		room.peers = {"a": 1, "b": 1}
		for x in range(3):
			logic.cells[logic.key(x, 0)] = {"o": "b", "ttl": 5, "by": "black", "perm": False}
		logic.cells[logic.key(5, 5)] = {"o": "w", "ttl": 5, "by": "white", "perm": False}
		# 돌 업기: 내 돌 위 → 2개로 (3개 + 업은 1 = 4, 하나 더 두면 5)
		self.give(logic, "black", "stack")
		logic.on_message(room, a, {"type": "use", "card": "stack"})
		self.assertEqual(self.mv(logic, room, a, 2, 0), (True, None))
		self.assertEqual(logic.at(2, 0)["h"], 2)
		# 상대도 업기 가능: 상대 돌 위 → 그 칸을 뺏음
		self.mv(logic, room, b, 1, 0)
		self.assertEqual(logic.at(1, 0)["o"], "w")
		self.assertIn("2개까지", self.mv(logic, room, a, 2, 0)[1])  # 이미 2개
		# 결투: 주사위 6 vs 1 → 뺏음
		rolls = iter([6, 1])
		logic.rng.randint = lambda lo, hi: next(rolls)
		self.give(logic, "black", "duel")
		logic.on_message(room, a, {"type": "use", "card": "duel", "target": [1, 0]})
		self.assertEqual(logic.at(1, 0)["o"], "b")
		dice = [e for e in room.events if e["type"] == "dice"][-1]
		self.assertEqual(dice["rolls"], {"black": 6, "white": 1})
		# (0,0) 1 + (1,0) 1 + (2,0) 업어서 2 = 4개 → 한 칸 더 두면 칸 4개로 다섯
		self.assertEqual(logic._weight([(0, 0), (1, 0), (2, 0)]), 4)
		self.assertIsNone(logic.winner)
		self.mv(logic, room, a, 3, 0)
		self.assertEqual(logic.winner, "black")

	def test_dice_roulette_oracle(self):
		logic, room, a, b = self.setup()
		room.peers = {"a": 1, "b": 1}
		logic.rng.randint = lambda lo, hi: 3
		pts = logic.points["black"]
		self.give(logic, "black", "dice")
		logic.on_message(room, a, {"type": "use", "card": "dice"})
		self.assertEqual(logic.points["black"], pts + 3)
		logic.used_card = False
		logic.rng.choices = lambda pop, weights=None: [0]  # 룰렛 첫 칸 +6P
		self.give(logic, "black", "roulette")
		logic.on_message(room, a, {"type": "use", "card": "roulette"})
		self.assertEqual(logic.points["black"], pts + 3 + 6)
		self.assertEqual(room.events[-2]["type"], "roulette")
		logic.used_card = False
		self.give(logic, "black", "oracle")
		logic.on_message(room, a, {"type": "use", "card": "oracle"})
		self.assertIsNotNone(logic.snapshot(room, "a")["hint"])
		self.assertIsNone(logic.snapshot(room, "b")["hint"])  # 상대는 못 봄
