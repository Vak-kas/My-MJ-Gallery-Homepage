"""🥤 야바위(mj_shell) 로직 테스트.

실행: venv/bin/python -m unittest discover -s relay/tests -t .
"""

import os
import random
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mj_shell as M  # noqa: E402


class _Peer:
	def __init__(self, pid, name):
		self.pid, self.name = pid, name


class _Room:
	def __init__(self):
		self.peers = {}
		self.notices, self.sent = [], []

	def notice(self, text):
		self.notices.append(text)

	def emit(self, data, to=None, exclude=None):
		self.sent.append((data, to, exclude))

	def events(self, kind, to=None):
		return [d for d, t, _ in self.sent if d.get("type") == kind and (to is None or t == to)]


class ShellTestCase(unittest.TestCase):
	def setUp(self):
		self.now = 1000.0
		patcher = mock.patch.object(M.time, "time", lambda: self.now)
		patcher.start()
		self.addCleanup(patcher.stop)

	def setup(self, skills=True, bot=False, cups=3, rounds=4):
		logic, room = M.ShellLogic(rng=random.Random(2)), _Room()
		a, b = _Peer("a", "가"), _Peer("b", "나")
		room.peers = {"a": a, "b": b} if not bot else {"a": a}
		logic.on_message(room, a, {"type": "sit", "seat": "p1"})
		if bot:
			logic.on_message(room, a, {"type": "add-bot"})
		else:
			logic.on_message(room, b, {"type": "sit", "seat": "p2"})
		logic.on_message(room, a, {"type": "options", "skills": skills, "cups": cups, "rounds": rounds})
		logic.on_message(room, a, {"type": "start"})
		return logic, room, a, b

	def advance(self, logic, room, seconds, step=0.25):
		end = self.now + seconds
		while self.now < end - 1e-9:
			self.now = min(end, self.now + step)
			logic.tick(room, self.now)

	def shuffle(self, logic, room, dealer, swaps):
		for a, b in swaps:
			ok, err = logic.on_message(room, dealer, {"type": "swap", "a": a, "b": b})
			self.assertTrue(ok, err)

	def test_round_flow_and_scoring(self):
		logic, room, a, b = self.setup()
		self.assertEqual((logic.round, logic.dealer, logic.phase), (1, "p1", "place"))
		self.assertIn("지금은", logic.on_message(room, b, {"type": "place", "cup": 0})[1])   # 맞히는 사람은 못 놓음
		self.assertTrue(logic.on_message(room, a, {"type": "place", "cup": 1})[0])
		self.assertEqual(logic.phase, "shuffle")
		self.assertEqual(room.events("ball", to="a")[0]["cup"], 1)
		self.assertFalse(room.events("ball", to="b"))
		self.assertIn("적어도", logic.on_message(room, a, {"type": "done"})[1])
		self.shuffle(logic, room, a, [(0, 1), (1, 2), (0, 2)])   # 구슬 1 → 0 → 0 → 2
		self.assertEqual(logic.ball, 2)
		self.assertEqual(logic.power, M.POWER - 3)
		self.assertTrue(logic.on_message(room, b, {"type": "bet", "bet": 2})[0])
		self.assertTrue(logic.on_message(room, a, {"type": "done"})[0])
		self.assertEqual(logic.phase, "guess")
		self.assertIn("섞을 때가 아니", logic.on_message(room, a, {"type": "swap", "a": 0, "b": 1})[1])
		snap = logic.snapshot(room, "b")
		self.assertIsNone(snap["ball"])                       # 맞히는 사람에겐 비밀
		self.assertEqual(logic.snapshot(room, "a")["ball"], 2)
		self.assertTrue(logic.on_message(room, b, {"type": "pick", "cup": 2})[0])
		self.assertEqual((logic.phase, logic.score["p2"]), ("reveal", 2))
		self.assertEqual(room.events("reveal")[0]["hit"], True)
		self.advance(logic, room, M.REVEAL_TIME + 0.1)
		self.assertEqual((logic.round, logic.dealer, logic.phase), (2, "p2", "place"))
		# 2라운드: 틀리면 사기꾼 득점
		logic.on_message(room, b, {"type": "place", "cup": 0})
		self.shuffle(logic, room, b, [(0, 1), (1, 2), (0, 1)])   # 0 → 1 → 2 → 2
		logic.on_message(room, b, {"type": "done"})
		logic.on_message(room, a, {"type": "pick", "cup": 0})
		self.assertEqual(logic.score, {"p1": 0, "p2": 3})

	def test_fast_swap_costs_two_and_timeouts(self):
		logic, room, a, b = self.setup()
		self.advance(logic, room, M.PLACE_TIME + 0.1)           # 안 놓으면 서버가 놓음
		self.assertEqual(logic.phase, "shuffle")
		self.assertIsNotNone(logic.ball)
		self.assertTrue(logic.on_message(room, a, {"type": "swap", "a": 0, "b": 1, "fast": True})[0])
		self.assertEqual(logic.power, M.POWER - 2)
		self.assertTrue(room.events("swap")[-1]["fast"])
		logic.power = 1
		self.assertIn("힘이 모자라요", logic.on_message(room, a, {"type": "swap", "a": 0, "b": 1, "fast": True})[1])
		self.advance(logic, room, M.SHUFFLE_TIME + 0.1)         # 시간 끝 → 모자란 섞기는 서버가 채우고 고르기로
		self.assertEqual(logic.phase, "guess")
		self.assertGreaterEqual(len(logic.swaps), M.MIN_SWAPS)
		self.advance(logic, room, M.GUESS_TIME + 0.1)           # 안 고르면 사기꾼 득점
		self.assertEqual((logic.phase, logic.score["p1"]), ("reveal", 1))

	def test_skills(self):
		logic, room, a, b = self.setup()
		self.assertIn("섞는 동안", logic.on_message(room, a, {"type": "skill", "id": "smoke"})[1])
		self.assertIn("사기꾼일 때", logic.on_message(room, b, {"type": "skill", "id": "smoke"})[1])
		logic.on_message(room, a, {"type": "place", "cup": 0})
		# 가속
		logic.on_message(room, a, {"type": "skill", "id": "turbo"})
		self.assertEqual(logic.power, M.POWER + 4)
		# 연막: 맞히는 사람에겐 컵 번호가 가려짐
		logic.on_message(room, a, {"type": "skill", "id": "smoke"})
		self.assertTrue(room.events("skill")[-1]["secret"])
		logic.on_message(room, a, {"type": "swap", "a": 0, "b": 1})
		self.assertEqual(room.events("swap", to="b")[-1]["a"], None)
		self.assertEqual(room.events("swap", to="a")[-1]["a"], 0)
		self.assertEqual(logic.swaps[-1][3], True)
		self.assertFalse(logic.smoke_armed)
		# 손바닥: 옆 컵으로만
		self.assertIn("옆 컵", logic.on_message(room, a, {"type": "skill", "id": "palm", "cup": 1})[1])  # 구슬은 1 에 있음 → 1 은 자기 자리
		self.assertTrue(logic.on_message(room, a, {"type": "skill", "id": "palm", "cup": 2})[0])
		self.assertEqual(logic.ball, 2)
		self.assertIn("이미 쓴", logic.on_message(room, a, {"type": "skill", "id": "palm", "cup": 1})[1])
		logic.on_message(room, a, {"type": "swap", "a": 0, "b": 1})
		logic.on_message(room, a, {"type": "swap", "a": 0, "b": 1})
		# 맞히는 사람 스킬은 고를 때만
		self.assertIn("고를 차례", logic.on_message(room, b, {"type": "skill", "id": "lens"})[1])
		logic.on_message(room, b, {"type": "skill", "id": "double"})   # 섞는 동안도 됨
		self.assertTrue(logic.double)
		logic.on_message(room, a, {"type": "done"})
		logic.on_message(room, b, {"type": "skill", "id": "lens"})
		self.assertNotEqual(logic.lens, logic.ball)
		self.assertEqual(room.events("lens", to="b")[0]["cup"], logic.lens)
		logic.on_message(room, b, {"type": "skill", "id": "rewind"})
		self.assertEqual(len(room.events("rewind", to="b")[0]["swaps"]), 3)
		self.assertIn("두 개까지", logic.on_message(room, b, {"type": "pick", "cups": [0, 1, 2]})[1])
		self.assertTrue(logic.on_message(room, b, {"type": "pick", "cups": [2, logic.lens]})[0])
		self.assertEqual(logic.result["hit"], True)
		self.assertEqual(logic.result["points"], 1)   # 두 개 고르기는 판돈과 상관없이 +1

	def test_shield_blocks_hostile_skill(self):
		logic, room, a, b = self.setup()
		logic.on_message(room, a, {"type": "place", "cup": 0})
		logic.on_message(room, b, {"type": "skill", "id": "shield"})
		self.assertTrue(logic.shield["p2"])
		logic.on_message(room, a, {"type": "skill", "id": "palm", "cup": 1})
		self.assertTrue(room.events("skill")[-1]["blocked"])
		self.assertEqual(logic.ball, 0)
		self.assertFalse(logic.shield["p2"])
		self.assertIn("palm", logic.used["p1"])

	def test_skills_off_game_end_and_draw(self):
		logic, room, a, b = self.setup(skills=False, rounds=4)
		self.assertIn("스킬 없이", logic.on_message(room, a, {"type": "skill", "id": "turbo"})[1])
		for _ in range(4):
			self.advance(logic, room, M.PLACE_TIME + M.SHUFFLE_TIME + M.GUESS_TIME + M.REVEAL_TIME + 1)
		self.assertEqual(logic.status, "over")
		self.assertEqual(logic.score, {"p1": 2, "p2": 2})   # 아무도 안 골라 사기꾼이 번갈아 득점
		self.assertIsNone(logic.winner)
		self.assertIn("무승부", logic.reason)
		# 다시 하기: 1라운드 사기꾼이 바뀜
		logic.on_message(room, a, {"type": "rematch"})
		self.assertEqual(logic.dealer, "p2")
		logic.on_message(room, a, {"type": "resign"})
		self.assertEqual(logic.winner, "p2")

	def test_bots_play_both_roles(self):
		for level in M.BOT_LEVELS:
			logic, room, a, _ = self.setup(bot=True, rounds=4)
			logic.on_message(room, a, {"type": "options", "bot_level": level, "rounds": 4})
			logic.on_message(room, a, {"type": "start"})
			hits = 0
			for _ in range(4):
				# 사람 차례는 시간 초과로 넘기고 컴퓨터가 알아서 함
				t = 0
				while logic.phase != "reveal" and t < 60:
					self.advance(logic, room, 1)
					t += 1
				self.assertEqual(logic.phase, "reveal", level)
				hits += logic.result["hit"]
				self.advance(logic, room, M.REVEAL_TIME + 0.1)
			self.assertEqual(logic.status, "over", level)
			self.assertTrue(room.events("swap"), level)
			self.assertFalse(room.events("ball", to="bot:p2"))


if __name__ == "__main__":
	unittest.main()
