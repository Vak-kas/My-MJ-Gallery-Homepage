"""논문 찾기 2단계 — 원문을 섹션별로 나눠 보기 (서론·관련 연구·기여·시스템 모델·…).

원문 출처:
- arXiv HTML (arxiv.org/html/<번호>): LaTeX 를 변환한 HTML 이라 섹션·수식(LaTeX)·인용 번호·참고문헌이 깔끔하게 나뉨
- arXiv 번호가 없으면 제목으로 arXiv 에서 같은 논문을 찾아봄
- 그래도 없으면 사용자가 올린 PDF (PyMuPDF 로 글자만 뽑음, 저장하지 않음 — 수식은 깨질 수 있음)

화면에 줄 HTML 은 원문 HTML 을 그대로 쓰지 않고 글자·수식·인용만 골라 새로 만듦 (스크립트 등이 섞여 들어오지 않게).
"""

import difflib
import html
import re
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from html.parser import HTMLParser

from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.http import JsonResponse
from django.views.decorators.http import require_GET, require_POST

from .papers import UA, _count

CACHE_PAPER = 30 * 24 * 60 * 60
MAX_HTML = 15 * 1024 * 1024
MAX_PDF = 30 * 1024 * 1024
ARXIV_RE = re.compile(r"^(\d{4}\.\d{4,5}|[a-z\-]+(\.[A-Z]{2})?/\d{7})$", re.I)

KINDS = [
	("abstract", "초록", None),
	("introduction", "서론", r"introduction|motivation"),
	("related", "관련 연구", r"related work|literature|prior work|background|state of the art|existing work|overview of"),
	("system", "시스템 모델", r"system model|network model|signal model|channel model|system description|scenario|preliminar|transmission model|threat model|jamming model|\bmodel(l)?ing\b"),
	("problem", "문제 정의", r"problem formulation|problem statement|optimization problem|formulation"),
	("proposed", "제안 기법", r"proposed|algorithm|scheme|framework|design|approach|method|solution|strategy|architecture"),
	("analysis", "성능 분석", r"analysis|theoretical|outage|secrecy|capacity|ergodic|bound"),
	("simulation", "시뮬레이션·결과", r"simulation|numerical|performance evaluation|experiment|results|evaluation"),
	("conclusion", "결론", r"conclusion|concluding|summary|future work"),
]
ROLE_RULES = [
	("organization", "구성 안내", r"(rest|remainder) of (this|the) (paper|article)|organized as follows|is organized|structured as follows"),
	("this", "이 논문이 한 일", r"\b(in this (paper|work|article|letter)|this (paper|work|article|letter) (proposes|presents|investigates|studies)|we propose|we investigate|we develop|we study|our (main )?contributions|main contributions|summarized as follows)\b"),
	("gap", "한계·문제 제기", r"\b(however|nevertheless|nonetheless|remains? (an )?open|has not been|have not been|few (works|studies)|overlooked|limited|lack of|challenging|unexplored|neglect)\b"),
]
CONTRIB_RE = re.compile(r"contribution|summarized as follows|summarize .* as follows|in this (paper|work|article)", re.I)


class SectionError(Exception):
	def __init__(self, message, status=400):
		super().__init__(message)
		self.status = status


# ── 작은 HTML 트리 ──

VOID = {"br", "img", "hr", "input", "meta", "link", "col", "source", "wbr", "area", "base", "embed", "param", "track"}


class Node:
	__slots__ = ("tag", "attrs", "children", "parent")

	def __init__(self, tag, attrs=None, parent=None):
		self.tag, self.attrs, self.children, self.parent = tag, dict(attrs or {}), [], parent

	@property
	def cls(self):
		return self.attrs.get("class") or ""

	def has(self, c):
		return c in self.cls.split()

	def find_all(self, pred):
		for ch in self.children:
			if isinstance(ch, Node):
				if pred(ch):
					yield ch
				yield from ch.find_all(pred)

	def find(self, pred):
		return next(self.find_all(pred), None)

	def text(self):
		out = []
		for ch in self.children:
			if isinstance(ch, str):
				out.append(ch)
			elif ch.tag == "math":
				out.append(ch.attrs.get("alttext") or "")
			elif ch.tag not in ("script", "style") and not ch.has("ltx_note"):
				out.append(ch.text())
		return "".join(out)


class _Builder(HTMLParser):
	def __init__(self):
		super().__init__(convert_charrefs=True)
		self.root = Node("root")
		self.cur = self.root

	def handle_starttag(self, tag, attrs):
		node = Node(tag, attrs, self.cur)
		self.cur.children.append(node)
		if tag not in VOID:
			self.cur = node

	def handle_startendtag(self, tag, attrs):
		self.cur.children.append(Node(tag, attrs, self.cur))

	def handle_endtag(self, tag):
		n = self.cur
		while n is not None and n.tag != tag:
			n = n.parent
		if n is not None and n.parent is not None:
			self.cur = n.parent

	def handle_data(self, data):
		self.cur.children.append(data)


def parse_tree(raw):
	b = _Builder()
	b.feed(raw)
	return b.root


# ── 안전한 HTML 로 다시 만들기 ──

def _clean_ws(s):
	return re.sub(r"\s+", " ", s)


def inline(node):
	"""문단 안: 글자·이탤릭·굵게·수식·인용만."""
	out = []
	for ch in node.children:
		if isinstance(ch, str):
			out.append(html.escape(_clean_ws(ch)))
			continue
		if ch.tag in ("script", "style") or ch.has("ltx_note") or ch.tag == "figure":
			continue
		if ch.tag == "math":
			tex = ch.attrs.get("alttext") or ""
			out.append(f'<span class="mj-katex" data-latex="{html.escape(tex)}"></span>')
		elif ch.tag == "cite" or ch.has("ltx_cite"):
			refs = []
			for a in ch.find_all(lambda n: n.tag == "a" and (n.attrs.get("href") or "").startswith("#bib.")):
				refs.append((a.attrs["href"][1:], _clean_ws(a.text()).strip()))
			if refs:
				label = ", ".join(r[1] for r in refs if r[1]) or "?"
				keys = " ".join(r[0] for r in refs)
				out.append(f'<span class="pp-cite" data-refs="{html.escape(keys)}">[{html.escape(label)}]</span>')
			else:
				out.append(html.escape(_clean_ws(ch.text())))
		elif ch.tag in ("em", "i") or "ltx_font_italic" in ch.cls:
			out.append(f"<i>{inline(ch)}</i>")
		elif ch.tag in ("strong", "b") or "ltx_font_bold" in ch.cls:
			out.append(f"<b>{inline(ch)}</b>")
		elif ch.tag == "br":
			out.append(" ")
		else:
			out.append(inline(ch))
	return "".join(out)


def _equation(table):
	rows = []
	for tr in table.find_all(lambda n: n.tag == "tr"):
		maths = [m.attrs.get("alttext") or "" for m in tr.find_all(lambda n: n.tag == "math")]
		no = tr.find(lambda n: n.has("ltx_eqn_eqno") or n.has("ltx_tag_equation"))
		if maths:
			rows.append((" ".join(maths), _clean_ws(no.text()).strip() if no else ""))
	return rows


def blocks_of(sec):
	"""섹션 안의 내용 블록 차례대로: p · eq · list · h · fig."""
	out = []

	def walk(node):
		for ch in node.children:
			if not isinstance(ch, Node):
				continue
			if ch.tag in ("h2", "h3", "h4", "h5", "h6") and node is not sec:
				out.append({"t": "h", "html": html.escape(_clean_ws(ch.text()).strip())})
			elif ch.has("ltx_para") or (ch.tag == "p" and ch.has("ltx_p")):
				before = len(out)
				walk(ch)
				if len(out) == before and ch.tag == "p":
					h = inline(ch).strip()
					if h:
						out.append({"t": "p", "html": h, "text": _clean_ws(ch.text()).strip()})
			elif ch.tag == "p":
				h = inline(ch).strip()
				if h:
					out.append({"t": "p", "html": h, "text": _clean_ws(ch.text()).strip()})
			elif ch.tag == "table" and ch.has("ltx_equation") or ch.has("ltx_equationgroup"):
				rows = _equation(ch)
				if rows:
					out.append({"t": "eq", "rows": [{"latex": r[0], "no": r[1]} for r in rows]})
			elif ch.tag in ("ul", "ol") or ch.has("ltx_itemize") or ch.has("ltx_enumerate"):
				items = []
				for li in [c for c in ch.children if isinstance(c, Node) and c.tag == "li"]:
					items.append({"html": inline(li).strip(), "text": _clean_ws(li.text()).strip()})
				if items:
					out.append({"t": "list", "ordered": ch.tag == "ol" or ch.has("ltx_enumerate"), "items": items})
			elif ch.tag == "figure" or ch.has("ltx_figure") or ch.has("ltx_table"):
				cap = ch.find(lambda n: n.tag == "figcaption")
				if cap and not ch.parent.has("ltx_figure"):
					out.append({"t": "fig", "html": inline(cap).strip()})
			elif ch.tag == "section":
				walk(ch)  # 하위 섹션 — 제목(h3…)은 위에서 블록으로 들어감
			elif ch.has("ltx_note") or ch.tag in ("script", "style"):
				continue
			else:
				walk(ch)

	walk(sec)
	return out


def kind_of(title, first=False):
	t = (title or "").lower()
	for key, _, pat in KINDS:
		if pat and re.search(pat, t):
			return key
	return "introduction" if first else "other"


def paragraph_roles(blocks):
	"""서론 문단마다 역할 추정 (자동, 표지어 기준)."""
	n_para = 0
	for b in blocks:
		if b["t"] != "p":
			continue
		text = b["text"]
		role = None
		for key, _, pat in ROLE_RULES:
			if n_para == 0 and key == "gap":
				continue  # 첫 문단은 뒤에 However 가 있어도 보통 배경
			if re.search(pat, text, re.I):
				role = key
				break
		if not role and n_para == 0:
			role = "background"  # 서론 첫 문단은 인용이 있어도 보통 배경 설명
		if not role:
			cites = len(re.findall(r"\[\d+(?:[,–\-]\s*\d+)*\]", text)) + b["html"].count("pp-cite")
			role = "prior" if cites >= 2 or re.search(r"\bet al\.|\b(studied|investigated|proposed|considered|analyzed|developed) (in|by)\b", text, re.I) else ("background" if n_para < 2 else "prior" if cites else "background")
		b["role"] = role
		n_para += 1
	return blocks


def contributions(blocks):
	"""서론에서 '기여' 목록 뽑기: 기여를 말하는 문단 다음 목록, 없으면 그 문단의 1)·2) 나눔."""
	for i, b in enumerate(blocks):
		if b["t"] == "p" and CONTRIB_RE.search(b["text"]):
			for nxt in blocks[i + 1:i + 3]:
				if nxt["t"] == "list":
					return [re.sub(r"^\s*(\d+[.)]|•|-)\s*", "", it["html"]) for it in nxt["items"]]
			# PDF: 기여 문단 뒤에 "1) …", "• …" 로 시작하는 문단이 이어짐
			items = []
			for nxt in blocks[i + 1:i + 9]:
				if nxt["t"] == "p" and re.match(r"^\s*(\d\)|\(\d\)|•|▪|–|-|\d\.)\s+", nxt["text"]):
					items.append(re.sub(r"^\s*(\d\)|\(\d\)|•|▪|–|-|\d\.)\s+", "", nxt["html"]))
				elif items:
					break
			if len(items) == 1:  # 한 문단에 1) 2) 3) 이 다 붙어 있는 경우
				items = [x.strip() for x in re.split(r"\s(?:\d\)|\(\d\)|•)\s+", items[0]) if x.strip()]
			if len(items) >= 2:
				return items
			parts = re.split(r"(?:^|\s)(?:\d\)|\(\d\)|•)\s+", b["html"])
			if len(parts) >= 3:
				return [p.strip() for p in parts[1:] if p.strip()]
	return []


ROLE_LABEL = {"background": "배경", "prior": "기존 연구", "gap": "한계·문제 제기", "this": "이 논문이 한 일", "organization": "구성 안내"}


def from_arxiv_html(raw):
	root = parse_tree(raw)
	title_el = root.find(lambda n: n.tag == "h1" and n.has("ltx_title_document"))
	abstract_el = root.find(lambda n: n.has("ltx_abstract"))
	secs = []
	if abstract_el is not None:
		blocks = [b for b in blocks_of(abstract_el) if b["t"] != "h"]
		if blocks:
			secs.append({"kind": "abstract", "title": "Abstract", "blocks": blocks})
	tops = [s for s in root.find_all(lambda n: n.tag == "section" and (n.has("ltx_section") or n.has("ltx_appendix")))]
	for i, s in enumerate(tops):
		h = s.find(lambda n: n.tag in ("h2", "h3") and n.parent is s)
		title = _clean_ws(h.text()).strip() if h else f"Section {i + 1}"
		blocks = blocks_of(s)
		kind = "appendix" if s.has("ltx_appendix") else kind_of(re.sub(r"^[IVX\d]+\.?\s+", "", title), first=i == 0)
		secs.append({"kind": kind, "title": title, "blocks": blocks})
	refs = {}
	for li in root.find_all(lambda n: n.tag == "li" and n.has("ltx_bibitem")):
		tag = li.find(lambda n: n.has("ltx_tag_bibitem"))
		body = "".join(_clean_ws(b.text()) for b in li.find_all(lambda n: n.has("ltx_bibblock")))
		refs[li.attrs.get("id", "")] = {"label": _clean_ws(tag.text()).strip() if tag else "", "text": body.strip()[:600]}
	if not secs:
		raise SectionError("이 논문은 arXiv HTML 에서 섹션을 찾지 못했어요. PDF 를 올려 보세요.", 404)
	return _finish(_clean_ws(title_el.text()).strip() if title_el else "", secs, refs, "arxiv-html")


def _finish(title, secs, refs, source):
	for s in secs:
		if s["kind"] == "introduction":
			paragraph_roles(s["blocks"])
			s["contributions"] = contributions(s["blocks"])
			cited = []
			for b in s["blocks"]:
				for keys in re.findall(r'data-refs="([^"]+)"', b.get("html", "")) + [k for it in b.get("items", []) for k in re.findall(r'data-refs="([^"]+)"', it["html"])]:
					for k in keys.split():
						if k not in cited:
							cited.append(k)
			s["cited"] = cited
			break
	words = sum(len(b.get("text", "").split()) for s in secs for b in s["blocks"])
	return {"title": title, "source": source, "sections": secs, "refs": refs, "words": words,
			"kinds": [{"key": k, "label": label} for k, label, _ in KINDS], "roles": ROLE_LABEL}


# ── PDF ──

HEAD_PDF = re.compile(r"^(?P<num>[IVX]{1,5}|\d{1,2})(?:[.)]|\.?\s)\s*(?P<title>[A-Z][A-Za-z0-9 ,\-:&/()]{2,70})$")
SUB_PDF = re.compile(r"^(?P<num>[A-H]|\d{1,2}\.\d{1,2})[.)]?\s+(?P<title>[A-Z][A-Za-z0-9 ,\-:&/()]{2,70})$")
PLAIN_HEAD = re.compile(r"^(abstract|references|bibliography|acknowledge?ments?|appendix|index terms)\b", re.I)
REF_SPLIT = re.compile(r"(?m)^\s*\[(\d{1,3})\]\s+")
CITE_TXT = re.compile(r"\[(\d{1,3}(?:\s*[,–\-]\s*\d{1,3})*)\]")


def _pdf_cites(text_html):
	def rep(m):
		nums = []
		for part in re.split(r"\s*,\s*", m.group(1)):
			if re.search(r"[–\-]", part):
				a, b = re.split(r"\s*[–\-]\s*", part)[:2]
				if a.isdigit() and b.isdigit() and int(b) - int(a) < 30:
					nums += list(range(int(a), int(b) + 1))
			elif part.isdigit():
				nums.append(int(part))
		keys = " ".join(f"ref.{n}" for n in nums)
		return f'<span class="pp-cite" data-refs="{keys}">[{m.group(1)}]</span>'
	return CITE_TXT.sub(rep, text_html)


def from_pdf(data):
	import fitz  # PyMuPDF

	try:
		doc = fitz.open(stream=data, filetype="pdf")
	except Exception:
		raise SectionError("PDF 를 열지 못했어요.")
	if doc.page_count > 60:
		raise SectionError("60쪽이 넘는 PDF 는 나누지 않아요.")
	lines = []  # (글자, 크기, 굵게)
	sizes = []
	for page in doc:
		for block in page.get_text("dict").get("blocks", []):
			for line in block.get("lines", []):
				spans = line.get("spans", [])
				text = "".join(s.get("text", "") for s in spans).strip()
				if not text:
					continue
				size = max((s.get("size", 0) for s in spans), default=0)
				bold = any("bold" in (s.get("font", "").lower()) or (s.get("flags", 0) & 16) for s in spans)
				lines.append((text, size, bold))
				sizes.append(round(size, 1))
			lines.append(("", 0, False))  # 블록 끝 = 문단 끝
	body = max(set(sizes), key=sizes.count) if sizes else 10
	# 여러 쪽에 똑같이 나오는 짧은 줄 = 머리말·꼬리말 → 빼기
	from collections import Counter
	freq = Counter(t for t, _, _ in lines if t)
	lines = [(t, sz, b) for t, sz, b in lines if not (t and freq[t] >= 3 and len(t) < 90)]
	title = ""
	for t, s, _ in lines[:40]:
		if s >= body * 1.4 and len(t) > 10:
			title = (title + " " + t).strip()
		elif title:
			break
	secs, cur, para = [], None, []

	def flush():
		if cur is not None and para:
			text = re.sub(r"-\s+(?=[a-z])", "", " ".join(para))
			cur["blocks"].append({"t": "p", "html": _pdf_cites(html.escape(text)), "text": text})
		para.clear()

	refs_text = []
	in_refs = False
	for t, s, bold in lines:
		if in_refs:
			refs_text.append(t)
			continue
		emph = bold or s > body * 1.03
		if PLAIN_HEAD.match(t) and len(t) < 40 or (cur is None and re.match(r"^abstract\b", t, re.I)):
			flush()
			word = PLAIN_HEAD.match(t).group(1).lower() if PLAIN_HEAD.match(t) else "abstract"
			if word in ("references", "bibliography"):
				in_refs = True
				continue
			kind = "abstract" if word in ("abstract", "index terms") else "appendix"
			if kind == "abstract" and secs and secs[-1]["kind"] == "abstract":
				cur = secs[-1]
			else:
				cur = {"kind": kind, "title": "Abstract" if kind == "abstract" else t, "blocks": []}
				secs.append(cur)
			rest = re.sub(r"^(abstract|index terms)\W*", "", t, flags=re.I) if kind == "abstract" else ""
			if rest:
				para.append(rest)
			continue
		m = HEAD_PDF.match(t)
		if m and (emph or t.isupper()) and len(t.split()) <= 10 and not t.rstrip().endswith(","):
			flush()
			title_txt = m.group("title").strip()
			kind = kind_of(title_txt.title() if title_txt.isupper() else title_txt, first=not any(x["kind"] != "abstract" for x in secs))
			cur = {"kind": kind, "title": t, "blocks": []}
			secs.append(cur)
			continue
		sm = SUB_PDF.match(t)
		if sm and emph and cur is not None and len(t.split()) <= 10:
			flush()
			cur["blocks"].append({"t": "h", "html": html.escape(t)})
			continue
		if not t:
			flush()
		elif cur is not None:
			para.append(t)
	flush()
	refs = {}
	joined = "\n".join(refs_text)
	parts = REF_SPLIT.split(joined)
	for i in range(1, len(parts) - 1, 2):
		refs[f"ref.{parts[i]}"] = {"label": f"[{parts[i]}]", "text": " ".join(parts[i + 1].split())[:600]}
	if len([s for s in secs if s["kind"] != "abstract"]) < 2:
		raise SectionError("이 PDF 에서 섹션 제목(I. INTRODUCTION 같은)을 찾지 못했어요. 2단 IEEE 형식 논문이 가장 잘 나뉘어요.", 422)
	return _finish(title, secs, refs, "pdf")


# ── arXiv 가져오기 ──

def _fetch(url, limit, accept="text/html"):
	req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": accept})
	try:
		with urllib.request.urlopen(req, timeout=30) as res:
			data = res.read(limit + 1)
	except urllib.error.HTTPError as exc:
		if exc.code == 404:
			raise SectionError("arXiv 에 이 논문의 HTML 판이 없어요. PDF 를 올려 보세요.", 404)
		raise SectionError("arXiv 가 응답하지 않아요. 잠시 뒤 다시 해 주세요.", 502)
	except OSError:
		raise SectionError("arXiv 에 연결하지 못했어요. 잠시 뒤 다시 해 주세요.", 502)
	if len(data) > limit:
		raise SectionError("원문이 너무 커요.", 413)
	return data


def by_arxiv(arxiv_id):
	key = f"papers:sec:{arxiv_id}"
	hit = cache.get(key)
	if hit:
		return hit, True
	raw = _fetch(f"https://arxiv.org/html/{arxiv_id}", MAX_HTML).decode("utf-8", "replace")
	if "ltx_document" not in raw and "ltx_page" not in raw:
		raise SectionError("arXiv 에 이 논문의 HTML 판이 없어요. PDF 를 올려 보세요.", 404)
	out = from_arxiv_html(raw)
	out["arxiv"] = arxiv_id
	cache.set(key, out, CACHE_PAPER)
	return out, False


def find_arxiv(title):
	"""제목이 거의 같은 arXiv 논문 번호 (없으면 '')."""
	norm = lambda s: re.sub(r"[^a-z0-9 ]", "", " ".join((s or "").lower().split()))
	t = norm(title)
	if len(t) < 15:
		return ""
	key = "papers:find-arxiv:" + t[:200]
	hit = cache.get(key)
	if hit is not None:
		return hit
	q = 'ti:"' + re.sub(r'["()]', " ", title)[:200] + '"'
	raw = _fetch("https://export.arxiv.org/api/query?" + urllib.parse.urlencode({"search_query": q, "max_results": 5}), 2 * 1024 * 1024, "application/atom+xml")
	ns = {"a": "http://www.w3.org/2005/Atom"}
	found = ""
	try:
		for e in ET.fromstring(raw).findall("a:entry", ns):
			if difflib.SequenceMatcher(None, t, norm(e.findtext("a:title", "", ns))).ratio() >= 0.92:
				found = re.sub(r"v\d+$", "", e.findtext("a:id", "", ns).split("/abs/")[-1])
				break
	except ET.ParseError:
		pass
	cache.set(key, found, 7 * 24 * 60 * 60)
	return found


@require_GET
def sections_view(request):
	arxiv_id = (request.GET.get("arxiv") or "").strip()
	title = (request.GET.get("title") or "").strip()[:400]
	if arxiv_id and not ARXIV_RE.match(arxiv_id):
		return JsonResponse({"error": "arXiv 번호가 이상해요."}, status=400)
	if not arxiv_id and not title:
		return JsonResponse({"error": "arXiv 번호나 제목이 필요해요."}, status=400)
	try:
		if not arxiv_id:
			if cache.get("papers:find-arxiv:" + re.sub(r"[^a-z0-9 ]", "", " ".join(title.lower().split()))[:200]) is None and _count(request):
				return JsonResponse({"error": "조회가 너무 잦아요. 10분 뒤 다시 해 주세요."}, status=429)
			arxiv_id = find_arxiv(title)
			if not arxiv_id:
				return JsonResponse({"error": "arXiv 에서 같은 논문을 찾지 못했어요. 학교에서 받은 PDF 를 올리면 섹션을 나눠 볼 수 있어요.", "need_pdf": True}, status=404)
		if cache.get(f"papers:sec:{arxiv_id}") is None and _count(request):
			return JsonResponse({"error": "조회가 너무 잦아요. 10분 뒤 다시 해 주세요."}, status=429)
		data, _ = by_arxiv(arxiv_id)
	except SectionError as exc:
		return JsonResponse({"error": str(exc), "need_pdf": exc.status in (404, 422)}, status=exc.status)
	return JsonResponse(data)


@login_required
@require_POST
def sections_pdf(request):
	f = request.FILES.get("file")
	if not f:
		return JsonResponse({"error": "PDF 를 골라 주세요."}, status=400)
	if f.size > MAX_PDF:
		return JsonResponse({"error": "30MB 보다 큰 PDF 는 안 돼요."}, status=400)
	if _count(request):
		return JsonResponse({"error": "너무 잦아요. 10분 뒤 다시 해 주세요."}, status=429)
	data = f.read()
	if not data.startswith(b"%PDF"):
		return JsonResponse({"error": "PDF 파일이 아니에요."}, status=400)
	try:
		out = from_pdf(data)
	except SectionError as exc:
		return JsonResponse({"error": str(exc)}, status=exc.status)
	out["filename"] = f.name[:200]
	return JsonResponse(out)
