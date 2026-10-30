from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from .registry import CATEGORIES, GAMES


class GameHubTests(TestCase):
	def setUp(self):
		cache.clear()

	def tearDown(self):
		cache.clear()

	def test_hub_lists_ready_and_coming_games(self):
		res = self.client.get(reverse("games:index"))
		self.assertEqual(res.status_code, 200)
		for game in GAMES:
			self.assertContains(res, game["title"])
			if game["url_name"]:
				self.assertContains(res, reverse(game["url_name"]))
				self.assertEqual(self.client.get(reverse(game["url_name"])).status_code, 200, game["slug"])
		self.assertContains(res, "준비 중")
		self.assertEqual({g["category"] for g in GAMES} - {k for k, *_ in CATEGORIES}, set())

	def test_menu_and_meta(self):
		res = self.client.get("/")
		self.assertIn("Game", [i["label"] for i in res.context["site_nav"]])
		page = self.client.get(reverse("games:ladder"))
		self.assertContains(page, "<title>사다리타기 · Game")
		self.assertContains(page, "/og/game/ladder.png")
		self.assertIn("/games/roulette/", self.client.get("/sitemap.xml").content.decode())
		card = self.client.get("/og/game/ladder.png")
		self.assertEqual(card.status_code, 200)
		self.assertEqual(card["Content-Type"], "image/png")

	def test_hidden_menu_blocks_games(self):
		from studio import site_settings

		admin = get_user_model().objects.create_superuser("admin", "a@example.com", "pw-for-tests-only")
		self.client.force_login(admin)
		nav = ["home", "blog", "tool", "photo", "game"]
		self.client.post(reverse("studio:settings"), {"nav_order": nav, "nav_state_game": "admin",
													  "home_order": [s["key"] for s in site_settings.HOME_SECTION_DEFAULTS]})
		self.assertEqual(self.client.get(reverse("games:ladder")).status_code, 200)  # 관리자는 봄
		self.client.logout()
		self.assertEqual(self.client.get(reverse("games:index")).status_code, 404)
		self.assertNotIn("/games/", self.client.get("/sitemap.xml").content.decode())


class Engine2048Tests(TestCase):
	def test_merge_rules(self):
		from .engine2048 import Game

		g = Game(1)
		g.board = [2, 2, 2, 2, 4, 0, 4, 8, 0, 0, 0, 0, 2, 4, 8, 16]
		g.score = 0
		g.rnd = lambda: 0.0  # 새 타일은 첫 빈칸에 2
		self.assertTrue(g.move("L"))
		self.assertEqual(g.board[:8], [4, 4, 2, 0, 8, 8, 0, 0])  # 새 2 는 첫 빈칸(2번)에
		self.assertEqual(g.score, 16)
		self.assertEqual(g.board[12:], [2, 4, 8, 16])  # 못 움직인 줄은 그대로

	def test_replay_is_deterministic(self):
		from .engine2048 import replay

		moves = "LURD" * 60
		a, b = replay(12345, moves), replay(12345, moves)
		self.assertEqual((a.board, a.score), (b.board, b.score))
		self.assertNotEqual(replay(12346, moves).board, a.board)


class ScoreApiTests(TestCase):
	def setUp(self):
		cache.clear()
		self.u1 = get_user_model().objects.create_user("alice", "a@example.com", "pw-for-tests-only")
		self.u2 = get_user_model().objects.create_user("bob", "b@example.com", "pw-for-tests-only")

	def tearDown(self):
		cache.clear()

	def post(self, name, body=None):
		import json
		return self.client.post(reverse(f"games:{name}"), json.dumps(body or {}), content_type="application/json").json()

	def play2048(self, moves="LDRDLDRD" * 30):
		from .engine2048 import replay

		s = self.post("2048_start")
		expected = replay(s["seed"], moves)
		return s, expected, self.post("2048_submit", {"token": s["token"], "moves": moves})

	def test_2048_server_computes_score_and_token_is_single_use(self):
		s, expected, r = self.play2048()
		self.assertEqual(r["score"], expected.score)
		self.assertFalse(r["saved"])  # 비로그인은 저장 안 함
		self.assertTrue(r["login"])
		again = self.post("2048_submit", {"token": s["token"], "moves": "L"})
		self.assertFalse(again["ok"])
		bad = self.post("2048_submit", {"token": self.post("2048_start")["token"], "moves": "LX"})
		self.assertFalse(bad["ok"])

	def test_2048_leaderboard_best_per_user(self):
		from .models import Score

		self.client.force_login(self.u1)
		_, _, r = self.play2048()
		self.assertTrue(r["saved"] and r["best"])
		Score.objects.create(board="2048", user=self.u1, score=10)  # 더 낮은 기록
		Score.objects.create(board="2048", user=self.u2, score=999999)
		res = self.client.get(reverse("games:scores", args=["2048"])).json()
		self.assertEqual([row["name"] for row in res["rows"]], ["bob", "alice"])  # 사람마다 최고 기록 하나
		self.assertEqual(res["mine"]["rank"], 2)
		self.assertEqual(self.client.get(reverse("games:scores", args=["nope"])).status_code, 404)

	def test_typing_grading_uses_server_time(self):
		from unittest import mock

		from .typing import keystrokes

		self.client.force_login(self.u1)
		with mock.patch("games.scores.time.time", return_value=1000.0):
			s = self.post("typing_start", {"lang": "ko"})
		self.assertEqual(len(s["texts"]), 10)
		# 서버 기준 63초 (3초 카운트다운 빼면 60초) 동안 전부 맞게 침, 브라우저는 1초라고 거짓말
		with mock.patch("games.scores.time.time", return_value=1063.0):
			r = self.post("typing_submit", {"token": s["token"], "typed": s["texts"], "seconds": 1})
		self.assertEqual(r["accuracy"], 100.0)
		self.assertEqual(r["cpm"], round(sum(keystrokes(t) for t in s["texts"]) / (58 / 60)))  # 최대 2초만 깎아 줌
		self.assertTrue(r["saved"])

	def test_typing_low_accuracy_not_ranked(self):
		self.client.force_login(self.u1)
		s = self.post("typing_start", {"lang": "en"})
		r = self.post("typing_submit", {"token": s["token"], "typed": ["x"] * 10, "seconds": 30})
		self.assertFalse(r["saved"])
		self.assertEqual(r["reason"], "accuracy")
		self.assertFalse(self.post("typing_submit", {"token": s["token"], "typed": ["x"] * 10})["ok"])  # 한 번만

	def test_typing_inhuman_speed_not_ranked(self):
		from unittest import mock

		self.client.force_login(self.u1)
		with mock.patch("games.scores.time.time", return_value=1000.0):
			s = self.post("typing_start", {"lang": "ko"})
		with mock.patch("games.scores.time.time", return_value=1005.0):  # 2초 만에 10문장
			r = self.post("typing_submit", {"token": s["token"], "typed": s["texts"], "seconds": 2})
		self.assertGreater(r["cpm"], 1500)
		self.assertEqual((r["saved"], r["reason"]), (False, "speed"))


class OmokViewTests(TestCase):
	ROOM = {"id": "ab12cd34", "kind": "omok", "token": "tok-123", "title": "점심 내기", "owner_id": None, "owner": "alice", "public": True, "peers": 1, "status": "waiting", "seats_open": 1}

	def setUp(self):
		cache.clear()
		self.alice = get_user_model().objects.create_user("alice", "a@example.com", "pw-for-tests-only")
		self.room = {**self.ROOM, "owner_id": self.alice.id}

	def tearDown(self):
		cache.clear()

	def test_lobby_lists_public_rooms_with_link(self):
		from unittest import mock

		with mock.patch("tools.relay_client.list_games", return_value=[self.room, {**self.room, "id": "zz", "public": False}]):
			res = self.client.get(reverse("games:omok"))
		self.assertContains(res, "점심 내기")
		self.assertContains(res, "/games/omok/ab12cd34/?t=tok-123")
		self.assertNotContains(res, "/games/omok/zz/")  # 비공개 방은 안 보임

	def test_create_requires_login_and_limit(self):
		from unittest import mock

		self.assertEqual(self.client.post(reverse("games:omok_create")).status_code, 302)
		self.client.force_login(self.alice)
		with mock.patch("tools.relay_client.list_games", return_value=[]), \
				mock.patch("tools.relay_client.create_game", return_value=self.room) as create:
			res = self.client.post(reverse("games:omok_create"), {"title": "한 판", "public": "on"})
		self.assertRedirects(res, "/games/omok/ab12cd34/?t=tok-123", fetch_redirect_response=False)
		self.assertEqual(create.call_args.args[0]["owner"], "alice")
		self.assertTrue(create.call_args.args[0]["public"])
		with mock.patch("tools.relay_client.list_games", return_value=[self.room] * 3), \
				mock.patch("tools.relay_client.create_game") as create:
			self.client.post(reverse("games:omok_create"))
		create.assert_not_called()

	def test_room_needs_token_and_open_when_menu_members_only(self):
		from unittest import mock

		from studio import site_settings

		with mock.patch("tools.relay_client.get_game", return_value=self.room):
			self.assertEqual(self.client.get("/games/omok/ab12cd34/").status_code, 404)
			self.assertEqual(self.client.get("/games/omok/ab12cd34/?t=nope").status_code, 404)
			res = self.client.get("/games/omok/ab12cd34/?t=tok-123")
			self.assertContains(res, "/relay/ws/game/ab12cd34")  # JS 문자열이라 ?, = 는 이스케이프돼서 경로만 확인
			self.assertContains(res, 'name="robots" content="noindex')
			# Game 메뉴를 회원 전용으로 해도 초대 링크는 비로그인도 열림
			admin = get_user_model().objects.create_superuser("admin", "x@example.com", "pw-for-tests-only")
			self.client.force_login(admin)
			nav = ["home", "blog", "tool", "photo", "game"]
			self.client.post(reverse("studio:settings"), {"nav_order": nav, "nav_state_game": "members", "home_order": [s["key"] for s in site_settings.HOME_SECTION_DEFAULTS]})
			self.client.logout()
			self.assertEqual(self.client.get("/games/omok/ab12cd34/?t=tok-123").status_code, 200)
			self.assertEqual(self.client.get("/games/omok/").status_code, 302)

	def test_only_owner_closes(self):
		from unittest import mock

		bob = get_user_model().objects.create_user("bob", "b@example.com", "pw-for-tests-only")
		self.client.force_login(bob)
		with mock.patch("tools.relay_client.get_game", return_value=self.room), mock.patch("tools.relay_client.close_game") as close:
			self.client.post(reverse("games:omok_close", args=["ab12cd34"]))
			close.assert_not_called()
			self.client.force_login(self.alice)
			self.client.post(reverse("games:omok_close", args=["ab12cd34"]))
			close.assert_called_once_with("ab12cd34")


class CatchmindViewTests(TestCase):
	ROOM = {"id": "cm123456", "kind": "catchmind", "token": "tok-cm", "title": "금요일 그림", "owner_id": None, "owner": "alice", "public": True, "peers": 2, "status": "lobby", "seats_open": 0}

	def test_lobby_room_and_kind_check(self):
		from unittest import mock

		with mock.patch("tools.relay_client.list_games", return_value=[self.ROOM, {**OmokViewTests.ROOM}]):
			res = self.client.get(reverse("games:catchmind"))
		self.assertContains(res, "그림 맞추기.")
		self.assertContains(res, "/games/catchmind/cm123456/?t=tok-cm")
		self.assertNotContains(res, "/games/catchmind/ab12cd34/")  # 오목 방은 안 보임
		with mock.patch("tools.relay_client.get_game", return_value=self.ROOM):
			self.assertContains(self.client.get("/games/catchmind/cm123456/?t=tok-cm"), "/relay/ws/game/cm123456")
			self.assertEqual(self.client.get("/games/omok/cm123456/?t=tok-cm").status_code, 404)  # 종류가 다르면 404


class SoloPuzzleTests(TestCase):
	"""스도쿠·지뢰찾기·따라그리기: 서버가 판을 정하고 서버가 채점."""

	def setUp(self):
		cache.clear()
		self.user = get_user_model().objects.create_user("solo", "s@example.com", "pw-for-tests-only")

	def tearDown(self):
		cache.clear()

	def post(self, name, body):
		import json
		return self.client.post(reverse(f"games:{name}"), json.dumps(body), content_type="application/json").json()

	def test_sudoku_puzzles_have_one_answer(self):
		from . import sudoku

		for level, (_, target) in sudoku.LEVELS.items():
			puzzle, solution = sudoku.generate(level)
			self.assertEqual(sudoku.count_solutions([int(c) for c in puzzle]), 1)
			self.assertLessEqual(81 - puzzle.count("0"), target + 2)
			self.assertTrue(all(p in ("0", s) for p, s in zip(puzzle, solution)))
			for unit in sudoku.ROWS + sudoku.COLS + sudoku.BOXES:
				self.assertEqual({solution[i] for i in unit}, set("123456789"))

	def test_sudoku_submit_checks_answer_and_saves_time(self):
		from .models import Score

		self.client.force_login(self.user)
		s = self.post("sudoku_start", {"level": "easy"})
		session = cache.get(f"sudoku:{s['token']}")
		self.assertEqual(s["puzzle"], session["puzzle"])
		self.assertNotIn("solution", s)  # 답은 보내지 않음
		wrong = session["solution"][:-1] + ("1" if session["solution"][-1] != "1" else "2")
		self.assertIn("맞지 않아요", self.post("sudoku_submit", {"token": s["token"], "grid": wrong})["error"])
		r = self.post("sudoku_submit", {"token": s["token"], "grid": session["solution"]})
		self.assertTrue(r["ok"] and r["saved"] and r["best"])
		self.assertEqual(Score.objects.get().board, "sudoku-easy")
		self.assertIn("초", r["leaderboard"]["rows"][0]["text"])
		self.assertIn("게임 정보가 없어요", self.post("sudoku_submit", {"token": s["token"], "grid": session["solution"]})["error"])  # 한 번만

	def test_sudoku_hint_fixes_wrong_cell_and_skips_ranking(self):
		from .models import Score

		self.client.force_login(self.user)
		s = self.post("sudoku_start", {"level": "easy"})
		sol = cache.get(f"sudoku:{s['token']}")["solution"]
		blank = s["puzzle"].index("0")
		grid = list(s["puzzle"])
		grid[blank] = "1" if sol[blank] != "1" else "2"
		h = self.post("sudoku_hint", {"token": s["token"], "grid": "".join(grid)})
		self.assertEqual((h["i"], h["v"], h["wrong"]), (blank, int(sol[blank]), True))
		r = self.post("sudoku_submit", {"token": s["token"], "grid": sol})
		self.assertEqual((r["saved"], r["reason"]), (False, "hint"))
		self.assertFalse(Score.objects.exists())

	def test_time_leaderboard_lower_is_better(self):
		from .models import Score
		from .scores import leaderboard

		other = get_user_model().objects.create_user("fast", "f@example.com", "pw-for-tests-only")
		Score.objects.create(board="mines-easy", user=self.user, score=30_000)
		Score.objects.create(board="mines-easy", user=self.user, score=95_500)
		Score.objects.create(board="mines-easy", user=other, score=12_300)
		lb = leaderboard("mines-easy", self.user)
		self.assertEqual([(r["name"], r["text"]) for r in lb["rows"]], [("fast", "12.3초"), ("solo", "30.0초")])
		self.assertEqual((lb["mine"]["rank"], lb["mine"]["text"]), (2, "30.0초"))
		self.assertEqual(leaderboard("mines-hard")["rows"], [])
		from .scores import time_text
		self.assertEqual(time_text(95_500), "1:35.5")

	def test_mines_first_click_safe_and_win_saves(self):
		from .models import Score

		self.client.force_login(self.user)
		s = self.post("mines_start", {"level": "easy"})
		self.assertEqual((s["rows"], s["cols"], s["count"]), (9, 9, 10))
		r = self.post("mines_open", {"token": s["token"], "cells": [40]})
		self.assertEqual(r["state"], "playing")
		self.assertEqual(r["shown"]["40"], 0)  # 첫 칸과 주변엔 지뢰가 없음
		self.assertNotIn("mines", r)  # 끝나기 전엔 지뢰 위치를 안 보냄
		board = cache.get(f"mines:{s['token']}")["board"]
		safe = [i for i in range(81) if i not in board.mines and i not in board.opened]
		for k in range(0, len(safe), 8):
			r = self.post("mines_open", {"token": s["token"], "cells": safe[k:k + 8]})
		self.assertEqual(r["state"], "won")
		self.assertEqual(len(r["mines"]), 10)
		self.assertTrue(r["saved"])
		self.assertEqual(Score.objects.get().board, "mines-easy")

	def test_mines_boom_ends_game(self):
		s = self.post("mines_start", {"level": "normal"})
		self.post("mines_open", {"token": s["token"], "cells": [0]})
		mine = min(cache.get(f"mines:{s['token']}")["board"].mines)
		r = self.post("mines_open", {"token": s["token"], "cells": [mine]})
		self.assertEqual((r["state"], r["boom"]), ("lost", mine))
		self.assertIn(mine, r["mines"])
		self.assertIn("게임 정보가 없어요", self.post("mines_open", {"token": s["token"], "cells": [1]})["error"])
		t = self.post("mines_start", {})["token"]
		self.assertIn("올바르지", self.post("mines_open", {"token": t, "cells": []})["error"])

	def test_trace_scores_each_shape_and_total(self):
		from . import trace
		from .models import Score

		self.client.force_login(self.user)
		s = self.post("trace_start", {"mode": "memory"})
		self.assertEqual(len(s["shapes"]), trace.ROUND)
		scores = []
		for i, shape in enumerate(s["shapes"]):
			strokes = [shape["points"]] if i % 2 == 0 else [[[0.1, 0.1], [0.2, 0.9], [0.9, 0.2]]]
			r = self.post("trace_draw", {"token": s["token"], "i": i, "strokes": strokes})
			scores.append(r["score"])
			if i == 0:
				self.assertIn("이미 채점한", self.post("trace_draw", {"token": s["token"], "i": 0, "strokes": strokes})["error"])
		self.assertTrue(r["done"])
		self.assertEqual(scores[0], 100)
		self.assertLess(scores[1], 40)
		self.assertEqual(r["total"], sum(scores))
		self.assertEqual(Score.objects.get().board, "trace-memory")

	def test_trace_scoring_rejects_junk(self):
		from . import trace

		self.assertEqual(trace.score("circle", "nope"), 0)
		self.assertEqual(trace.score("circle", [[["a", 1]], [[float("nan"), 0.5]]]), 0)
		self.assertEqual(trace.score("star", [trace.SHAPES["star"][1]]), 100)
		scribble = [[[x / 20, y / 20] for x in range(21)] for y in range(21)]  # 판 전체를 칠하기
		self.assertLess(trace.score("star", scribble), 30)
