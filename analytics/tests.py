from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from blog.models import Post

from .models import PageView
from .tracking import classify, device_of

CHROME = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 Chrome/130.0 Safari/537.36"
IPHONE_KAKAO = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148 KAKAOTALK 10.8.0"


@override_settings(SITE_URL="https://smjgallery.kr")
class TrackingTests(TestCase):
	def setUp(self):
		cache.clear()
		self.admin = get_user_model().objects.create_superuser("admin", "a@example.com", "pw")

	def get(self, path, ua=CHROME, ip="203.0.113.5", **extra):
		return self.client.get(path, HTTP_USER_AGENT=ua, HTTP_X_REAL_IP=ip, **extra)

	def test_records_page_without_ip(self):
		self.get("/", HTTP_REFERER="https://www.google.com/search?q=smj")
		pv = PageView.objects.get()
		self.assertEqual((pv.path, pv.section, pv.source, pv.referrer_host, pv.device), ("/", "home", "search", "google.com", "desktop"))
		self.assertEqual(len(pv.visitor), 16)
		self.assertNotIn("203.0.113.5", str(PageView.objects.values().get()))

	def test_skips_bots_admin_studio_and_non_html(self):
		self.get("/", ua="Mozilla/5.0 (compatible; Googlebot/2.1)")
		self.get("/", ua="facebookexternalhit/1.1")
		self.get("/robots.txt")
		self.get("/static/images/og-default.png")
		self.client.force_login(self.admin)
		self.get("/")
		self.get("/studio/")
		self.assertEqual(PageView.objects.count(), 0)

	def test_same_visitor_same_day_one_hash(self):
		self.get("/")
		self.get("/blog/")
		self.get("/", ip="198.51.100.9")
		self.assertEqual(PageView.objects.values("visitor").distinct().count(), 2)

	def test_classify(self):
		self.assertEqual(classify("", IPHONE_KAKAO, "smjgallery.kr")[0], "kakao")
		self.assertEqual(classify("https://github.com/Vak-kas", CHROME, "smjgallery.kr"), ("github", "github.com"))
		self.assertEqual(classify("https://smjgallery.kr/blog/", CHROME, "smjgallery.kr")[0], "internal")
		self.assertEqual(classify("https://search.naver.com/x", CHROME, "smjgallery.kr")[0], "search")
		self.assertEqual(classify("", CHROME, "smjgallery.kr")[0], "direct")
		self.assertEqual(device_of(IPHONE_KAKAO), "mobile")

	def test_dashboard(self):
		author = get_user_model().objects.create_user("seo", "s@example.com", "pw")
		Post.objects.create(category="tech", title="HackRF 입문", slug="hackrf", author=author, published_at=timezone.now())
		self.get("/blog/post/hackrf/", ua=IPHONE_KAKAO)
		self.get("/blog/post/hackrf/", ip="198.51.100.1", HTTP_REFERER="https://github.com/")
		self.get("/tools/qrcode/")
		old = PageView.objects.create(day=timezone.localdate() - timedelta(days=100), path="/", section="home", visitor="x", source="direct", device="desktop")
		self.client.force_login(self.admin)
		res = self.client.get(reverse("studio:analytics"), {"days": 7})
		s = res.context["s"]
		self.assertEqual((s["today_views"], s["today_visitors"]), (3, 3))
		self.assertEqual(s["posts"][0]["title"], "📝 HackRF 입문")
		self.assertIn("QR 코드 만들기", s["tools"][0]["title"])
		self.assertEqual({x["key"] for x in s["sources"]}, {"kakao", "github", "direct"})
		self.assertFalse(PageView.objects.filter(pk=old.pk).exists())  # 90일 지난 기록 정리
		self.assertContains(res, "방문자 통계")

	def test_member_cannot_see_dashboard(self):
		member = get_user_model().objects.create_user("m", "m@example.com", "pw")
		self.client.force_login(member)
		self.assertEqual(self.client.get(reverse("studio:analytics")).status_code, 302)
