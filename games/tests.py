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
