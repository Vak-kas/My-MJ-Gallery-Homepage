"""블로그 본문(content) 해석·렌더링.

본문은 두 형식이 섞여 있다.
- 새 형식(Tiptap): {"format": "tiptap", "version": 1, "doc": <ProseMirror JSON>}
- 예전 형식(Editor.js): {"blocks": [...]}  → blog_extras 의 기존 렌더러가 처리

Tiptap 문서는 브라우저가 만든 HTML 을 믿지 않고 JSON 에서 직접 HTML 을 만든다.
텍스트는 전부 escape 하고, 링크/이미지 주소와 인라인 스타일 값은 허용 목록으로만 통과시킨다.
"""

import json
import re

from django.utils.html import escape

TIPTAP_FORMAT = "tiptap"

_SAFE_URL_RE = re.compile(r"^(https?://|mailto:|/(?!/)|#)", re.I)
_COLOR_RE = re.compile(r"^(#[0-9a-fA-F]{3,8}|rgba?\(\s*[\d.\s,%]+\))$")
_FONT_RE = re.compile(r"^[\w\s,'\"-]{1,120}$")


def parse_content(content):
	"""("tiptap", doc) / ("editorjs", data) / ("raw", str) 중 하나를 돌려준다."""
	if not content:
		return "raw", ""
	try:
		data = json.loads(content)
	except (json.JSONDecodeError, TypeError, ValueError):
		return "raw", content
	if isinstance(data, dict) and data.get("format") == TIPTAP_FORMAT and isinstance(data.get("doc"), dict):
		return TIPTAP_FORMAT, data["doc"]
	if isinstance(data, dict):
		return "editorjs", data
	return "raw", content


def safe_url(value):
	url = str(value or "").strip()
	return url if _SAFE_URL_RE.match(url) else ""


def _attrs(node):
	attrs = node.get("attrs")
	return attrs if isinstance(attrs, dict) else {}


def _children(node):
	content = node.get("content")
	return content if isinstance(content, list) else []


# ── 링크 카드 (예전 렌더러와 같은 마크업) ─────────────────────────────

def render_linkcard(url, title="", description="", image="", site_name="", favicon="", mode="card"):
	url = safe_url(url)
	if not url:
		return ""
	url_e = escape(url)
	title_e = escape(title or url)
	desc_e = escape(description or "")
	image_e = escape(safe_url(image))
	site_e = escape(site_name or "")
	favicon_e = escape(safe_url(favicon))

	fav_html = f'<img src="{favicon_e}" alt="" class="h-4 w-4 rounded" onerror="this.style.display=\'none\'" />' if favicon_e else ""
	desc_html = f'<p class="mt-1 line-clamp-2 text-[13px] leading-relaxed text-[#6e6e73]">{desc_e}</p>' if desc_e else ""

	if mode == "mention":
		return (
			f'<p class="my-2"><a href="{url_e}" target="_blank" rel="noopener noreferrer" '
			f'class="inline-flex items-center gap-1.5 rounded-full border border-[#e5e5ea] bg-[#f5f5f7] px-3 py-1.5 text-[13px] font-medium text-[#1d1d1f] no-underline hover:bg-[#eef3ff] hover:border-[#0066cc]/40">'
			f'🔗 {title_e}</a></p>'
		)
	if mode == "preview":
		cover_html = (
			f'<div class="w-full h-44 overflow-hidden bg-[#f5f5f7]">'
			f'<img src="{image_e}" alt="" class="h-full w-full object-cover" /></div>'
		) if image_e else ""
		return (
			f'<a href="{url_e}" target="_blank" rel="noopener noreferrer" '
			f'class="my-4 block overflow-hidden rounded-2xl border border-[#e5e5ea] bg-white no-underline transition hover:shadow-md">'
			f'{cover_html}'
			f'<div class="p-4">'
			f'<div class="flex items-center gap-2 text-[12px] text-[#8e8e93]">{fav_html}<span>{site_e}</span></div>'
			f'<p class="mt-2 text-[17px] font-bold text-[#1d1d1f]">{title_e}</p>'
			f'{desc_html}'
			f'<p class="mt-2 truncate text-[12px] text-[#0066cc]">{url_e}</p>'
			f'</div></a>'
		)
	img_html = f'<img src="{image_e}" alt="" class="absolute inset-0 h-full w-full object-cover" />' if image_e else ""
	return (
		f'<a href="{url_e}" target="_blank" rel="noopener noreferrer" '
		f'class="my-4 flex overflow-hidden rounded-2xl border border-[#e5e5ea] bg-white no-underline transition hover:shadow-md block">'
		f'<div class="flex-1 min-w-0 p-4">'
		f'<div class="flex items-center gap-2 text-[12px] text-[#8e8e93]">{fav_html}<span>{site_e}</span></div>'
		f'<p class="mt-1.5 truncate text-[15px] font-semibold text-[#1d1d1f]">{title_e}</p>'
		f'{desc_html}'
		f'<p class="mt-2 truncate text-[12px] text-[#0066cc]">{url_e}</p>'
		f'</div>'
		+ (f'<div class="relative h-auto w-[140px] shrink-0 overflow-hidden border-l border-[#e5e5ea] bg-[#f5f5f7]">{img_html}</div>' if image_e else "")
		+ '</a>'
	)


# ── Tiptap → HTML ───────────────────────────────────────────────

def _style_from_text_style(attrs):
	styles = []
	color = str(attrs.get("color") or "").strip()
	background = str(attrs.get("backgroundColor") or "").strip()
	font = str(attrs.get("fontFamily") or "").strip()
	if color and _COLOR_RE.match(color):
		styles.append(f"color:{color}")
	if background and _COLOR_RE.match(background):
		styles.append(f"background-color:{background}")
	if font and _FONT_RE.match(font):
		styles.append(f"font-family:{font}")
	return ";".join(styles)


def _apply_mark(html, mark):
	mark_type = mark.get("type")
	attrs = _attrs(mark)
	if mark_type == "bold":
		return f"<strong>{html}</strong>"
	if mark_type == "italic":
		return f"<em>{html}</em>"
	if mark_type == "underline":
		return f"<u>{html}</u>"
	if mark_type == "strike":
		return f"<s>{html}</s>"
	if mark_type == "code":
		return f'<code class="rounded bg-[#f2f2f7] px-1.5 py-0.5 font-mono text-[0.88em] text-[#eb5757]">{html}</code>'
	if mark_type == "link":
		href = safe_url(attrs.get("href"))
		if not href:
			return html
		return f'<a href="{escape(href)}" target="_blank" rel="noopener noreferrer" class="text-[#0066cc] underline underline-offset-2">{html}</a>'
	if mark_type in {"textStyle", "highlight"}:
		if mark_type == "highlight":
			attrs = {"backgroundColor": attrs.get("color") or "#fbf3db"}
		style = _style_from_text_style(attrs)
		return f'<span style="{escape(style)}" class="rounded-[3px]">{html}</span>' if style else html
	return html


def _render_inline(nodes):
	parts = []
	for node in nodes:
		node_type = node.get("type")
		if node_type == "text":
			html = escape(node.get("text", ""))
			marks = node.get("marks") if isinstance(node.get("marks"), list) else []
			# code 마크는 가장 안쪽, link 는 가장 바깥에 오도록 정렬
			order = {"code": 0, "link": 9}
			for mark in sorted(marks, key=lambda m: order.get(m.get("type"), 5)):
				html = _apply_mark(html, mark)
			parts.append(html)
		elif node_type == "hardBreak":
			parts.append("<br />")
		elif node_type == "inlineMath":
			latex = escape(str(_attrs(node).get("latex") or "").strip())
			if latex:
				parts.append(f'<span class="mj-katex" data-latex="{latex}" data-display="0">{latex}</span>')
	return "".join(parts)


_HEADING_CLASSES = {
	1: "text-[2rem] font-bold mt-10 mb-4 tracking-tight",
	2: "text-[1.5rem] font-semibold mt-8 mb-3 tracking-tight",
	3: "text-[1.25rem] font-semibold mt-6 mb-2",
}


def _render_blocks(nodes, tight=False):
	return "".join(_render_block(node, tight) for node in nodes)


# ── 구분선 모양 (에디터 frontend/editor/src/extensions/divider.js 와 같은 id) ──

_DIV_SIDE_L = '<span class="h-px flex-1 bg-gradient-to-r from-transparent to-[#b4b4b8]"></span>'
_DIV_SIDE_R = '<span class="h-px flex-1 bg-gradient-to-l from-transparent to-[#b4b4b8]"></span>'
_DIV_WAVE = (
	"url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='24' height='8' viewBox='0 0 24 8'%3E"
	"%3Cpath d='M0 4c3-4 6-4 9 0s6 4 9 0' fill='none' stroke='%238e8e93' stroke-width='1.2'/%3E%3C/svg%3E\")"
)
DIVIDER_STYLES = {
	"line": '<hr class="w-full border-t border-[#d2d2d7]" />',
	"circle": f'{_DIV_SIDE_L}<span class="h-2 w-2 rounded-full bg-[#1d1d1f]"></span>{_DIV_SIDE_R}',
	"diamond": f'{_DIV_SIDE_L}<span class="h-2 w-2 rotate-45 bg-[#1d1d1f]"></span>{_DIV_SIDE_R}',
	"star": f'{_DIV_SIDE_L}<span class="text-[14px] leading-none text-[#1d1d1f]">✦</span>{_DIV_SIDE_R}',
	"dots": '<span class="text-[13px] leading-none tracking-[0.6em] text-[#8e8e93]">•••</span>',
	"asterism": '<span class="text-[22px] leading-none text-[#1d1d1f]">⁂</span>',
	"fade": '<span class="h-px w-full bg-gradient-to-r from-transparent via-[#8e8e93] to-transparent"></span>',
	"double": '<hr class="w-full border-t-[3px] border-double border-[#b4b4b8]" />',
	"dashed": '<hr class="w-full border-t border-dashed border-[#a1a1a6]" />',
	"wave": f'<span class="h-2 w-full bg-repeat-x" style="background-image:{_DIV_WAVE};background-size:18px 8px"></span>',
}


def render_divider(style):
	"""구분선 HTML. 모르는 모양은 기본 선."""
	inner = DIVIDER_STYLES.get(str(style or "line"), DIVIDER_STYLES["line"])
	return f'<div class="my-10 flex items-center justify-center gap-4" data-divider="{escape(str(style or "line"))}">{inner}</div>'


# ── 콜아웃 (에디터 frontend/editor/src/extensions/callout.js 와 같은 id·색) ──
CALLOUT_KINDS = {
	"info": ("ℹ️", "bg-[#eef5ff] border-[#b9d4ff]", "text-[#1d4f91]"),
	"tip": ("💡", "bg-[#edf9ef] border-[#a9dfb3]", "text-[#1f6b33]"),
	"warn": ("⚠️", "bg-[#fff8e6] border-[#f2d58a]", "text-[#8a5a00]"),
	"danger": ("🚫", "bg-[#fdeeee] border-[#f3b3b3]", "text-[#9b2222]"),
	"note": ("📝", "bg-[#f4f4f6] border-[#d7d7dc]", "text-[#3a3a3f]"),
}


def render_callout(kind, icon, title_html, body_html, aside_html=""):
	"""콜아웃 HTML. 모르는 종류는 info, 아이콘은 4글자까지(이모지 하나). aside 는 오른쪽 칸(수식·표 등)."""
	kind = str(kind or "info")
	if kind not in CALLOUT_KINDS:
		kind = "info"
	default_icon, box_cls, title_cls = CALLOUT_KINDS[kind]
	icon = escape(str(icon or "").strip()[:4] or default_icon)
	title = f'<p class="mb-1 font-bold leading-snug {title_cls}">{title_html}</p>' if title_html else ""
	border_cls = box_cls.split()[-1]
	body = f'<div class="min-w-0 flex-1 [&>*:last-child]:mb-0">{body_html}</div>'
	if aside_html:
		body = (
			f'<div class="sm:flex sm:items-center sm:gap-4">{body}'
			f'<div class="mt-3 sm:mt-0 sm:max-w-[45%] sm:min-w-[150px] rounded-lg border bg-white/60 px-4 py-2.5 {border_cls} '
			f'[&>*:last-child]:mb-0 [&>*]:my-0" data-callout-aside>{aside_html}</div></div>'
		)
	return (
		f'<div class="my-6 flex items-start gap-3 rounded-xl border px-4 py-3.5 {box_cls}" data-callout="{kind}">'
		f'<span class="flex h-7 w-7 flex-shrink-0 items-center justify-center text-[18px] leading-none" aria-hidden="true">{icon}</span>'
		f'<div class="min-w-0 flex-1 leading-[1.8]">{title}{body}</div></div>'
	)


def _table_colgroup(rows):
	"""첫 행의 셀 colwidth(에디터에서 끌어서 정한 열 너비) → <colgroup>. 너비가 하나도 없으면 빈 문자열."""
	first = next((r for r in rows if r.get("type") == "tableRow"), None)
	if not first:
		return "", 0
	widths = []
	for cell in _children(first):
		raw = _attrs(cell).get("colwidth") or []
		try:
			span = max(1, int(_attrs(cell).get("colspan") or 1))
		except (TypeError, ValueError):
			span = 1
		for i in range(span):
			try:
				value = int(raw[i]) if isinstance(raw, list) and i < len(raw) and raw[i] else 0
			except (TypeError, ValueError):
				value = 0
			widths.append(max(0, min(value, 4000)))
	if not any(widths):
		return "", 0
	cols = "".join(f'<col style="width:{w}px">' if w else "<col>" for w in widths)
	return f"<colgroup>{cols}</colgroup>", sum(widths)


_ALIGN_CLASSES = {"center": " text-center", "right": " text-right", "justify": " text-justify"}


def _align_cls(attrs):
	"""에디터 정렬(textAlign) → Tailwind 클래스. 왼쪽/모르는 값은 빈 문자열."""
	return _ALIGN_CLASSES.get(str(attrs.get("textAlign") or ""), "")


def _render_block(node, tight=False):
	node_type = node.get("type")
	attrs = _attrs(node)
	children = _children(node)

	if node_type == "paragraph":
		inner = _render_inline(children) or "<br />"
		cls = "leading-[1.85]" if tight else "mb-4 leading-[1.85]"
		return f'<p class="{cls}{_align_cls(attrs)}">{inner}</p>'

	if node_type == "heading":
		try:
			level = max(1, min(3, int(attrs.get("level") or 2)))
		except (TypeError, ValueError):
			level = 2
		return f'<h{level} class="{_HEADING_CLASSES[level]}{_align_cls(attrs)}">{_render_inline(children)}</h{level}>'

	if node_type in {"bulletList", "orderedList"}:
		tag = "ol" if node_type == "orderedList" else "ul"
		list_cls = "list-decimal" if tag == "ol" else "list-disc"
		spacing = "mt-1" if tight else "mb-4"
		start = ""
		if tag == "ol":
			try:
				start_num = int(attrs.get("start") or 1)
			except (TypeError, ValueError):
				start_num = 1
			if start_num != 1:
				start = f' start="{start_num}"'
		return f'<{tag}{start} class="{list_cls} pl-6 {spacing} space-y-0.5">{_render_blocks(children)}</{tag}>'

	if node_type == "listItem":
		return f"<li>{_render_blocks(children, tight=True)}</li>"

	if node_type == "taskList":
		spacing = "mt-1" if tight else "mb-4"
		return f'<ul class="{spacing} space-y-1">{_render_blocks(children)}</ul>'

	if node_type == "taskItem":
		checked = bool(attrs.get("checked"))
		checked_attr = " checked" if checked else ""
		done = " line-through text-[#aeaeb2]" if checked else ""
		return (
			f'<li class="flex items-start gap-2">'
			f'<input type="checkbox" disabled{checked_attr} class="mt-[0.5em] h-4 w-4 flex-shrink-0 accent-[#0066cc]" />'
			f'<div class="min-w-0 flex-1{done}">{_render_blocks(children, tight=True)}</div></li>'
		)

	if node_type == "blockquote":
		return (
			f'<blockquote class="border-l-4 border-[#d2d2d7] pl-5 py-1 text-[#6e6e73] my-5 space-y-1">'
			f'{_render_blocks(children, tight=True)}</blockquote>'
		)

	if node_type == "codeBlock":
		code = "".join(child.get("text", "") for child in children if child.get("type") == "text")
		language = re.sub(r"[^\w+-]", "", str(attrs.get("language") or ""))
		lang_attr = f' data-language="{language}"' if language else ""
		return (
			f'<pre class="bg-[#f2f2f7] rounded-xl p-4 mb-4 overflow-x-auto text-[0.85rem] '
			f'font-mono leading-relaxed text-[#1d1d1f]"{lang_attr}><code>{escape(code)}</code></pre>'
		)

	if node_type == "horizontalRule":
		return render_divider(attrs.get("style"))

	if node_type == "image":
		src = safe_url(attrs.get("src"))
		if not src:
			return ""
		caption = str(attrs.get("caption") or "")
		alt = str(attrs.get("alt") or caption)
		caption_html = f'<figcaption class="px-4 py-3 text-sm text-[#8e8e93]">{escape(caption)}</figcaption>' if caption else ""
		return (
			f'<figure class="my-5 overflow-hidden rounded-2xl border border-[#e5e5ea] bg-white">'
			f'<img src="{escape(src)}" alt="{escape(alt)}" loading="lazy" class="block w-full h-auto object-contain" />'
			f'{caption_html}</figure>'
		)

	if node_type == "table":
		colgroup, min_width = _table_colgroup(children)
		style = f' style="min-width:{min_width}px"' if min_width else ""
		return (
			f'<div class="overflow-x-auto mb-4"><table class="w-full border-collapse"{style}>'
			f'{colgroup}{_render_blocks(children)}</table></div>'
		)

	if node_type == "tableRow":
		return f"<tr>{_render_blocks(children)}</tr>"

	if node_type in {"tableCell", "tableHeader"}:
		tag = "th" if node_type == "tableHeader" else "td"
		span = ""
		for key in ("colspan", "rowspan"):
			try:
				value = int(attrs.get(key) or 1)
			except (TypeError, ValueError):
				value = 1
			if value > 1:
				span += f' {key}="{value}"'
		cls = "border border-[#e5e5ea] px-3 py-2 text-sm align-top"
		if tag == "th":
			cls += " bg-[#f9f9fb] font-semibold text-left"
		return f'<{tag}{span} class="{cls}">{_render_blocks(children, tight=True)}</{tag}>'

	if node_type == "details":
		summary = next((c for c in children if c.get("type") == "detailsSummary"), None)
		body = next((c for c in children if c.get("type") == "detailsContent"), None)
		open_attr = " open" if attrs.get("open") else ""
		return (
			f'<details class="mb-3 border border-[#e5e5ea] rounded-xl group"{open_attr}>'
			f'<summary class="cursor-pointer select-none px-4 py-3 font-medium '
			f'hover:bg-[#f9f9fb] rounded-xl list-none flex items-center gap-2">'
			f'<span class="transition-transform group-open:rotate-90 text-[#aeaeb2]">▶</span>'
			f'<span>{_render_inline(_children(summary or {}))}</span></summary>'
			f'<div class="px-4 pb-4 pt-2 leading-relaxed">{_render_blocks(_children(body or {}))}</div>'
			f'</details>'
		)

	if node_type == "callout":
		title = next((c for c in children if c.get("type") == "calloutTitle"), None)
		body = next((c for c in children if c.get("type") == "calloutBody"), None)
		aside = next((c for c in children if c.get("type") == "calloutAside"), None)
		return render_callout(
			attrs.get("kind"),
			attrs.get("icon"),
			_render_inline(_children(title or {})),
			_render_blocks(_children(body or {}), tight=True),
			_render_blocks(_children(aside or {}), tight=True) if aside else "",
		)

	if node_type == "blockMath":
		latex = escape(str(attrs.get("latex") or "").strip())
		if not latex:
			return ""
		return (
			f'<div class="my-4 overflow-x-auto rounded-xl border border-[#e5e5ea] bg-[#fafafa] px-4 py-3{_align_cls(attrs)}">'
			f'<span class="mj-katex" data-latex="{latex}" data-display="1">{latex}</span></div>'
		)

	if node_type == "linkCard":
		return render_linkcard(
			attrs.get("url"),
			title=attrs.get("title") or "",
			description=attrs.get("description") or "",
			image=attrs.get("image") or "",
			site_name=attrs.get("siteName") or "",
			favicon=attrs.get("favicon") or "",
			mode=attrs.get("mode") or "card",
		)

	# 알 수 없는 블록이라도 안의 내용은 살림
	if children:
		return _render_blocks(children, tight)
	return ""


def render_tiptap_html(doc):
	return _render_blocks(_children(doc))


# ── 요약 / 대표이미지 ────────────────────────────────────────────

def tiptap_plain_text(doc):
	chunks = []

	def walk(node):
		node_type = node.get("type")
		if node_type == "text":
			chunks.append(node.get("text", ""))
			return
		if node_type in {"inlineMath", "blockMath"}:
			chunks.append(str(_attrs(node).get("latex") or ""))
		for child in _children(node):
			walk(child)
		if node_type not in {"text", "inlineMath", "hardBreak"}:
			chunks.append(" ")

	walk(doc)
	return re.sub(r"\s+", " ", "".join(chunks)).strip()


def tiptap_cover_image(doc):
	first = ""
	stack = list(reversed(_children(doc)))
	while stack:
		node = stack.pop()
		if node.get("type") == "image":
			src = safe_url(_attrs(node).get("src"))
			if src:
				if _attrs(node).get("isCover"):
					return src
				first = first or src
		stack.extend(reversed(_children(node)))
	return first
