"""🫥 숨바꼭질(mj_hideseek) 로직 테스트.

실행: venv/bin/python -m unittest discover -s relay/tests -t .
"""

import math
import os
import random
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mj_hideseek as M  # noqa: E402


class _Peer:
	def __init__(self, pid, name):
		self.pid, self.name = pid, name


class _Room:
	def __init__(self):
		self.notices, self.sent = [], []

	def notice(self, text):
		self.notices.append(text)

	def emit(self, data, to=None, exclude=None):
		self.sent.append((data, to, exclude))

	def events(self, kind, to=None):
		return [d for d, t, _ in self.sent if d.get("type") == kind and (to is None or t == to)]


class HideSeekTestCase(unittest.TestCase):
	def setUp(self):
		self.now = 1000.0
		patcher = mock.patch.object(M.time, "time", lambda: self.now)
		patcher.start()
		self.addCleanup(patcher.stop)
		self.logic, self.room = M.HideSeekLogic(rng=random.Random(1)), _Room()
		self.a, self.b, self.c = _Peer("a", "가"), _Peer("b", "나"), _Peer("c", "다")
		for p in (self.a, self.b, self.c):
			self.logic.on_join(self.room, p)

	def send(self, peer, **data):
		return self.logic.on_message(self.room, peer, data)

	def start(self):
		self.assertEqual(self.send(self.a, type="start"), (True, None))
		self.seeker = next(p for p in (self.a, self.b, self.c) if self.logic.players[p.pid]["role"] == "seeker")
		self.hiders = [p for p in (self.a, self.b, self.c) if p is not self.seeker]

	def to_seek(self):
		self.now += self.logic.hide_time + 0.1
		self.assertTrue(self.logic.tick(self.room, self.now))
		self.assertEqual(self.logic.status, "seek")

	def place(self, peer, x, z, ry=0.0):
		p = self.logic.players[peer.pid]
		p.update(x=x, z=z, ry=ry)

	def aim_at(self, x, z):
		"""술래를 (x, z) 를 바라보게 2 m 앞에 세움."""
		sx, sz = x, z + 2.0   # 과녁보다 +z 쪽 → −z 방향(ry=0) 을 봄
		self.place(self.seeker, sx, sz, 0.0)


class JoinAndStartTests(HideSeekTestCase):
	def test_join_sends_map_and_first_is_host(self):
		self.assertEqual(self.logic.host, "a")
		maps = self.room.events("map", to="a")
		self.assertTrue(maps and maps[0]["map"]["props"])
		self.assertIn("box", maps[0]["props"])

	def test_only_host_starts_and_needs_two(self):
		self.assertEqual(self.send(self.b, type="start")[1], "방장만 시작할 수 있어요.")
		solo = M.HideSeekLogic()
		room = _Room()
		solo.on_join(room, self.a)
		self.assertEqual(solo.on_message(room, self.a, {"type": "start"})[1], "2명 이상이어야 해요.")

	def test_roles_and_seeker_rotates(self):
		self.start()
		roles = sorted(p["role"] for p in self.logic.players.values())
		self.assertEqual(roles, ["hider", "hider", "seeker"])
		first = self.seeker.pid
		self.logic._finish(self.room, "seeker", "끝")
		self.start()
		self.assertNotEqual(self.seeker.pid, first)

	def test_hider_ids_are_opaque(self):
		self.start()
		for h in self.hiders:
			eid = self.logic.players[h.pid]["eid"]
			self.assertTrue(eid.startswith("e"))
			self.assertNotEqual(h.pid, eid)
			self.assertEqual(len(eid), 7)

	def test_settings_only_from_choices(self):
		self.send(self.a, type="settings", hide=45, seek=999)
		self.assertEqual((self.logic.hide_time, self.logic.seek_time), (45, 180))


class MoveTests(HideSeekTestCase):
	def test_seeker_frozen_while_hiding(self):
		self.start()
		before = (self.logic.players[self.seeker.pid]["x"], self.logic.players[self.seeker.pid]["z"])
		self.send(self.seeker, type="pos", x=1, z=1, ry=0)
		self.assertEqual(before, (self.logic.players[self.seeker.pid]["x"], self.logic.players[self.seeker.pid]["z"]))

	def test_pos_is_broadcast_with_opaque_id_and_speed_limited(self):
		self.start()
		h = self.hiders[0]
		p = self.logic.players[h.pid]
		x0, z0 = p["x"], p["z"]
		self.now += 0.1
		self.send(h, type="pos", x=x0 + 50, z=z0, ry=0.5)   # 순간 이동 시도
		self.assertLess(abs(p["x"] - x0), 2.0)
		pos = self.room.events("pos")[-1]
		self.assertEqual(pos["id"], p["eid"])
		self.assertTrue(self.room.events("fix", to=h.pid))

	def test_pos_clamped_to_house_and_rejects_nan(self):
		self.start()
		h = self.hiders[0]
		p = self.logic.players[h.pid]
		self.place(h, 0.5, 0.5)
		self.now += 1
		self.send(h, type="pos", x=-3, z=-3, ry=0)
		self.assertGreaterEqual(p["x"], 0.2)
		self.now += 1
		self.send(h, type="pos", x="nan", z=1, ry=0)
		self.assertTrue(math.isfinite(p["x"]))


class DisguiseTests(HideSeekTestCase):
	def test_copy_prop_needs_to_be_near(self):
		self.start()
		h = self.hiders[0]
		prop = M.MAP["props"][0]
		self.place(h, prop["x"] + 10, prop["z"])
		self.assertEqual(self.send(h, type="disguise", prop=prop["type"], **{"from": prop["id"]})[1], "너무 멀어요 — 가까이 가서 변신하세요.")
		self.place(h, prop["x"] + 1, prop["z"])
		self.send(h, type="disguise", prop=prop["type"], **{"from": prop["id"]})
		self.assertEqual(self.logic.players[h.pid]["prop"], prop["type"])
		self.assertEqual(self.room.events("disguise")[-1]["id"], self.logic.players[h.pid]["eid"])

	def test_seeker_cannot_disguise_and_unknown_prop(self):
		self.start()
		self.assertEqual(self.send(self.seeker, type="disguise", prop="box"), (False, None))
		self.assertEqual(self.send(self.hiders[0], type="disguise", prop="rocket")[1], "모르는 물건이에요.")


class ShootTests(HideSeekTestCase):
	def test_no_shooting_while_hiding(self):
		self.start()
		h = self.logic.players[self.hiders[0].pid]
		self.send(self.seeker, type="shoot", target=h["eid"])
		self.assertEqual(h["hp"], M.HIDER_HP)

	def test_two_hits_catch_and_all_caught_seeker_wins(self):
		self.start()
		self.to_seek()
		for h in self.hiders:
			p = self.logic.players[h.pid]
			self.aim_at(p["x"], p["z"])
			for _ in range(2):
				self.now += M.SHOOT_COOLDOWN + 0.01
				self.send(self.seeker, type="shoot", target=p["eid"])
			self.assertFalse(p["alive"])
		self.assertEqual(self.logic.status, "over")
		self.assertEqual(self.logic.result["winner"], "seeker")

	def test_cooldown(self):
		self.start()
		self.to_seek()
		p = self.logic.players[self.hiders[0].pid]
		self.aim_at(p["x"], p["z"])
		self.now += 1
		self.send(self.seeker, type="shoot", target=p["eid"])
		self.send(self.seeker, type="shoot", target=p["eid"])   # 바로 또 → 무시
		self.assertEqual(p["hp"], M.HIDER_HP - M.HIT_DAMAGE)

	def test_must_face_and_be_in_range(self):
		self.start()
		self.to_seek()
		p = self.logic.players[self.hiders[0].pid]
		self.aim_at(p["x"], p["z"])
		self.logic.players[self.seeker.pid]["ry"] = math.pi   # 뒤돌아 봄
		self.now += 1
		self.send(self.seeker, type="shoot", target=p["eid"])
		self.assertEqual(p["hp"], M.HIDER_HP)
		self.place(self.seeker, p["x"], p["z"] + M.SHOOT_RANGE + 3, 0.0)   # 너무 멂
		self.now += 1
		self.send(self.seeker, type="shoot", target=p["eid"])
		self.assertEqual(p["hp"], M.HIDER_HP)

	def test_shooting_real_prop_costs_seeker_hp_until_hiders_win(self):
		self.start()
		self.to_seek()
		prop = M.MAP["props"][0]
		s = self.logic.players[self.seeker.pid]
		for _ in range(math.ceil(M.SEEKER_HP / M.MISS_PENALTY)):
			self.aim_at(prop["x"], prop["z"])
			self.now += M.SHOOT_COOLDOWN + 0.01
			self.send(self.seeker, type="shoot", target=prop["id"])
		self.assertEqual(s["hp"], 0)
		self.assertEqual(self.logic.result["winner"], "hiders")

	def test_hider_cannot_shoot(self):
		self.start()
		self.to_seek()
		self.assertEqual(self.send(self.hiders[0], type="shoot", target="p0"), (False, None))


class TimeAndLeaveTests(HideSeekTestCase):
	def test_time_up_hiders_win_and_taunts(self):
		self.start()
		self.to_seek()
		self.now += M.TAUNT_EVERY + 0.1
		self.logic.tick(self.room, self.now)
		self.assertEqual(len(self.room.events("taunt")[-1]["pts"]), 2)
		self.now += self.logic.seek_time
		self.assertTrue(self.logic.tick(self.room, self.now))
		self.assertEqual(self.logic.result["winner"], "hiders")

	def test_seeker_leaving_ends_round(self):
		self.start()
		self.logic.on_leave(self.room, self.seeker.pid)
		self.assertEqual(self.logic.result["winner"], "hiders")

	def test_host_moves_on_leave(self):
		self.logic.on_leave(self.room, "a")
		self.assertEqual(self.logic.host, "b")


class SnapshotTests(HideSeekTestCase):
	def test_seeker_sees_no_names_hiders_do(self):
		self.start()
		self.to_seek()
		s = self.logic.snapshot(self.room, self.seeker.pid)
		self.assertTrue(s["ents"])
		self.assertTrue(all("name" not in e for e in s["ents"]))
		h = self.logic.snapshot(self.room, self.hiders[0].pid)
		self.assertTrue(all("name" in e for e in h["ents"]))
		self.assertEqual(h["me"]["role"], "hider")

	def test_ninth_person_is_spectator(self):
		for i in range(10):
			self.logic.on_join(self.room, _Peer(f"x{i}", f"손{i}"))
		self.assertEqual(len(self.logic.players), M.MAX_PLAYERS)
		self.assertEqual(self.logic.on_message(self.room, _Peer("x9", "손9"), {"type": "start"})[1], "구경 중이에요 (최대 8명).")


class MapTests(unittest.TestCase):
	def test_props_inside_house_and_known(self):
		m = M.MAP
		for p in m["props"]:
			self.assertIn(p["type"], M.PROPS)
			self.assertTrue(0 < p["x"] < m["w"] and 0 < p["z"] < m["d"], p)
		for x, z in m["hider_spawns"] + [m["seeker_spawn"]]:
			self.assertTrue(0 < x < m["w"] and 0 < z < m["d"])

	def test_spawns_not_inside_props(self):
		m = M.MAP
		for x, z in m["hider_spawns"] + [m["seeker_spawn"]]:
			for p in m["props"]:
				_, w, _, d = M.PROPS[p["type"]]
				self.assertGreater(math.hypot(x - p["x"], z - p["z"]), min(w, d) / 2 + 0.3, (x, z, p))


if __name__ == "__main__":
	unittest.main()
