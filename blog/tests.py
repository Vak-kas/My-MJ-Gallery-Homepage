import json
from unittest import mock

from django.contrib.auth import get_user_model

from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from blog.models import GuestbookEntry, Post
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

	def test_divider_styles(self):
		html = self.render({"type": "horizontalRule", "attrs": {"style": "circle"}})
		self.assertIn('data-divider="circle"', html)
		self.assertIn("rounded-full", html)
		self.assertIn("⁂", self.render({"type": "horizontalRule", "attrs": {"style": "asterism"}}))
		# 모르는 모양·없는 모양은 기본 선, 속성값은 이스케이프
		for bad in ({"style": "<script>"}, {"style": None}, None):
			node = {"type": "horizontalRule"}
			if bad is not None:
				node["attrs"] = bad
			out = self.render(node)
			self.assertIn('<hr class="w-full border-t border-[#d2d2d7]"', out)
			self.assertNotIn("<script>", out)

	def test_callout(self):
		html = self.render({
			"type": "callout", "attrs": {"kind": "warn"},
			"content": [
				{"type": "calloutTitle", "content": [text("표기법 안내")]},
				{"type": "calloutBody", "content": [para(text("본문 "), {"type": "inlineMath", "attrs": {"latex": "N_{ID}"}})]},
			],
		})
		self.assertIn('data-callout="warn"', html)
		self.assertIn("⚠️", html)
		self.assertIn("표기법 안내", html)
		self.assertIn('data-latex="N_{ID}"', html)
		# 제목이 비면 제목 줄 없음, 아이콘 지정·종류 모름·속성 없음도 안전
		plain = self.render({"type": "callout", "attrs": {"kind": "<x>", "icon": "<b>"}, "content": [
			{"type": "calloutTitle"}, {"type": "calloutBody", "content": [para(text("only"))]}]})
		self.assertIn('data-callout="info"', plain)
		self.assertIn("&lt;b&gt;", plain)
		self.assertNotIn("<b>", plain)
		self.assertNotIn("font-bold", plain)
		self.assertIn("only", self.render({"type": "callout", "content": [{"type": "calloutBody", "content": [para(text("only"))]}]}))

	def test_callout_aside_and_table_widths(self):
		html = self.render({
			"type": "callout", "attrs": {"kind": "warn"},
			"content": [
				{"type": "calloutTitle", "content": [text("표기법")]},
				{"type": "calloutBody", "content": [para(text("본문"))]},
				{"type": "calloutAside", "content": [{"type": "blockMath", "attrs": {"latex": "N^{cell}_{ID}"}}]},
			],
		})
		self.assertIn("data-callout-aside", html)
		self.assertIn('data-latex="N^{cell}_{ID}"', html)
		self.assertLess(html.index("본문"), html.index("data-callout-aside"))

		def cell(width=None, **attrs):
			node = {"type": "tableCell", "attrs": dict(attrs), "content": [para(text("c"))]}
			if width is not None:
				node["attrs"]["colwidth"] = width
			return node
		table = self.render({"type": "table", "content": [
			{"type": "tableRow", "content": [cell([120]), cell([None]), cell(["x"])]},
		]})
		self.assertIn('<colgroup><col style="width:120px"><col><col></colgroup>', table)
		self.assertIn('style="min-width:120px"', table)
		# 너비 없는 표는 colgroup 없음, 병합 셀(colspan)은 열 수만큼 자리 차지
		plain = self.render({"type": "table", "content": [{"type": "tableRow", "content": [cell(), cell()]}]})
		self.assertNotIn("colgroup", plain)
		merged = self.render({"type": "table", "content": [{"type": "tableRow", "content": [cell([100, 50], colspan=2)]}]})
		self.assertIn('<col style="width:100px"><col style="width:50px">', merged)
		self.assertIn('colspan="2"', merged)

	def test_text_align(self):
		html = self.render(
			{"type": "paragraph", "attrs": {"textAlign": "center"}, "content": [text("가운데")]},
			{"type": "heading", "attrs": {"level": 2, "textAlign": "right"}, "content": [text("오른쪽")]},
			{"type": "blockMath", "attrs": {"latex": "x", "textAlign": "center"}},
			{"type": "paragraph", "attrs": {"textAlign": "left"}, "content": [text("왼쪽")]},
			{"type": "paragraph", "attrs": {"textAlign": "<bad>"}, "content": [text("이상")]},
		)
		self.assertIn('class="mb-4 leading-[1.85] text-center">가운데', html)
		self.assertIn("text-right", html.split("오른쪽")[0])
		self.assertIn("py-3 text-center", html)
		self.assertNotIn("text-left", html)
		self.assertNotIn("<bad>", html)

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
		self.assertNotContains(resp, 'placeholder="메시지를 남겨주세요"')  # 💬 문의 위젯에도 message 입력란이 있어 방명록 입력란만 확인

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


class SeriesTests(TestCase):
	def setUp(self):
		from django.contrib.auth import get_user_model
		from django.utils import timezone
		self.user = get_user_model().objects.create_superuser("seo", "s@example.com", "pw")
		self.client.force_login(self.user)
		self.now = timezone.now()

	def write(self, title, series="HackRF 입문", order=""):
		self.client.post(reverse("blog:post_create"), {
			"title": title, "category": "tech", "content": '{"format":"tiptap","version":1,"doc":{"type":"doc","content":[]}}',
			"series_name": series, "series_order": order, "submit_action": "publish", "is_published": "1",
		})
		return Post.objects.get(title=title)

	def test_auto_order_and_navigation(self):
		from blog.models import Series
		p1 = self.write("1편 준비물")
		p2 = self.write("2편 설치")
		p3 = self.write("3편 첫 수신")
		self.assertEqual([p.series_order for p in (p1, p2, p3)], [1, 2, 3])
		self.assertEqual(Series.objects.count(), 1)
		res = self.client.get(reverse("blog:post_detail", args=[p2.slug]))
		self.assertEqual(res.context["series_index"], 2)
		self.assertEqual(res.context["series_prev"], p1)
		self.assertEqual(res.context["series_next"], p3)
		self.assertContains(res, "📚 HackRF 입문")
		page = self.client.get(reverse("blog:series", args=[p1.series.slug]))
		self.assertEqual([p.title for p in page.context["series_parts"]], ["1편 준비물", "2편 설치", "3편 첫 수신"])

	def test_draft_keeps_series_when_reopened_and_saved_again(self):
		self.client.post(reverse("blog:post_create"), {
			"title": "초안 2편", "category": "tech", "content": "", "series_name": "HackRF 입문", "submit_action": "draft",
		})
		draft = Post.objects.get(title="초안 2편")
		self.assertEqual(draft.series.name, "HackRF 입문")
		res = self.client.get(f"{reverse('blog:post_create')}?draft={draft.id}")
		self.assertEqual(res.context["form_data"]["series_name"], "HackRF 입문")
		self.assertEqual(res.context["form_data"]["series_order"], 1)
		# 다시 열린 화면 그대로 저장해도 시리즈가 남아야 함
		self.client.post(reverse("blog:post_create"), {
			"draft_id": str(draft.id), "title": "초안 2편", "category": "tech", "content": "",
			"series_name": res.context["form_data"]["series_name"], "series_order": res.context["form_data"]["series_order"], "submit_action": "draft",
		})
		draft.refresh_from_db()
		self.assertEqual((draft.series.name, draft.series_order), ("HackRF 입문", 1))

	def test_drafts_are_not_listed_in_series_even_for_author(self):
		p1 = self.write("1편 준비물")
		self.client.post(reverse("blog:post_create"), {
			"title": "2편 초안", "category": "tech", "content": "", "series_name": "HackRF 입문", "submit_action": "draft",
		})
		draft = Post.objects.get(title="2편 초안")
		self.assertFalse(draft.is_published)
		res = self.client.get(reverse("blog:post_detail", args=[p1.slug]))   # 작성자(관리자)로 봐도
		self.assertEqual([p.title for p in res.context["series_parts"]], ["1편 준비물"])
		self.assertIsNone(res.context["series_next"])
		page = self.client.get(reverse("blog:series", args=[p1.series.slug]))
		self.assertNotContains(page, "2편 초안")
		self.client.logout()
		res = self.client.get(reverse("blog:post_detail", args=[p1.slug]))
		self.assertNotContains(res, "2편 초안")

	def test_explicit_order_and_remove(self):
		p = self.write("번외편", order="10")
		self.assertEqual(p.series_order, 10)
		self.client.post(reverse("blog:post_edit", args=[p.slug]), {
			"title": "번외편", "category": "tech", "content": p.content, "series_name": "", "submit_action": "publish", "is_published": "1",
		})
		p.refresh_from_db()
		self.assertIsNone(p.series)

	def test_hidden_parts_not_listed_for_visitors(self):
		p1 = self.write("공개 편")
		p2 = self.write("비공개 편")
		Post.objects.filter(pk=p2.pk).update(visibility=Post.VISIBILITY_PRIVATE)
		self.client.logout()
		res = self.client.get(reverse("blog:post_detail", args=[p1.slug]))
		self.assertEqual([p.title for p in res.context["series_parts"]], ["공개 편"])


class TagTests(TestCase):
	def setUp(self):
		from django.contrib.auth import get_user_model
		self.user = get_user_model().objects.create_superuser("tagger", "t@example.com", "pw")
		self.client.force_login(self.user)

	def post(self, title, tags):
		self.client.post(reverse("blog:post_create"), {
			"title": title, "category": "tech", "content": '{"format":"tiptap","version":1,"doc":{"type":"doc","content":[]}}',
			"tags": tags, "submit_action": "publish", "is_published": "1",
		})
		return Post.objects.get(title=title)

	def test_leading_hash_is_stripped_and_deduped(self):
		from blog.models import Tag
		p = self.post("글", "#3GPP, ##5G, 5G , #, 3gpp")
		self.assertEqual(sorted(t.name for t in p.tags.all()), ["3GPP", "5G"])
		self.assertFalse(Tag.objects.filter(name__startswith="#").exists())
		res = self.client.get(reverse("blog:tech"))
		self.assertNotContains(res, "##")
		# 수정 화면에는 # 없는 이름으로 채워짐
		res = self.client.get(reverse("blog:post_edit", args=[p.slug]))
		self.assertEqual(res.context["form_data"]["tags"], "3GPP, 5G")

	def test_migration_merges_hashed_tags(self):
		import importlib
		from django.apps import apps
		from blog.models import Tag
		good = Tag.objects.create(name="5G", slug="5g")
		bad = Tag.objects.create(name="#5G", slug="5g-2")
		lone = Tag.objects.create(name="#NGRAN", slug="ngran-x")
		p = self.post("글", "")
		p.tags.add(bad, lone)
		importlib.import_module("blog.migrations.0012_strip_hash_from_tags").strip_hashes(apps, None)
		self.assertEqual(sorted(t.name for t in p.tags.all()), ["5G", "NGRAN"])
		self.assertEqual(Tag.objects.filter(name__in=["5G", "NGRAN"]).count(), 2)
		self.assertFalse(Tag.objects.filter(pk=bad.pk).exists())
		self.assertEqual(Tag.objects.get(pk=lone.pk).slug, "ngran")

	def test_series_picker_lists_my_series_with_counts(self):
		from blog.models import Series
		s = Series.objects.create(author=self.user, name="HackRF 입문", slug="hackrf")
		p = self.post("1편", "")
		Post.objects.filter(pk=p.pk).update(series=s, series_order=1)
		res = self.client.get(reverse("blog:post_create"))
		self.assertEqual(res.context["my_series"], [{"name": "HackRF 입문", "post_count": 1, "published_count": 1, "draft_count": 0, "next_order": 2}])
		self.assertContains(res, "HackRF 입문 — 발행 1편")
		self.assertContains(res, "새 시리즈 만들기")
		# 목록 카드에 시리즈 표시
		res = self.client.get(reverse("blog:tech"))
		self.assertContains(res, "📚 HackRF 입문 · 1편")


class StaticVersionTagTests(SimpleTestCase):
	def test_appends_content_hash(self):
		from blog.templatetags.blog_extras import static_v
		url = static_v("editor/mj-editor.js")
		self.assertRegex(url, r"/static/editor/mj-editor\.js\?v=[0-9a-f]{10}$")
		self.assertEqual(url, static_v("editor/mj-editor.js"))
		self.assertEqual(static_v("editor/does-not-exist.js"), "/static/editor/does-not-exist.js")


class WritePageMarkupTests(TestCase):
	def test_sections_are_balanced(self):
		from django.contrib.auth import get_user_model
		self.client.force_login(get_user_model().objects.create_superuser("w", "w@example.com", "pw"))
		html = self.client.get(reverse("blog:post_create")).content.decode()
		self.assertEqual(html.count("<section"), html.count("</section>"))
		# 태그 상자는 시리즈 상자 밖에 있어야 함
		self.assertLess(html.index('id="series_hint"'), html.index('for="tags"'))
		self.assertIn("</section>", html[html.index('id="series_hint"'):html.index('for="tags"')])


class EditedBadgeTests(SimpleTestCase):
	"""(수정됨) 표시: 임시저장 글을 처음 발행한 건 수정이 아니고, 발행 뒤에 고친 것만 수정"""

	def _post(self, created, published, updated):
		return Post(created_at=created, published_at=published, updated_at=updated)

	def test_draft_published_later_is_not_edited(self):
		from datetime import timedelta
		from django.utils import timezone

		created = timezone.now() - timedelta(days=3)
		published = timezone.now()
		self.assertFalse(self._post(created, published, published + timedelta(seconds=1)).is_edited)

	def test_edit_after_publish_is_edited(self):
		from datetime import timedelta
		from django.utils import timezone

		published = timezone.now() - timedelta(hours=2)
		self.assertTrue(self._post(published - timedelta(days=1), published, timezone.now()).is_edited)

	def test_unpublished_draft_uses_created_at(self):
		from datetime import timedelta
		from django.utils import timezone

		created = timezone.now() - timedelta(hours=1)
		self.assertFalse(self._post(created, None, created + timedelta(seconds=5)).is_edited)
		self.assertTrue(self._post(created, None, timezone.now()).is_edited)


class CategoryPageTests(TestCase):
	"""카테고리 카드 목록: 전체 탭은 모든 카테고리, Secret 은 관리자만, 30개 넘으면 페이지"""

	def setUp(self):
		from django.contrib.auth import get_user_model
		from django.utils import timezone

		self.admin = get_user_model().objects.create_superuser("cat-admin", "a@example.com", "pw")
		now = timezone.now()
		for i, cat in enumerate([Post.CATEGORY_TECH, Post.CATEGORY_LIFE, Post.CATEGORY_SECRET]):
			Post.objects.create(title=f"글 {cat}", slug=f"cat-{cat}", category=cat, author=self.admin, content="", is_published=True, published_at=now)

	def test_all_tab_lists_every_public_category(self):
		res = self.client.get(reverse("blog:all"))
		self.assertEqual(res.status_code, 200)
		self.assertEqual(sorted(p.title for p in res.context["posts"]), ["글 life", "글 tech"])
		self.assertNotContains(res, reverse("blog:secret"))
		self.assertEqual(res.context["active_tab"], "all")

	def test_admin_sees_secret_in_all_tab(self):
		self.client.force_login(self.admin)
		res = self.client.get(reverse("blog:all"))
		self.assertIn("글 secret", [p.title for p in res.context["posts"]])
		self.assertContains(res, reverse("blog:secret"))

	def test_category_tab_filters(self):
		res = self.client.get(reverse("blog:life"))
		# 옆 "인기글 순위" 위젯에는 다른 카테고리도 나오니 카드 목록으로 판정
		self.assertEqual([p.title for p in res.context["posts"]], ["글 life"])
		self.assertContains(res, reverse("blog:all"))

	def test_secret_hidden_from_anonymous(self):
		self.assertEqual(self.client.get(reverse("blog:secret")).status_code, 404)

	def test_pagination_after_30(self):
		from django.utils import timezone

		for i in range(31):
			Post.objects.create(title=f"많은 글 {i}", slug=f"many-{i}", category=Post.CATEGORY_TECH, author=self.admin, content="", is_published=True, published_at=timezone.now())
		res = self.client.get(reverse("blog:all"))
		self.assertEqual(len(res.context["posts"]), 30)
		self.assertContains(res, "?page=2")
		res2 = self.client.get(reverse("blog:all") + "?page=2")
		self.assertEqual(res2.status_code, 200)
		self.assertGreater(len(res2.context["posts"]), 0)


class LegacyEditorJsXssTests(SimpleTestCase):
	"""옛 Editor.js 형식(블록 JSON)에 박힌 HTML 은 서식만 남기고 스크립트·이벤트 속성은 제거해야 함"""

	def test_onerror_img_is_removed(self):
		content = json.dumps({"blocks": [{"type": "paragraph", "data": {
			"html": "<img src=\"/xss-test-missing.png\" onerror=\"alert('x')\"> 글 <b>굵게</b>"}}]})
		out = str(render_editorjs(content))
		self.assertNotIn("onerror", out)
		self.assertNotIn("<img", out)
		self.assertIn("<b>굵게</b>", out)

	def test_script_and_handlers_everywhere(self):
		content = json.dumps({"blocks": [
			{"type": "header", "data": {"text": "<script>alert(1)</script>제목", "level": 2}},
			{"type": "list", "data": {"style": "unordered", "items": ["<a href=\"javascript:alert(1)\" onclick=\"x()\">링크</a>", {"content": "<span onclick=alert(1) style=\"color:red\">둘</span>"}]}},
			{"type": "checklist", "data": {"items": [{"text": "<iframe src=//evil></iframe>할 일", "checked": False}]}},
			{"type": "quote", "data": {"text": "<u onmouseover=alert(1)>인용</u>", "caption": "<img src=x onerror=alert(1)>출처"}},
		]})
		out = str(render_editorjs(content))
		for bad in ("<script", "onclick", "onmouseover", "onerror", "<iframe", "style=", "javascript:"):
			self.assertNotIn(bad, out)
		for good in ("제목", "링크", "둘", "할 일", "<u>인용</u>", "출처"):
			self.assertIn(good, out)


class UrlPreviewSsrfTests(TestCase):
	def setUp(self):
		self.user = get_user_model().objects.create_user(username="previewer", password="pw-for-tests-only")
		self.url = reverse("blog:url_preview")

	def test_requires_login(self):
		self.assertEqual(self.client.get(self.url, {"url": "https://example.com/"}).status_code, 302)

	def test_blocks_internal_targets_without_fetching(self):
		from blog import views
		self.client.force_login(self.user)
		with mock.patch.object(views._requests, "get") as fake_get:
			for bad in (
				"http://127.0.0.1/", "http://localhost:8000/", "http://[::1]/", "http://169.254.169.254/latest/meta-data/",
				"http://10.0.0.5/", "http://192.168.1.1/", "http://0.0.0.0/", "file:///etc/passwd", "ftp://example.com/",
				"http://user:pw@example.com/", "http://[::ffff:127.0.0.1]/",
			):
				res = self.client.get(self.url, {"url": bad})
				self.assertEqual(res.status_code, 400, bad)
				self.assertEqual(res.json()["error"], "미리보기를 만들 수 없는 주소예요")
		fake_get.assert_not_called()

	def test_hostname_resolving_to_private_ip_is_blocked(self):
		from blog import views
		self.client.force_login(self.user)
		with mock.patch("blog.views.socket.getaddrinfo", return_value=[(2, 1, 6, "", ("10.1.2.3", 80))]), \
				mock.patch.object(views._requests, "get") as fake_get:
			res = self.client.get(self.url, {"url": "http://internal.example.com/"})
		self.assertEqual(res.status_code, 400)
		fake_get.assert_not_called()

	def test_redirect_to_internal_is_blocked_and_errors_are_generic(self):
		from blog import views
		self.client.force_login(self.user)
		redirect = mock.Mock(is_redirect=True, is_permanent_redirect=False, headers={"Location": "http://127.0.0.1:8000/admin/"})
		with mock.patch("blog.views.socket.getaddrinfo", return_value=[(2, 1, 6, "", ("93.184.216.34", 80))]), \
				mock.patch.object(views._requests, "get", return_value=redirect) as fake_get:
			res = self.client.get(self.url, {"url": "http://example.com/"})
		self.assertEqual(res.status_code, 400)
		self.assertEqual(fake_get.call_count, 1)
		self.assertFalse(fake_get.call_args.kwargs["allow_redirects"])
		# 예외 내용이 응답으로 새지 않음
		with mock.patch("blog.views.socket.getaddrinfo", return_value=[(2, 1, 6, "", ("93.184.216.34", 80))]), \
				mock.patch.object(views._requests, "get", side_effect=RuntimeError("secret internals")):
			res = self.client.get(self.url, {"url": "http://example.com/"})
		self.assertEqual(res.status_code, 400)
		self.assertNotIn("secret", res.content.decode())

	def test_public_page_metadata_is_parsed_with_byte_cap(self):
		from blog import views
		self.client.force_login(self.user)
		body = "<html><head><title>T</title><meta property='og:title' content='OG 제목'><meta name='description' content='설명'></head><body>".encode() + b"x" * (views.PREVIEW_MAX_BYTES * 2)
		ok = mock.Mock(is_redirect=False, is_permanent_redirect=False, status_code=200, encoding="utf-8",
			headers={"Content-Type": "text/html; charset=utf-8"})
		ok.iter_content = lambda n: (body[i:i + n] for i in range(0, len(body), n))
		with mock.patch("blog.views.socket.getaddrinfo", return_value=[(2, 1, 6, "", ("93.184.216.34", 443))]), \
				mock.patch.object(views._requests, "get", return_value=ok):
			res = self.client.get(self.url, {"url": "https://example.com/a"})
		self.assertEqual(res.status_code, 200)
		data = res.json()
		self.assertEqual(data["title"], "OG 제목")
		self.assertEqual(data["description"], "설명")
		self.assertEqual(data["site_name"], "example.com")


class MemberCategoryTests(TestCase):
	"""일반 회원은 Free(자유게시판)에만, 관리자는 모든 카테고리에 글을 씀"""

	def setUp(self):
		self.member = get_user_model().objects.create_user(username="member", password="pw-for-tests-only")
		self.admin = get_user_model().objects.create_superuser(username="boss", password="pw-for-tests-only", email="b@x.kr")

	def _post(self, category):
		return self.client.post(reverse("blog:post_create"), {
			"title": f"{category} 글", "category": category, "content": "본문", "submit_action": "publish",
		})

	def test_member_only_board(self):
		self.client.force_login(self.member)
		for cat in ("tech", "life", "secret"):
			self._post(cat)
			self.assertFalse(Post.objects.filter(category=cat).exists(), cat)
		self._post("board")
		self.assertTrue(Post.objects.filter(category="board", author=self.member).exists())

	def test_member_form_shows_only_board(self):
		self.client.force_login(self.member)
		res = self.client.get(reverse("blog:post_create"))
		self.assertEqual(res.context["categories"], [("board", "Free")])

	def test_member_cannot_move_post_to_other_category(self):
		self.client.force_login(self.member)
		self._post("board")
		post = Post.objects.get(author=self.member)
		self.client.post(reverse("blog:post_edit", args=[post.slug]), {
			"title": post.title, "category": "tech", "content": "본문", "submit_action": "publish",
		})
		post.refresh_from_db()
		self.assertEqual(post.category, "board")

	def test_admin_all_categories(self):
		self.client.force_login(self.admin)
		for cat in ("tech", "board", "life", "secret"):
			self._post(cat)
			self.assertTrue(Post.objects.filter(category=cat).exists(), cat)


class WeeklyRecordTests(TestCase):
	"""블로그 허브 이번 주 기록: 관리자 글만, 월요일 시작 주, 목표, 연속 기록, Secret 은 관리자에게만"""

	def setUp(self):
		from django.utils import timezone
		self.tz = timezone
		self.admin = get_user_model().objects.create_superuser("owner", "o@x.kr", "pw-for-tests-only")
		self.member = get_user_model().objects.create_user("m", "m@x.kr", "pw-for-tests-only")
		self.today = timezone.localdate()

	def tearDown(self):
		from django.core.cache import cache
		from studio import site_settings
		cache.delete(site_settings.CACHE_KEY)  # 개발 서버와 같은 파일 캐시를 쓰므로 테스트 값이 남지 않게

	def _post(self, days_ago, category="tech", author=None, published=True):
		from datetime import datetime, time, timedelta
		day = self.today - timedelta(days=days_ago)
		at = self.tz.make_aware(datetime.combine(day, time(12)))
		return Post.objects.create(
			title=f"t{Post.objects.count()}", slug=f"s{Post.objects.count()}", category=category, content="x",
			author=author or self.admin, is_published=published, published_at=at,
		)

	def test_counts_streak_and_goals(self):
		from blog.weekly import weekly_stats
		monday_offset = self.today.weekday()
		self._post(0, "tech")
		self._post(0, "life")
		self._post(monday_offset + 1, "tech")        # 지난주 (일요일)
		self._post(monday_offset + 8, "tech")        # 2주 전
		self._post(0, "board", author=self.member)   # 회원 글은 안 셈
		self._post(0, "secret")
		self._post(0, "tech", published=False)       # 초안은 안 셈
		w = weekly_stats({"tech": 1, "life": 2, "board": 0, "secret": 0})
		self.assertEqual(w["total"], 2)
		self.assertEqual(w["goal_total"], 3)
		self.assertEqual({r["key"]: (r["count"], r["goal"]) for r in w["rows"]}, {"tech": (1, 1), "life": (1, 2)})
		self.assertEqual(w["streak"], 3)
		self.assertEqual(len(w["bars"]), 26)
		self.assertTrue(w["bars"][-1]["current"])
		self.assertEqual(w["bars"][-1]["count"], 2)
		admin_view = weekly_stats({"tech": 1}, include_secret=True)
		self.assertEqual(admin_view["total"], 3)
		self.assertIn("secret", [r["key"] for r in admin_view["rows"]])

	def test_streak_continues_from_last_week_when_this_week_empty(self):
		from blog.weekly import weekly_stats
		monday_offset = self.today.weekday()
		self._post(monday_offset + 1)
		self._post(monday_offset + 8)
		self.assertEqual(weekly_stats({})["streak"], 2)
		self.assertEqual(weekly_stats({})["total"], 0)

	def test_hub_shows_card_and_studio_saves_goals(self):
		self._post(0, "tech")
		res = self.client.get(reverse("blog:index"))
		self.assertContains(res, "이번 주 기록")
		self.assertContains(res, "최근 26주")
		self.client.force_login(self.admin)
		page = self.client.get(reverse("studio:settings"))
		self.assertContains(page, "블로그 주간 목표")
		data = {"blog_goal_tech": "3", "blog_goal_board": "0", "blog_goal_life": "99", "blog_goal_secret": "x"}
		for item in page.context["nav_items"]:
			data.setdefault("nav_order", [])
			data["nav_order"].append(item["key"])
			data[f"nav_state_{item['key']}"] = item["state"]
			data[f"nav_label_{item['key']}"] = item["label"]
		data["home_order"] = [s["key"] for s in page.context["home_sections"]]
		self.client.post(reverse("studio:settings"), data)
		from studio import site_settings
		goals = site_settings.load()["blog_goals"]
		self.assertEqual(goals["tech"], 3)
		self.assertEqual(goals["life"], site_settings.BLOG_GOAL_MAX)
		self.assertEqual(goals["secret"], 0)


class PostIndexMarkupTests(TestCase):
	"""글 보기의 왼쪽 번호 목차 틀 (목차 내용은 브라우저 스크립트가 제목을 모아 채움)"""

	def test_index_aside_and_mobile_toc_present(self):
		from django.utils import timezone
		admin = get_user_model().objects.create_superuser("idx", "i@x.kr", "pw-for-tests-only")
		post = Post.objects.create(title="목차 글", slug="toc-post", category="tech", content=tiptap(
			{"type": "heading", "attrs": {"level": 2}, "content": [{"type": "text", "text": "하나"}]},
			{"type": "heading", "attrs": {"level": 2}, "content": [{"type": "text", "text": "둘"}]},
		), author=admin, is_published=True, published_at=timezone.now())
		res = self.client.get(reverse("blog:post_detail", args=[post.slug]))
		self.assertContains(res, 'id="post-layout"')
		self.assertContains(res, 'class="post-index"')
		self.assertContains(res, 'id="post-toc-mobile"')
		self.assertNotContains(res, "post-toc-bars")
		self.assertNotContains(res, "{#")


class CollectionCardsTests(TestCase):
	"""블로그 허브 컬렉션 카드: 카테고리·시리즈, Secret 은 관리자에게만, 검색어와 무관한 전체 개수"""

	def setUp(self):
		from django.utils import timezone
		from blog.models import Series
		self.admin = get_user_model().objects.create_superuser("col", "c@x.kr", "pw-for-tests-only")
		self.series = Series.objects.create(name="HackRF 입문", slug="hackrf", author=self.admin)
		now = timezone.now()
		for i, cat in enumerate(["tech", "tech", "life", "secret"]):
			Post.objects.create(title=f"{cat} 글 {i}", slug=f"c{i}", category=cat, content="x", author=self.admin,
				is_published=True, published_at=now, series=self.series if i < 2 else None, series_order=i + 1 if i < 2 else None)
		Post.objects.create(title="초안", slug="draft", category="tech", content="x", author=self.admin, is_published=False)

	def test_cards_for_visitor_and_admin(self):
		res = self.client.get(reverse("blog:index"), {"q": "없는검색어"})
		cards = {c["title"]: c for c in res.context["collections"]}
		self.assertEqual(cards["Tech"]["count"], 2)   # 검색어와 상관없이 전체
		self.assertEqual(cards["Life"]["count"], 1)
		self.assertNotIn("Secret", cards)
		self.assertEqual(cards["HackRF 입문"]["count"], 2)
		self.assertEqual(cards["HackRF 입문"]["kind"], "series")
		self.assertEqual(len(cards["Tech"]["recent"]), 2)
		self.assertContains(res, "컬렉션")
		self.assertNotContains(res, "초안")
		self.client.force_login(self.admin)
		cards = {c["title"]: c for c in self.client.get(reverse("blog:index")).context["collections"]}
		self.assertEqual(cards["Secret"]["count"], 1)
