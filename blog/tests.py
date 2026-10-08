import json

from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from blog.models import GuestbookEntry
from blog.content import parse_content, render_tiptap_html, tiptap_cover_image, tiptap_plain_text
from blog.templatetags.blog_extras import editorjs_cover_image, editorjs_excerpt, render_editorjs


def tiptap(*blocks):
	return json.dumps({"format": "tiptap", "version": 1, "doc": {"type": "doc", "content": list(blocks)}})


def para(*inline):
	return {"type": "paragraph", "content": list(inline)}


def text(value, *marks):
	node = {"type": "text", "text": value}
	if marks:
		node["marks"] = list(marks)
	return node


class ParseContentTests(SimpleTestCase):
	def test_detects_formats(self):
		self.assertEqual(parse_content(tiptap(para(text("a"))))[0], "tiptap")
		self.assertEqual(parse_content(json.dumps({"blocks": []}))[0], "editorjs")
		self.assertEqual(parse_content("<p>old</p>")[0], "raw")
		self.assertEqual(parse_content("")[0], "raw")


class TiptapRenderTests(SimpleTestCase):
	def render(self, *blocks):
		return str(render_editorjs(tiptap(*blocks)))

	def test_basic_blocks(self):
		html = self.render(
			{"type": "heading", "attrs": {"level": 2}, "content": [text("제목")]},
			para(text("굵게", {"type": "bold"}), text(" 보통")),
			{"type": "bulletList", "content": [{"type": "listItem", "content": [para(text("하나"))]}]},
			{"type": "taskList", "content": [{"type": "taskItem", "attrs": {"checked": True}, "content": [para(text("완료"))]}]},
			{"type": "codeBlock", "content": [text("<b>x</b>")]},
			{"type": "horizontalRule"},
		)
		self.assertIn("<h2", html)
		self.assertIn("<strong>굵게</strong> 보통", html)
		self.assertIn("<ul class=\"list-disc", html)
		self.assertIn("checked", html)
		self.assertIn("&lt;b&gt;x&lt;/b&gt;", html)
		self.assertIn("<hr", html)

	def test_math_uses_katex_placeholder(self):
		html = self.render(
			para(text("식 "), {"type": "inlineMath", "attrs": {"latex": "x^2"}}),
			{"type": "blockMath", "attrs": {"latex": "\\frac{a}{b}"}},
		)
		self.assertIn('class="mj-katex" data-latex="x^2" data-display="0"', html)
		self.assertIn('data-display="1"', html)

	def test_details_table_image_linkcard(self):
		html = self.render(
			{"type": "details", "attrs": {"open": True}, "content": [
				{"type": "detailsSummary", "content": [text("토글")]},
				{"type": "detailsContent", "content": [para(text("안"))]},
			]},
			{"type": "table", "content": [{"type": "tableRow", "content": [
				{"type": "tableHeader", "content": [para(text("머리"))]},
				{"type": "tableCell", "attrs": {"colspan": 2}, "content": [para(text("칸"))]},
			]}]},
			{"type": "image", "attrs": {"src": "/media/a.jpg", "caption": "설명"}},
			{"type": "linkCard", "attrs": {"url": "https://example.com", "title": "예제", "mode": "card"}},
		)
		self.assertIn("<details", html)
		self.assertIn(" open>", html)
		self.assertIn("<th", html)
		self.assertIn('colspan="2"', html)
		self.assertIn('src="/media/a.jpg"', html)
		self.assertIn("설명", html)
		self.assertIn('href="https://example.com"', html)

	def test_text_is_escaped(self):
		html = self.render(para(text("<script>alert(1)</script>")))
		self.assertNotIn("<script>", html)
		self.assertIn("&lt;script&gt;", html)

	def test_unsafe_urls_are_dropped(self):
		html = self.render(
			para(text("링크", {"type": "link", "attrs": {"href": "javascript:alert(1)"}})),
			{"type": "image", "attrs": {"src": "javascript:alert(1)"}},
			{"type": "linkCard", "attrs": {"url": "javascript:alert(1)", "title": "x"}},
		)
		self.assertNotIn("javascript:", html)
		self.assertIn("링크", html)

	def test_style_values_are_whitelisted(self):
		good = self.render(para(text("색", {"type": "textStyle", "attrs": {"color": "#d44c47", "fontFamily": "'Noto Serif KR', serif"}})))
		self.assertIn("color:#d44c47", good)
		self.assertIn("font-family", good)
		bad = self.render(para(text("색", {"type": "textStyle", "attrs": {"color": "red;background:url(x)", "fontFamily": "x;}</style>"}})))
		self.assertNotIn("url(", bad)
		self.assertNotIn("style=", bad)

	def test_attribute_quotes_are_escaped(self):
		html = self.render({"type": "image", "attrs": {"src": '/a.jpg" onerror="alert(1)', "caption": ""}})
		self.assertNotIn('onerror="alert', html)


class TiptapTextAndCoverTests(SimpleTestCase):
	def test_excerpt(self):
		content = tiptap(
			{"type": "heading", "attrs": {"level": 1}, "content": [text("안녕")]},
			para(text("하세요"), {"type": "inlineMath", "attrs": {"latex": "x"}}),
		)
		self.assertEqual(editorjs_excerpt(content), "안녕 하세요x")
		self.assertTrue(editorjs_excerpt(tiptap(para(text("가" * 300)))).endswith("…"))

	def test_cover_prefers_marked_image(self):
		content = tiptap(
			{"type": "image", "attrs": {"src": "/media/1.jpg"}},
			{"type": "image", "attrs": {"src": "/media/2.jpg", "isCover": True}},
		)
		self.assertEqual(editorjs_cover_image(content), "/media/2.jpg")
		self.assertEqual(editorjs_cover_image(tiptap({"type": "image", "attrs": {"src": "/media/1.jpg"}})), "/media/1.jpg")
		self.assertEqual(editorjs_cover_image(tiptap(para(text("x")))), "")

	def test_plain_helpers_handle_empty_doc(self):
		self.assertEqual(render_tiptap_html({}), "")
		self.assertEqual(tiptap_plain_text({}), "")
		self.assertEqual(tiptap_cover_image({}), "")


class LegacyEditorJsTests(SimpleTestCase):
	def test_legacy_still_renders(self):
		content = json.dumps({"blocks": [
			{"type": "paragraph", "data": {"text": "예전 글"}},
			{"type": "image", "data": {"url": "/media/old.jpg", "isCover": True}},
		]})
		self.assertIn("예전 글", str(render_editorjs(content)))
		self.assertEqual(editorjs_cover_image(content), "/media/old.jpg")
		self.assertEqual(editorjs_excerpt(content), "예전 글")

	def test_legacy_linkcard_blocks_javascript_url(self):
		content = json.dumps({"blocks": [{"type": "linkcard", "data": {"url": "javascript:alert(1)", "title": "x"}}]})
		self.assertNotIn("javascript:", str(render_editorjs(content)))


class GuestbookTests(TestCase):
	def setUp(self):
		from django.contrib.auth import get_user_model
		self.user = get_user_model().objects.create_user(username="visitor", password="pw-for-tests-only")
		self.url = reverse("blog:index")

	def test_anonymous_cannot_post(self):
		resp = self.client.post(self.url, {"author_name": "555", "message": "-1' OR 2+457-457-1=0+0+0+1"})
		self.assertEqual(resp.status_code, 302)
		self.assertIn(reverse("accounts:login"), resp["Location"])
		self.assertFalse(GuestbookEntry.objects.exists())

	def test_anonymous_sees_login_prompt_not_form(self):
		resp = self.client.get(self.url)
		self.assertContains(resp, "방명록은 로그인 후 남길 수 있어요")
		self.assertNotContains(resp, 'name="message"')

	def test_logged_in_post_uses_account_name(self):
		self.client.force_login(self.user)
		self.client.post(self.url, {"author_name": "가짜이름", "message": "안녕하세요"})
		entry = GuestbookEntry.objects.get()
		self.assertEqual(entry.author, self.user)
		self.assertEqual(entry.author_name, "visitor")

	def test_rate_limit_one_per_minute(self):
		self.client.force_login(self.user)
		self.client.post(self.url, {"message": "첫 번째"})
		self.client.post(self.url, {"message": "두 번째"})
		self.assertEqual(GuestbookEntry.objects.count(), 1)

	def test_daily_limit(self):
		from datetime import timedelta
		from django.utils import timezone
		for i in range(10):
			entry = GuestbookEntry.objects.create(author=self.user, author_name="visitor", message=str(i))
			GuestbookEntry.objects.filter(pk=entry.pk).update(created_at=timezone.now() - timedelta(minutes=10 + i))
		self.client.force_login(self.user)
		self.client.post(self.url, {"message": "11번째"})
		self.assertEqual(GuestbookEntry.objects.count(), 10)

	def test_attack_strings_are_stored_as_plain_text(self):
		payload = "<script>alert(1)</script> -1' OR 3*2<(0+5+20-20) --"
		GuestbookEntry.objects.create(author_name=payload, message=payload)
		resp = self.client.get(self.url)
		self.assertNotContains(resp, "<script>alert(1)</script>")
		self.assertContains(resp, "&lt;script&gt;")


class ClearGuestbookCommandTests(TestCase):
	def test_dry_run_keeps_entries_and_yes_backs_up_then_deletes(self):
		import json
		import tempfile
		from io import StringIO
		from pathlib import Path

		from django.core.management import call_command

		GuestbookEntry.objects.create(author_name="555", message="-1' OR 2+457-457-1=0+0+0+1")
		GuestbookEntry.objects.create(author_name="a", message="b")

		call_command("clear_guestbook", stdout=StringIO())
		self.assertEqual(GuestbookEntry.objects.count(), 2)

		with tempfile.TemporaryDirectory() as tmp:
			call_command("clear_guestbook", "--yes", f"--backup-dir={tmp}", stdout=StringIO())
			self.assertEqual(GuestbookEntry.objects.count(), 0)
			backups = list(Path(tmp).glob("guestbook-*.json"))
			self.assertEqual(len(backups), 1)
			self.assertEqual(len(json.loads(backups[0].read_text(encoding="utf-8"))), 2)


class DraftVsPublishedTests(TestCase):
	def setUp(self):
		from django.contrib.auth import get_user_model
		from django.utils import timezone
		from blog.models import Post
		self.admin = get_user_model().objects.create_superuser("admin", "admin@example.com", "pw-for-tests-only")
		self.client.force_login(self.admin)
		self.published_at = timezone.now().replace(microsecond=0)
		self.post = Post.objects.create(title="발행글", slug="published-post", category=Post.CATEGORY_TECH, author=self.admin, content="", is_published=True, published_at=self.published_at)
		self.draft = Post.objects.create(title="쓰는중", slug="draft-post", category=Post.CATEGORY_TECH, author=self.admin, content="", is_published=False)

	def test_edit_page_warns_that_draft_unpublishes_a_published_post(self):
		resp = self.client.get(reverse("blog:post_edit", args=[self.post.slug]))
		self.assertContains(resp, "발행 취소 · 임시저장으로")
		self.assertContains(resp, 'data-unpublish="1"')
		resp = self.client.get(reverse("blog:post_edit", args=[self.draft.slug]))
		self.assertContains(resp, ">임시저장</button>")

	def test_unpublishing_keeps_original_publish_date(self):
		self.client.post(reverse("blog:post_edit", args=[self.post.slug]), {"title": "발행글", "category": "tech", "content": "", "submit_action": "draft"})
		self.post.refresh_from_db()
		self.assertFalse(self.post.is_published)
		self.assertEqual(self.post.published_at, self.published_at)

	def test_studio_lists_drafts_separately(self):
		resp = self.client.get(reverse("studio:posts"))
		self.assertContains(resp, "📝 임시저장 · 나만 보임")
		self.assertContains(resp, "이어서 쓰기")
		drafts = self.client.get(reverse("studio:posts"), {"status": "draft"})
		self.assertContains(drafts, "쓰는중")
		self.assertNotContains(drafts, ">발행글</a>")
		published = self.client.get(reverse("studio:posts"), {"status": "published"})
		self.assertContains(published, "발행글")
		self.assertNotContains(published, ">쓰는중</a>")
