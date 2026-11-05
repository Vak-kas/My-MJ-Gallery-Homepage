"""2026-11-05 보안 점검 '중간' 항목 회귀 테스트"""

import json
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import make_password
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from blog.models import Post


class ProtectedPostLeakTests(TestCase):
	def setUp(self):
		cache.clear()
		self.admin = get_user_model().objects.create_superuser("own", "o@x.kr", "pw-for-tests-only")
		self.post = Post.objects.create(
			title="잠긴 글", slug="locked", category="tech", author=self.admin, is_published=True, published_at=timezone.now(),
			summary="비밀요약", content="비밀본문내용", visibility=Post.VISIBILITY_PROTECTED,
		)
		self.post.set_access_password("1234") if hasattr(self.post, "set_access_password") else None
		self.post.save()

	def tearDown(self):
		cache.clear()

	def test_hub_and_search_do_not_leak(self):
		hub = self.client.get(reverse("blog:index")).content.decode()
		self.assertIn("잠긴 글", hub)
		self.assertNotIn("비밀요약", hub)
		self.assertNotIn("비밀본문", hub)
		self.assertIn("비밀번호가 필요한 보호글", hub)
		found = self.client.get(reverse("blog:index"), {"q": "비밀본문"}).context["feed_posts"]
		self.assertEqual(list(found), [])        # 본문으로는 못 찾음
		found = self.client.get(reverse("blog:index"), {"q": "잠긴"}).context["feed_posts"]
		self.assertEqual([p.title for p in found], ["잠긴 글"])   # 제목으로는 찾음

	def test_unlock_attempts_limited_without_session(self):
		url = reverse("blog:post_detail", args=[self.post.slug])
		for _ in range(6):
			self.client.cookies.clear()            # 쿠키를 버려도
			self.client.post(url, {"action": "unlock_post", "post_password": "wrong"})
		from blog.views import _unlock_cache_keys
		from django.test import RequestFactory
		req = RequestFactory().get("/")
		ip_key, _ = _unlock_cache_keys(req, self.post)
		self.assertGreater((cache.get(ip_key) or {}).get("blocked_until", 0), 0)


class NetcheckPortTests(TestCase):
	def test_huge_range_rejected_without_building_list(self):
		from tools.netcheck import CheckError, _parse_ports
		with self.assertRaises(CheckError):
			_parse_ports("1-400000000")
		with self.assertRaises(CheckError):
			_parse_ports("1-65535")
		self.assertEqual(_parse_ports("80, 443, 8000-8002"), [80, 443, 8000, 8001, 8002])

	def test_json_array_body_is_400(self):
		user = get_user_model().objects.create_user("nc", "n@x.kr", "pw-for-tests-only")
		self.client.force_login(user)
		res = self.client.post(reverse("tools:netcheck_run"), "[]", content_type="application/json")
		self.assertEqual(res.status_code, 400)


class StdlibReindexTests(TestCase):
	def test_reindex_while_processing_is_refused(self):
		from unittest import mock
		from tools.models import StdDoc
		from tools.permissions import set_vip
		user = get_user_model().objects.create_user("vip", "v@x.kr", "pw-for-tests-only")
		set_vip(user, True)
		self.client.force_login(user)
		doc = StdDoc.objects.create(user=user, title="t", filename="t.pdf", size=1, status=StdDoc.STATUS_PROCESSING)
		with mock.patch("tools.stdlib.start_index") as start:
			res = self.client.post(reverse("tools:stdlib_doc_action", args=[doc.pk, "reindex"]))
			self.assertEqual(res.status_code, 409)
			StdDoc.objects.filter(pk=doc.pk).update(status=StdDoc.STATUS_READY)
			other = StdDoc.objects.create(user=user, title="u", filename="u.pdf", size=1, status=StdDoc.STATUS_PROCESSING)
			res = self.client.post(reverse("tools:stdlib_doc_action", args=[doc.pk, "reindex"]))
			self.assertEqual(res.status_code, 429)        # 이미 다른 문서를 나누는 중
			other.delete()
			res = self.client.post(reverse("tools:stdlib_doc_action", args=[doc.pk, "reindex"]))
			self.assertEqual(res.status_code, 200)
		self.assertEqual(start.call_count, 1)


class WebmailStyleTests(TestCase):
	def test_css_escape_and_image_set_removed(self):
		from webmail.sanitize import sanitize_html
		for bad in (
			'<div style="background:\\75 rl(https://t.evil/p.gif)">a</div>',
			'<div style="background-image:image-set(&quot;https://t.evil/p.gif&quot; 1x)">a</div>',
			'<div style="background:u/**/rl(https://t.evil/p.gif)">a</div>',
			'<div style="position:fixed;inset:0">a</div>',
		):
			self.assertNotIn("style=", sanitize_html(bad), bad)
		self.assertIn('style="color:red"', sanitize_html('<p style="color:red">ok</p>'))
		self.assertEqual(sanitize_html("<svg/><b>after</b>"), "<b>after</b>")


class MeetPinTests(TestCase):
	def setUp(self):
		cache.clear()

	def tearDown(self):
		cache.clear()

	def test_pin_bruteforce_limited(self):
		from tools.models import Meeting, MeetingResponse
		owner = get_user_model().objects.create_user("mo", "mo@x.kr", "pw-for-tests-only")
		m = Meeting.objects.create(owner=owner, title="t", dates=["2026-11-10"], start_min=540, end_min=600, expires_at=timezone.now() + timedelta(days=7))
		MeetingResponse.objects.create(meeting=m, name="민재", key_hash="x", pin_hash=make_password("4321"))
		url = reverse("tools:meet_join", args=[m.meet_id])
		codes = [self.client.post(url, json.dumps({"name": "민재", "pin": f"{i:04d}"}), content_type="application/json").status_code for i in range(12)]
		self.assertEqual(codes[:10], [403] * 10)
		self.assertEqual(codes[10:], [429, 429])
		res = self.client.post(url, json.dumps({"name": "민재", "pin": "4321"}), content_type="application/json")
		self.assertEqual(res.status_code, 429)   # 막힌 동안은 맞는 비밀번호도


class JsonArrayBodyTests(TestCase):
	def test_non_object_bodies_are_not_500(self):
		user = get_user_model().objects.create_user("ja", "j@x.kr", "pw-for-tests-only")
		self.client.force_login(user)
		for name in ("tools:secret_create", "tools:ocr_free"):
			res = self.client.post(reverse(name), "[]", content_type="application/json")
			self.assertLess(res.status_code, 500, name)
		res = self.client.post("/contact/", "[1]", content_type="application/json")
		self.assertLess(res.status_code, 500)
