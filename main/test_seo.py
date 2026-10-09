from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from blog.models import Post


@override_settings(SITE_URL="https://smjgallery.kr")
class LinkPreviewTests(TestCase):
	def setUp(self):
		cache.clear()
		self.author = get_user_model().objects.create_user("seo", "s@example.com", "pw", first_name="서민재")
		content = '{"format":"tiptap","version":1,"doc":{"type":"doc","content":[{"type":"paragraph","content":[{"type":"text","text":"HackRF 로 433MHz 신호를 잡아 본 기록입니다."}]},{"type":"image","attrs":{"src":"/media/blog/editor/a.png"}}]}}'
		self.post = Post.objects.create(category="tech", title="HackRF 입문", slug="hackrf", author=self.author, content=content, published_at=timezone.now())
		self.locked = Post.objects.create(category="tech", title="비밀 글", slug="locked", author=self.author, content=content,
			published_at=timezone.now(), visibility=Post.VISIBILITY_PROTECTED, summary="숨겨야 할 요약")

	def tearDown(self):
		cache.clear()

	def test_post_preview_uses_text_and_first_image(self):
		html = self.client.get(reverse("blog:post_detail", args=["hackrf"])).content.decode()
		self.assertIn('<meta property="og:title" content="HackRF 입문">', html)
		self.assertIn("HackRF 로 433MHz 신호를 잡아 본 기록입니다.", html)
		self.assertIn('<meta property="og:image" content="https://smjgallery.kr/media/blog/editor/a.png">', html)
		self.assertIn('<meta property="og:type" content="article">', html)
		self.assertIn("<title>HackRF 입문 — 서민재 갤러리</title>", html)
		self.assertIn('<link rel="canonical" href="https://smjgallery.kr/blog/post/hackrf/">', html)

	def test_protected_post_hides_content(self):
		html = self.client.get(reverse("blog:post_detail", args=["locked"])).content.decode()
		self.assertIn("비밀번호로 보호된 글", html)
		self.assertNotIn("숨겨야 할 요약", html.split("</head>")[0])
		self.assertNotIn("433MHz", html.split("</head>")[0])
		self.assertIn("og-default.png", html.split("</head>")[0])

	def test_default_and_tool_pages(self):
		html = self.client.get("/").content.decode()
		self.assertIn('<meta property="og:image" content="https://smjgallery.kr/static/images/og-default.png">', html)
		html = self.client.get(reverse("tools:qrcode")).content.decode()
		self.assertIn("QR 코드 만들기 · Tool", html)

	def test_private_pages_noindex(self):
		html = self.client.get("/tools/secret/abc/").content.decode()
		self.assertIn('name="robots" content="noindex, nofollow"', html)
		self.assertNotIn('rel="canonical"', html)

	def test_sitemap_robots_feed(self):
		xml = self.client.get("/sitemap.xml").content.decode()
		self.assertIn("https://", xml)
		self.assertIn("/blog/post/hackrf/", xml)
		self.assertNotIn("/blog/post/locked/", xml)
		self.assertIn("/tools/qrcode/", xml)
		self.assertNotIn("/tools/secret/", xml)
		robots = self.client.get("/robots.txt").content.decode()
		self.assertIn("Disallow: /studio/", robots)
		self.assertIn("Sitemap: https://smjgallery.kr/sitemap.xml", robots)
		feed = self.client.get("/blog/feed/").content.decode()
		self.assertIn("<title>HackRF 입문</title>", feed)
		self.assertNotIn("비밀 글", feed)

	def test_hidden_blog_not_in_sitemap(self):
		admin = get_user_model().objects.create_superuser("admin", "a@example.com", "pw")
		self.client.force_login(admin)
		order = ["profile", "skill", "career", "activity", "award", "publication", "project", "blog_links"]
		self.client.post(reverse("studio:settings"), {"nav_order": ["home", "blog", "tool", "photo"], "home_order": order,
			"nav_state_blog": "admin", **{f"home_on_{k}": "on" for k in order}})
		self.client.logout()
		xml = self.client.get("/sitemap.xml").content.decode()
		self.assertNotIn("/blog/", xml)


@override_settings(SITE_URL="https://smjgallery.kr")
class PostCardImageTests(TestCase):
	def setUp(self):
		import tempfile
		cache.clear()
		self.tmp = tempfile.mkdtemp()
		self.override = override_settings(MEDIA_ROOT=self.tmp)
		self.override.enable()
		self.author = get_user_model().objects.create_user("seo", "s@example.com", "pw", first_name="서민재")
		self.post = Post.objects.create(category="life", title="정처기 합격 야미", slug="pass", author=self.author, published_at=timezone.now())

	def tearDown(self):
		import shutil
		self.override.disable()
		shutil.rmtree(self.tmp, ignore_errors=True)
		cache.clear()

	def test_meta_uses_card_when_no_photo(self):
		html = self.client.get(reverse("blog:post_detail", args=["pass"])).content.decode()
		self.assertIn('content="https://smjgallery.kr/blog/post/pass/og.png?v=', html)

	def test_card_png_rendered_and_cached(self):
		import os
		res = self.client.get(reverse("blog:post_og", args=["pass"]))
		self.assertEqual(res["Content-Type"], "image/png")
		body = b"".join(res.streaming_content)
		self.assertTrue(body.startswith(b"\x89PNG"))
		files = os.listdir(os.path.join(self.tmp, "og", "posts"))
		self.assertEqual(len(files), 1)
		self.client.get(reverse("blog:post_og", args=["pass"]))
		self.assertEqual(len(os.listdir(os.path.join(self.tmp, "og", "posts"))), 1)  # 두 번째는 저장된 걸 씀
		Post.objects.filter(pk=self.post.pk).update(title="새 제목")
		self.client.get(reverse("blog:post_og", args=["pass"]))
		self.assertEqual(len(os.listdir(os.path.join(self.tmp, "og", "posts"))), 2)  # 제목이 바뀌면 새로 그림

	def test_protected_or_missing_gets_default(self):
		Post.objects.filter(pk=self.post.pk).update(visibility=Post.VISIBILITY_PROTECTED)
		res = self.client.get(reverse("blog:post_og", args=["pass"]))
		self.assertEqual(res.status_code, 302)
		self.assertIn("og-default.png", res["Location"])
		self.assertEqual(self.client.get(reverse("blog:post_og", args=["nope"])).status_code, 302)
