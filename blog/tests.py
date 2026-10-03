import json

from django.test import SimpleTestCase

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
