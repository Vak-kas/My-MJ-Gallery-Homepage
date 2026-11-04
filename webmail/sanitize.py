"""받은 HTML 메일을 안전하게 보여 주기 위한 정화기.

허용한 태그·속성만 남기고 스크립트·폼·iframe 등은 내용까지 버린다. 링크는 http(s)·mailto 만,
그림은 http(s)·data:image·cid: 만. 그림은 기본으로 안 불러오게 src → data-src 로 바꾼다(추적 방지).
정화한 결과는 sandbox iframe(스크립트 금지) 안에서 CSP 와 함께 보여 준다 — 이중 안전장치.
"""

import html
import re
from html.parser import HTMLParser

ALLOWED_TAGS = {
	"a", "p", "br", "div", "span", "b", "strong", "i", "em", "u", "s", "strike", "del", "ins", "ul", "ol", "li",
	"h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "pre", "code", "table", "thead", "tbody", "tfoot", "tr", "td", "th",
	"img", "hr", "font", "center", "small", "sub", "sup", "caption", "col", "colgroup", "section", "article", "header",
	"footer", "main", "nav", "figure", "figcaption", "label", "dl", "dt", "dd", "abbr", "cite", "q", "mark", "wbr",
}
VOID_TAGS = {"br", "img", "hr", "col", "wbr"}
# 이 태그는 안쪽 내용까지 통째로 버림
DROP_WITH_CONTENT = {"script", "style", "head", "title", "iframe", "object", "embed", "svg", "math", "form", "noscript",
                     "template", "textarea", "select", "button", "input", "video", "audio", "applet", "frame", "frameset", "link", "meta", "base"}
# 짝 없이 혼자 쓰는 버릴 태그 (깊이 셈에서 제외)
DROP_VOID = {"input", "link", "meta", "base", "embed", "frame", "source", "track", "param"}
ALLOWED_ATTRS = {
	"href", "src", "alt", "title", "width", "height", "style", "colspan", "rowspan", "align", "valign", "bgcolor", "color",
	"border", "cellpadding", "cellspacing", "size", "face", "dir", "lang", "class", "id", "span",
}
_URL_OK = re.compile(r"^(https?:|mailto:)", re.I)
_IMG_OK = re.compile(r"^(https?:|cid:|data:image/)", re.I)
_STYLE_BAD = re.compile(r"(expression\s*\(|javascript:|url\s*\(|@import|behavior\s*:|-moz-binding)", re.I)


class _Cleaner(HTMLParser):
	def __init__(self, show_images):
		super().__init__(convert_charrefs=True)
		self.out = []
		self.skip = 0  # DROP_WITH_CONTENT 안에 있는 깊이
		self.show_images = show_images

	def handle_starttag(self, tag, attrs):
		tag = tag.lower()
		if tag in DROP_WITH_CONTENT or tag in DROP_VOID:
			if tag not in DROP_VOID:
				self.skip += 1
			return
		if self.skip:
			return
		if tag not in ALLOWED_TAGS:
			return  # 모르는 태그는 껍데기만 버리고 내용은 둠
		cleaned = []
		for name, value in attrs:
			name = name.lower()
			value = value or ""
			if name.startswith("on") or name not in ALLOWED_ATTRS:
				continue
			if name == "href":
				if not _URL_OK.match(value.strip()):
					continue
			elif name == "src":
				if tag != "img" or not _IMG_OK.match(value.strip()):
					continue
				if not self.show_images and not value.strip().lower().startswith(("cid:", "data:")):
					name = "data-src"
			elif name == "style":
				if _STYLE_BAD.search(value):
					continue
			cleaned.append(f' {name}="{html.escape(value, quote=True)}"')
		if tag == "a":
			cleaned.append(' target="_blank" rel="noopener noreferrer nofollow"')
		self.out.append(f"<{tag}{''.join(cleaned)}>")

	def handle_startendtag(self, tag, attrs):
		self.handle_starttag(tag, attrs)

	def handle_endtag(self, tag):
		tag = tag.lower()
		if tag in DROP_WITH_CONTENT and tag not in DROP_VOID:
			self.skip = max(0, self.skip - 1)
			return
		if self.skip:
			return
		if tag in ALLOWED_TAGS and tag not in VOID_TAGS:
			self.out.append(f"</{tag}>")

	def handle_data(self, data):
		if not self.skip:
			self.out.append(html.escape(data, quote=False))

	def handle_entityref(self, name):
		if not self.skip:
			self.out.append(f"&{name};")

	def handle_charref(self, name):
		if not self.skip:
			self.out.append(f"&#{name};")

	def handle_comment(self, data):
		pass


def sanitize_html(source: str, show_images=False) -> str:
	cleaner = _Cleaner(show_images)
	cleaner.feed(source or "")
	cleaner.close()
	return "".join(cleaner.out)


_LINK_RE = re.compile(r"(https?://[^\s<>\"']+)")


def text_to_html(text: str) -> str:
	"""글자 메일 → 링크만 살린 HTML."""
	escaped = html.escape(text or "", quote=False)
	linked = _LINK_RE.sub(r'<a href="\1" target="_blank" rel="noopener noreferrer nofollow">\1</a>', escaped)
	return f'<div style="white-space:pre-wrap;word-break:break-word">{linked}</div>'
