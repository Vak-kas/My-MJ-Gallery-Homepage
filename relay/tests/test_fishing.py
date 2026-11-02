"""🎣 낚시 대결(mj_fishing) 로직 테스트.

실행: venv/bin/python -m unittest discover -s relay/tests -t .
시간은 mj_fishing.time.time 을 바꿔 치기해서 흐르게 함.
"""

import os
import random
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mj_fishing as F  # noqa: E402


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


class FishingTestCase(unittest.TestCase):
	def setUp(self):
		self.now = 1000.0
		patcher = mock.patch.object(F.time, "time", lambda: self.now)
		patcher.start()
		self.addCleanup(patcher.stop)

	def setup(self, skills=True, bot=False, duration=60, mode="total"):
		logic, room = F.FishingLogic(rng=random.Random(1)), _Room()
		a, b = _Peer("a", "가"), _Peer("b", "나")
		room.peers = {"a": a, "b": b} if not bot else {"a": a}
		logic.on_message(room, a, {"type": "sit", "seat": "p1"})
		if bot:
			logic.on_message(room, a, {"type": "add-bot"})
		else:
			logic.on_message(room, b, {"type": "sit", "seat": "p2"})
		logic.on_message(room, a, {"type": "options", "skills": skills, "duration": duration, "mode": mode})
		logic.on_message(room, a, {"type": "start"})
		return logic, room, a, b

	def advance(self, logic, room, seconds, step=0.25):
		"""시간을 흘리며 틱."""
		end = self.now + seconds
		while self.now < end - 1e-9:
			self.now = min(end, self.now + step)
			logic.tick(room, self.now)

	def hook(self, logic, room, peer, seat, spot="deep"):
		"""던지고 입질까지 기다렸다가 챔질 → 당기는 상태로."""
		ok, err = logic.on_message(room, peer, {"type": "cast", "spot": spot})
		self.assertTrue(ok, err)
		self.advance(logic, room, logic.bite_at[seat] - self.now + 0.01)
		self.assertEqual(logic.state[seat], "bite")
		self.assertTrue(logic.on_message(room, peer, {"type": "strike"})[0])
		self.assertEqual(logic.state[seat], "reeling")

	def test_cast_bite_strike_and_catch(self):
		logic, room, a, b = self.setup()
		self.assertEqual(logic.status, "playing")
		self.assertIn("자리를 골라", logic.on_message(room, a, {"type": "cast", "spot": "lake"})[1])
		self.hook(logic, room, a, "p1")
		self.assertEqual(len(room.events("bite", to="a")), 1)   # 입질은 당사자에게만
		self.assertEqual(room.events("hooked")[0]["seat"], "p1")
		self.assertFalse(logic.on_message(room, a, {"type": "cast", "spot": "deep"})[0])  # 이미 던져 둠
		fish = logic.fish["p1"]
		# 긴장이 내려가게 천천히 당기기
		for _ in range(fish["stamina"] + 1):
			if logic.state["p1"] != "reeling":
				break
			self.now += 0.5
			logic.on_message(room, a, {"type": "pull"})
		self.assertEqual(logic.state["p1"], "idle")
		catch = room.events("catch")[0]
		self.assertEqual(catch["fish"]["id"], fish["id"])
		if fish["id"] in F.JUNK:
			self.assertEqual(logic.basket["p1"], [])
		else:
			self.assertEqual(logic.total("p1"), fish["kg"])

	def test_too_early_too_late_and_snap(self):
		logic, room, a, b = self.setup()
		logic.on_message(room, a, {"type": "cast", "spot": "shallow"})
		logic.on_message(room, a, {"type": "strike"})
		self.assertEqual(room.events("escape")[-1]["why"], "early")
		self.assertEqual(logic.state["p1"], "idle")
		# 늦게
		logic.on_message(room, a, {"type": "cast", "spot": "shallow"})
		self.advance(logic, room, logic.bite_at["p1"] - self.now + 0.01)
		self.advance(logic, room, logic.fish["p1"]["window"] + 0.3)
		self.assertEqual(room.events("escape")[-1]["why"], "late")
		# 연타하면 줄이 끊어짐
		self.hook(logic, room, a, "p1")
		for _ in range(10):
			if logic.state["p1"] != "reeling":
				break
			self.now += F.PULL_GAP + 0.001
			logic.on_message(room, a, {"type": "pull"})
		self.assertEqual(room.events("escape")[-1]["why"], "snap")
		self.assertEqual(logic.basket["p1"], [])
		# 너무 빠른 연타는 무시
		self.hook(logic, room, a, "p1")
		self.now += 0.01
		logic.on_message(room, a, {"type": "pull"})
		p = logic.reel["p1"]["progress"]
		logic.on_message(room, a, {"type": "pull"})
		self.assertEqual(logic.reel["p1"]["progress"], p)

	def test_surge_raises_tension_but_never_snaps_alone(self):
		logic, room, a, b = self.setup()
		self.hook(logic, room, a, "p1")
		r = logic.reel["p1"]
		r["tension"] = 0.9
		self.advance(logic, room, r["surge_at"] - self.now + 0.01)
		self.assertEqual(logic.state["p1"], "reeling")
		self.assertLessEqual(logic.reel["p1"]["tension"], 0.97)
		self.assertTrue(any(e.get("surge_hit") for e in room.events("reel", to="a")))

	def test_glove_bait_shield_rock_fake(self):
		logic, room, a, b = self.setup()
		# 장갑: 연타해도 안 끊어짐
		logic.on_message(room, a, {"type": "skill", "id": "glove"})
		self.hook(logic, room, a, "p1")
		while logic.state["p1"] == "reeling":
			self.now += F.PULL_GAP + 0.001
			logic.on_message(room, a, {"type": "pull"})
		self.assertEqual(room.events("catch")[-1]["seat"], "p1")
		self.assertFalse(logic.glove["p1"])
		self.assertIn("이미 쓴", logic.on_message(room, a, {"type": "skill", "id": "glove"})[1])
		# 특제 미끼: 입질이 빨리 오고 큰 종류
		logic.on_message(room, a, {"type": "skill", "id": "bait"})
		logic.on_message(room, a, {"type": "cast", "spot": "shallow"})
		self.assertLessEqual(logic.bite_at["p1"] - self.now, 2.0)
		self.advance(logic, room, logic.bite_at["p1"] - self.now + 0.01)
		self.assertIn(logic.fish["p1"]["id"], {"crucian", "trout", "carp"})
		self.assertFalse(logic.bait["p1"])
		logic.on_message(room, a, {"type": "reel-in"})
		self.assertEqual(logic.state["p1"], "idle")
		# 돌: 기다리는 상대의 물고기가 도망가고 입질이 늦어짐 / 방패는 막음
		logic.on_message(room, b, {"type": "cast", "spot": "deep"})
		before = logic.bite_at["p2"]
		logic.on_message(room, a, {"type": "skill", "id": "rock"})
		self.assertEqual(logic.state["p2"], "waiting")
		self.assertGreater(logic.bite_at["p2"], before)
		self.assertEqual(room.events("escape", to="b")[-1]["why"], "rock")
		logic.on_message(room, b, {"type": "skill", "id": "shield"})
		logic.on_message(room, a, {"type": "skill", "id": "fake"})
		self.assertTrue(room.events("skill")[-1]["blocked"])
		self.assertEqual(logic.fakes["p2"], [])
		self.assertFalse(logic.shield["p2"])
		# 가짜 입질에 속으면 도망
		logic2, room2, a2, b2 = self.setup()
		logic2.on_message(room2, b2, {"type": "cast", "spot": "deep"})
		logic2.on_message(room2, a2, {"type": "skill", "id": "fake"})
		self.assertTrue(room2.events("skill")[-1]["secret"])
		logic2.bite_at["p2"] = self.now + 100   # 진짜 입질은 멀리
		self.advance(logic2, room2, logic2.fakes["p2"][0] - self.now + 0.01)
		self.assertEqual(len(room2.events("bite", to="b")), 1)
		self.assertEqual(logic2.state["p2"], "waiting")
		logic2.on_message(room2, b2, {"type": "strike"})
		self.assertEqual(room2.events("escape")[-1]["why"], "fake")

	def test_skills_off_and_opponent_sees_no_secrets(self):
		logic, room, a, b = self.setup(skills=False)
		self.assertIn("스킬 없이", logic.on_message(room, a, {"type": "skill", "id": "rock"})[1])
		self.hook(logic, room, a, "p1")
		snap = logic.snapshot(room, "b")
		self.assertNotIn("tension", snap["players"]["p1"]["reel"])
		self.assertNotIn("shield", snap["players"]["p1"])
		self.assertIn("tension", logic.snapshot(room, "a")["players"]["p1"]["reel"])

	def test_time_up_overtime_and_winner(self):
		logic, room, a, b = self.setup(duration=60)
		self.hook(logic, room, a, "p1")
		self.advance(logic, room, 61)
		self.assertEqual(logic.status, "playing")   # 당기는 중이라 기다려 줌
		self.assertFalse(logic.on_message(room, b, {"type": "cast", "spot": "deep"})[0])
		self.assertTrue(logic.snapshot(room, "a")["overtime"])
		self.advance(logic, room, F.OVERTIME)
		self.assertEqual(logic.status, "over")
		self.assertIsNone(logic.winner)   # 둘 다 0kg → 무승부
		# 다시 하기: 무게 많은 쪽 승리
		logic.on_message(room, a, {"type": "rematch"})
		logic.basket["p1"].append({"id": "carp", "emoji": "🎏", "name": "잉어", "kg": 3.5})
		logic.basket["p2"].append({"id": "sturgeon", "emoji": "🐉", "name": "철갑상어", "kg": 20.0})
		self.advance(logic, room, 61)
		self.assertEqual(logic.winner, "p2")
		self.assertEqual(logic.wins["p2"], 1)
		self.assertIn("20kg", logic.reason)

	def test_biggest_mode_and_resign(self):
		logic, room, a, b = self.setup(mode="biggest")
		logic.basket["p1"] += [{"id": "carp", "emoji": "🎏", "name": "잉어", "kg": 3.0}, {"id": "carp", "emoji": "🎏", "name": "잉어", "kg": 3.0}]
		logic.basket["p2"].append({"id": "carp", "emoji": "🎏", "name": "잉어", "kg": 4.0})
		self.advance(logic, room, 61)
		self.assertEqual(logic.winner, "p2")
		logic.on_message(room, a, {"type": "rematch"})
		logic.on_message(room, b, {"type": "resign"})
		self.assertEqual(logic.winner, "p1")

	def test_bots_finish_a_game(self):
		for level in F.BOT_LEVELS:
			logic, room, a, _ = self.setup(bot=True, duration=60)
			logic.on_message(room, a, {"type": "options", "bot_level": level, "duration": 60})
			logic.on_message(room, a, {"type": "start"})
			self.advance(logic, room, 60 + F.OVERTIME + 1)
			self.assertEqual(logic.status, "over", level)
			self.assertTrue(room.events("cast"), level)
			if level != "easy":
				self.assertTrue(logic.basket["p2"], level)
			self.assertFalse(room.events("bite", to="bot:p2"))   # 컴퓨터에겐 안 보냄


if __name__ == "__main__":
	unittest.main()
