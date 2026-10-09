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
