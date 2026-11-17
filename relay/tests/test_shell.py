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

	def place(self, logic, room, dealer, cup):
		"""구슬을 놓고, 자리를 보여 주는 시간이 지나 섞기가 시작될 때까지."""
		ok, err = logic.on_message(room, dealer, {"type": "place", "cup": cup})
		self.assertTrue(ok, err)
		self.assertEqual(logic.phase, "show")
		self.advance(logic, room, M.SHOW_TIME + 0.1)
		self.assertEqual(logic.phase, "shuffle")

	def shuffle(self, logic, room, dealer, swaps):
		for a, b in swaps:
			ok, err = logic.on_message(room, dealer, {"type": "swap", "a": a, "b": b})
			self.assertTrue(ok, err)

	def test_round_flow_and_scoring(self):
		logic, room, a, b = self.setup()
		self.assertEqual((logic.round, logic.dealer, logic.phase), (1, "p1", "place"))
		self.assertIn("지금은", logic.on_message(room, b, {"type": "place", "cup": 0})[1])   # 맞히는 사람은 못 놓음
		self.assertTrue(logic.on_message(room, a, {"type": "place", "cup": 1})[0])
		# 처음 자리는 모두에게 보여 줌 — 그동안은 못 섞음
		self.assertEqual(logic.phase, "show")
		self.assertEqual(room.events("placed")[0]["cup"], 1)
		self.assertEqual(logic.snapshot(room, "b")["ball"], 1)
		self.assertIn("섞을 때가 아니", logic.on_message(room, a, {"type": "swap", "a": 0, "b": 1})[1])
		self.advance(logic, room, M.SHOW_TIME + 0.1)
		self.assertEqual(logic.phase, "shuffle")
		self.assertIsNone(logic.snapshot(room, "b")["ball"])   # 섞기부터는 다시 비밀
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
		self.place(logic, room, b, 0)
		self.shuffle(logic, room, b, [(0, 1), (1, 2), (0, 1)])   # 0 → 1 → 2 → 2
		logic.on_message(room, b, {"type": "done"})
		logic.on_message(room, a, {"type": "pick", "cup": 0})
		self.assertEqual(logic.score, {"p1": 0, "p2": 3})

	def test_swap_speeds_cost_power_and_timeouts(self):
		logic, room, a, b = self.setup()
		self.advance(logic, room, M.PLACE_TIME + 0.1)           # 안 놓으면 서버가 놓음
		self.assertEqual(logic.phase, "show")
		self.advance(logic, room, M.SHOW_TIME + 0.1)
		self.assertEqual(logic.phase, "shuffle")
		self.assertIsNotNone(logic.ball)
		self.assertTrue(logic.on_message(room, a, {"type": "swap", "a": 0, "b": 1, "speed": 1})[0])
		self.assertEqual(logic.power, M.POWER - 2)
		self.assertEqual(room.events("swap")[-1]["speed"], 1)
		self.assertTrue(logic.on_message(room, a, {"type": "swap", "a": 0, "b": 1, "speed": 2})[0])   # 번개
		self.assertEqual(logic.power, M.POWER - 5)
		self.assertTrue(logic.on_message(room, a, {"type": "swap", "a": 0, "b": 1, "speed": 9})[0])   # 모르는 값은 보통
		self.assertEqual((logic.power, logic.swaps[-1][2]), (M.POWER - 6, 0))
		logic.power = 2
		self.assertIn("힘이 모자라요", logic.on_message(room, a, {"type": "swap", "a": 0, "b": 1, "speed": 2})[1])
		self.advance(logic, room, M.SHUFFLE_TIME + 0.1)         # 시간 끝 → 모자란 섞기는 서버가 채우고 고르기로
		self.assertEqual(logic.phase, "guess")
		self.assertGreaterEqual(len(logic.swaps), M.MIN_SWAPS)
		self.advance(logic, room, M.GUESS_TIME + 0.1)           # 안 고르면 사기꾼 득점
		self.assertEqual((logic.phase, logic.score["p1"]), ("reveal", 1))

	def test_more_shuffling_and_guess_waits_for_animation(self):
		logic, room, a, b = self.setup()
		self.place(logic, room, a, 0)
		self.assertEqual(logic.snapshot(room, "a")["power_max"], 20)
		for i in range(20):                                     # 힘 20 → 보통 섞기 20번
			self.assertTrue(logic.on_message(room, a, {"type": "swap", "a": i % 3, "b": (i + 1) % 3})[0])
		self.assertEqual(logic.power, 0)
		self.assertIn("힘이 모자라요", logic.on_message(room, a, {"type": "swap", "a": 0, "b": 1})[1])
		# 한꺼번에 보낸 섞기는 화면에서 20 × 0.6초 걸림 → 고르는 시간은 그 뒤부터 셈
		logic.on_message(room, a, {"type": "done"})
		self.assertAlmostEqual(logic.phase_until - self.now, 20 * M.SWAP_LEN[0] + M.GUESS_TIME, places=3)

	def test_skills(self):
		logic, room, a, b = self.setup()
		self.assertIn("섞는 동안", logic.on_message(room, a, {"type": "skill", "id": "smoke"})[1])
		self.assertIn("사기꾼일 때", logic.on_message(room, b, {"type": "skill", "id": "smoke"})[1])
		self.assertIn("섞는 동안", logic.on_message(room, a, {"type": "skill", "id": "teleport", "cup": 1})[1])
		self.place(logic, room, a, 0)
		# 가속
		logic.on_message(room, a, {"type": "skill", "id": "turbo"})
		self.assertEqual(logic.power, M.POWER + 8)
		# 연막: 맞히는 사람에겐 컵 번호가 가려짐
		logic.on_message(room, a, {"type": "skill", "id": "smoke"})
		self.assertTrue(room.events("skill")[-1]["secret"])
		logic.on_message(room, a, {"type": "swap", "a": 0, "b": 1})
		self.assertEqual(room.events("swap", to="b")[-1]["a"], None)
		self.assertEqual(room.events("swap", to="a")[-1]["a"], 0)
		self.assertEqual(logic.swaps[-1][3], True)
		self.assertFalse(logic.smoke_armed)
		# 텔레포트: 구슬이 없는 아무 컵으로 — 상대에겐 썼다는 것만
		self.assertIn("다른 컵", logic.on_message(room, a, {"type": "skill", "id": "teleport", "cup": 1})[1])  # 구슬은 1 에 있음 → 1 은 자기 자리
		self.assertIn("다른 컵", logic.on_message(room, a, {"type": "skill", "id": "teleport", "cup": 3})[1])
		before = len(room.sent)
		self.assertTrue(logic.on_message(room, a, {"type": "skill", "id": "teleport", "cup": 2})[0])
		self.assertEqual(logic.ball, 2)
		self.assertEqual(room.events("ball", to="a")[-1]["cup"], 2)
		self.assertFalse([d for d, to, _ in room.sent[before:] if to != "a" and "cup" in d])   # 어디로 갔는지는 사기꾼만
		self.assertFalse(room.events("skill")[-1]["secret"])
		self.assertIsNone(logic.snapshot(room, "b")["ball"])
		self.assertIn("이미 쓴", logic.on_message(room, a, {"type": "skill", "id": "teleport", "cup": 1})[1])
		self.assertIn("모르는", logic.on_message(room, a, {"type": "skill", "id": "palm", "cup": 1})[1])   # 손바닥은 없어짐
		# 회오리: 힘을 안 쓰고 번개 속도로 3번
		power, n = logic.power, len(logic.swaps)
		self.assertTrue(logic.on_message(room, a, {"type": "skill", "id": "whirl"})[0])
		self.assertEqual((logic.power, len(logic.swaps) - n), (power, 3))
		self.assertTrue(all(sw[2] == 2 for sw in logic.swaps[n:]))
		ball = logic.swaps and logic.ball
		self.assertEqual(logic.snapshot(room, "a")["ball"], ball)
		# 맞히는 사람 스킬은 고를 때만
		self.assertIn("고를 차례", logic.on_message(room, b, {"type": "skill", "id": "lens"})[1])
		logic.on_message(room, b, {"type": "skill", "id": "double"})   # 섞는 동안도 됨
		self.assertTrue(logic.double)
		logic.on_message(room, a, {"type": "done"})
		logic.on_message(room, b, {"type": "skill", "id": "lens"})
		self.assertNotEqual(logic.lens, logic.ball)
		rest = [c for c in range(3) if c != logic.lens]
		self.assertEqual(room.events("lens", to="b")[0]["cup"], logic.lens)
		logic.on_message(room, b, {"type": "skill", "id": "rewind"})
		self.assertEqual(len(room.events("rewind", to="b")[0]["swaps"]), 3)
		self.assertIn("두 개까지", logic.on_message(room, b, {"type": "pick", "cups": [0, 1, 2]})[1])
		self.assertTrue(logic.on_message(room, b, {"type": "pick", "cups": rest})[0])
		self.assertEqual(logic.result["hit"], True)
		self.assertEqual(logic.result["points"], 1)   # 두 개 고르기는 판돈과 상관없이 +1

	def test_shield_blocks_hostile_skill(self):
		logic, room, a, b = self.setup()
		self.place(logic, room, a, 0)
		logic.on_message(room, b, {"type": "skill", "id": "shield"})
		self.assertTrue(logic.shield["p2"])
		logic.on_message(room, a, {"type": "skill", "id": "teleport", "cup": 1})
		self.assertTrue(room.events("skill")[-1]["blocked"])
		self.assertEqual(logic.ball, 0)
		self.assertFalse(logic.shield["p2"])
		self.assertIn("teleport", logic.used["p1"])

	def test_skills_off_game_end_and_draw(self):
		logic, room, a, b = self.setup(skills=False, rounds=4)
		self.assertIn("스킬 없이", logic.on_message(room, a, {"type": "skill", "id": "turbo"})[1])
		for _ in range(4 * 60):   # 아무도 안 하면 라운드마다 시간 초과로 넘어감
			if logic.status == "over":
				break
			self.advance(logic, room, 1)
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
				while logic.phase != "reveal" and t < 90:
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
