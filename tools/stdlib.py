"""표준 서재 (VIP 회원·관리자) — 내가 가진 표준 PDF(IEEE 802.11be 등)를 절(clause) 단위로 나눠 찾기.

- 문서는 올린 사람만 볼 수 있음. IEEE 표준은 저작권 문서라 다른 사람에게 보여 주면 재배포가 되기 때문.
- PDF 는 비공개 폴더(private_media/stdlib/<user>/)에 두고, 나누기는 따로 뜬 프로세스(manage.py stdlib_index)가 함.
- 찾기: PostgreSQL 이면 전문 검색(영어 어간, GIN 색인), 아니면 단어 포함으로.
- ✨ 질문: 찾은 절만 근거로 AI 가 답하고 절 번호·쪽·원문 인용을 붙임.
"""

import re
import subprocess
import sys
from collections import Counter
from datetime import timedelta
from functools import wraps
from html import escape
from pathlib import Path

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.db import connection
from django.db.models import Sum
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from . import ai
from .ai_views import _json, _respond, _text
from .models import StdChunk, StdDoc
from .permissions import AI_LIMITS, tier

MAX_FILE = 95 * 1024 * 1024  # nginx client_max_body_size 100M 안쪽
MAX_TOTAL = 800 * 1024 * 1024
MAX_DOCS = 15
MAX_PAGES = 6000
CHUNK_CHARS = 1800

# 한국어로 찾아도 되게 (표준 문서는 영어)
KO = {
	"펑처링": "puncturing", "프리앰블": "preamble", "자원단위": "resource unit", "리소스유닛": "resource unit", "다중링크": "multi-link", "멀티링크": "multi-link",
	"비컨": "beacon", "채널": "channel", "대역폭": "bandwidth", "변조": "modulation", "부호화": "coding", "부호율": "coding rate", "파일럿": "pilot",
	"부반송파": "subcarrier", "서브캐리어": "subcarrier", "트리거": "trigger", "빔포밍": "beamforming", "사운딩": "sounding", "안테나": "antenna",
	"전력": "power", "보안": "security", "인증": "authentication", "암호화": "encryption", "지연": "latency", "재전송": "retransmission",
	"확인응답": "acknowledgment", "블록확인응답": "block ack", "집성": "aggregation", "스트림": "spatial stream", "보호구간": "guard interval",
	"심볼": "symbol", "필드": "field", "프레임": "frame", "헤더": "header", "패딩": "padding", "스크램블러": "scrambler", "인터리버": "interleaver",
	"매핑": "mapping", "톤": "tone", "주파수": "frequency", "스펙트럼마스크": "spectrum mask", "수신감도": "receiver minimum input sensitivity",
	"감도": "sensitivity", "정의": "definition", "약어": "abbreviations", "타이밍": "timing", "동기": "synchronization", "제한": "restriction",
	"절전": "power save", "웨이크": "wake", "백오프": "backoff", "경쟁": "contention", "채널접근": "channel access", "다중사용자": "multi-user",
}

HEAD = re.compile(r"^(?P<num>(?:\d{1,2}|[A-Z])(?:\.\d{1,3}[a-z]?){0,8}[a-z]?)\.?\s+(?P<title>[A-Z(][^\n]{1,160})$")
ANNEX = re.compile(r"^Annex\s+(?P<num>[A-Z]{1,2})\b\s*(?P<title>.*)$")
# IEEE "Table 36-30—Puncturing patterns", 3GPP "Table 6.1.3.1-1: Buffer size levels"
CAPTION = re.compile(r"^(?P<kind>Table|Figure)\s+(?P<num>[A-Z]?\d{1,3}(?:\.\d{1,3}[a-z]?)*[-–]\d{1,4}[a-z]?)\s*(?:[—–:]|--?)\s*(?P<title>.+)$")
TOC_LINE = re.compile(r"(\.\s?){4,}\s*\d+\s*$|…{2,}\s*\d+\s*$")
NUM_ONLY = re.compile(r"^[\divxlcIVXLC]+$")


# ── 권한 ──

def can_use(user):
	return tier(user) in ("vip", "admin")


def vip_required(view):
	@wraps(view)
	@login_required
	def wrapped(request, *args, **kwargs):
		if not can_use(request.user):
			if request.headers.get("Accept", "").startswith("application/json") or request.method == "POST":
				return JsonResponse({"error": "표준 서재는 VIP 회원만 쓸 수 있어요."}, status=403)
			return render(request, "tools/stdlib.html", {"denied": True}, status=403)
		return view(request, *args, **kwargs)
	return wrapped


def _doc(request, pk):
	doc = StdDoc.objects.filter(user=request.user, pk=pk).first()
	if not doc:
		raise Http404
	return doc


# ── PDF 나누기 ──

def _page_lines(page):
	"""한 쪽의 (글자, 크기, 굵게) 줄 목록과 위·아래 가장자리 줄(머리말·꼬리말 후보).
	같은 높이의 조각(절 번호 · 제목 등)은 한 줄로 합치고, 줄 간격이 벌어지면 "" 로 문단을 끊음."""
	height = page.rect.height or 842
	raw = []
	for block in page.get_text("dict").get("blocks", []):
		for line in block.get("lines", []):
			spans = [s for s in line.get("spans", []) if s.get("text", "").strip()]
			if not spans:
				continue
			text = " ".join("".join(s.get("text", "") for s in line.get("spans", [])).split())
			size = max(s.get("size", 0) for s in spans)
			bold = all(("bold" in s.get("font", "").lower() or (s.get("flags", 0) & 16)) for s in spans)
			x0, y0, _, y1 = line["bbox"]
			raw.append([round(y0, 1), x0, y1, text, round(size, 1), bold])
	raw.sort(key=lambda r: (r[0], r[1]))
	rows = []
	for r in raw:
		if rows and abs(r[0] - rows[-1][0]) < 2.5 and abs(r[4] - rows[-1][4]) < 1.5:
			rows[-1][3] += " " + r[3]
			rows[-1][2] = max(rows[-1][2], r[2])
			rows[-1][5] = rows[-1][5] and r[5]
		else:
			rows.append(r)
	out, edges, prev = [], set(), None
	for y0, _, y1, text, size, bold in rows:
		if y0 < height * 0.09 or y1 > height * 0.91:
			edges.add(text)
		if prev is not None and y0 - prev > max(4.0, size * 0.6):
			out.append(("", 0, False))
		out.append((text, size, bold))
		prev = y1
	out.append(("", 0, False))
	return out, edges


def parse(path, progress=None):
	"""PDF → 조각 목록 [{kind, clause, title, page, text}].

	메모리를 아끼려고 두 번 훑음: ① 가장자리 줄(머리말·꼬리말) 횟수와 글자 크기만 세고,
	② 한 쪽씩 다시 읽으며 바로 조각으로 만듦 (전체 쪽을 메모리에 올려 두지 않음).
	"""
	import fitz  # PyMuPDF

	doc = fitz.open(path)
	n = doc.page_count
	if n > MAX_PAGES:
		raise ValueError(f"{MAX_PAGES}쪽이 넘는 문서는 나누지 않아요.")
	norm = lambda t: re.sub(r"\d+", "#", t)
	freq, sizes = Counter(), Counter()
	for pno in range(n):
		lines, edges = _page_lines(doc[pno])
		freq.update({norm(t) for t in edges})
		sizes.update(s for t, s, _ in lines if t)
		if progress and pno % 100 == 99:
			progress(int(pno / n * 30))
			fitz.TOOLS.store_shrink(100)  # PyMuPDF 내부 캐시 비우기
	repeat = {k for k, c in freq.items() if c >= max(5, n * 0.15) and len(k) < 160}
	body = sizes.most_common(1)[0][0] if sizes else 10
	del freq, sizes

	chunks = []
	cur = {"kind": StdChunk.KIND_CLAUSE, "clause": "", "title": "앞부분", "page": 1, "buf": []}
	para = []
	cap = None  # 표·그림 제목 뒤 몇 줄을 같이 모음

	def flush_para():
		if para:
			text = re.sub(r"(\w)-\s+(?=[a-z])", r"\1", " ".join(para))
			cur["buf"].append(text)
			para.clear()

	def flush_clause(force=False):
		flush_para()
		text = "\n".join(cur["buf"]).strip()
		if text and (force or len(text) >= 1):
			# 긴 절은 여러 조각으로 (문단 경계에서)
			piece, start_page = [], cur["page"]
			for p in cur["buf"]:
				piece.append(p)
				if sum(len(x) for x in piece) >= CHUNK_CHARS:
					chunks.append({"kind": cur["kind"], "clause": cur["clause"], "title": cur["title"], "page": start_page, "text": "\n".join(piece)})
					piece = []
			if piece:
				chunks.append({"kind": cur["kind"], "clause": cur["clause"], "title": cur["title"], "page": start_page, "text": "\n".join(piece)})
		cur["buf"] = []

	for pno in range(1, n + 1):
		lines, _ = _page_lines(doc[pno - 1])
		if pno % 100 == 0:
			fitz.TOOLS.store_shrink(100)
			if progress:
				progress(30 + int(pno / n * 65))
		for text, size, bold in lines:
			if not text:
				flush_para()
				continue
			if norm(text) in repeat or NUM_ONLY.match(text) or TOC_LINE.search(text):
				continue
			c = CAPTION.match(text)
			if c:
				if cap:
					chunks.append(cap)
				kind = StdChunk.KIND_TABLE if c["kind"] == "Table" else StdChunk.KIND_FIGURE
				cap = {"kind": kind, "clause": f"{c['kind']} {c['num'].replace('–', '-')}", "title": c["title"][:300], "page": pno, "text": text, "left": 900}
				continue
			if cap:
				cap["text"] += " " + text
				cap["left"] -= len(text)
				if cap["left"] <= 0:
					chunks.append(cap)
					cap = None
			h = HEAD.match(text)
			a = ANNEX.match(text)
			is_head = (bold or size > body * 1.05) and len(text) < 170 and not text.endswith((",", ";")) and (h or a)
			if is_head and h and not re.search(r"[a-z]{2,}\s+[a-z]{2,}\s+[a-z]{2,}\s+[a-z]{2,}\s+[a-z]{2,}\s+[a-z]{2,}\s+[a-z]{2,}\s+[a-z]{2,}", h["title"]):
				flush_clause()
				cur.update(kind=StdChunk.KIND_CLAUSE, clause=h["num"], title=h["title"].strip()[:300], page=pno)
				continue
			if is_head and a:
				flush_clause()
				cur.update(kind=StdChunk.KIND_CLAUSE, clause=a["num"], title=("Annex " + a["num"] + " " + a["title"]).strip()[:300], page=pno)
				cur["more_title"] = cur["title"].endswith(":") or not a["title"].strip()
				continue
			if cur.get("more_title"):
				cur["more_title"] = False
				if len(text) < 120:
					cur["title"] = (cur["title"] + " " + text).strip()[:300]
					continue
			para.append(text)
	flush_clause(force=True)
	if cap:
		chunks.append(cap)
	doc.close()
	ctrl = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\ufffe\uffff]")  # PostgreSQL 은 NUL 등 제어 문자를 못 받음
	for c in chunks:
		c.pop("left", None)
		for k in ("text", "title", "clause"):
			c[k] = ctrl.sub("", c[k])
		c["text"] = c["text"][:12000]
	return chunks, n


def index_doc(doc_id):
	"""manage.py stdlib_index 가 부름. 실패해도 상태만 남김."""
	doc = StdDoc.objects.get(pk=doc_id)
	try:
		def progress(p):
			StdDoc.objects.filter(pk=doc.pk).update(progress=p, updated_at=timezone.now())

		chunks, pages = parse(doc.file.path, progress)
		if not chunks:
			raise ValueError("글자를 거의 뽑지 못했어요. 그림으로만 된(스캔) PDF 일 수 있어요.")
		StdChunk.objects.filter(doc=doc).delete()
		StdChunk.objects.bulk_create([StdChunk(doc=doc, order=i, **c) for i, c in enumerate(chunks)], batch_size=1000)
		StdDoc.objects.filter(pk=doc.pk).update(status=StdDoc.STATUS_READY, pages=pages, chunks=len(chunks), progress=100, error="", updated_at=timezone.now())
	except Exception as exc:  # noqa: BLE001 — 어떤 실패든 화면에 이유를 보여 줌
		StdDoc.objects.filter(pk=doc.pk).update(status=StdDoc.STATUS_ERROR, error=str(exc)[:300] or exc.__class__.__name__, updated_at=timezone.now())


def start_index(doc):
	subprocess.Popen(
		[sys.executable, str(Path(settings.BASE_DIR) / "manage.py"), "stdlib_index", str(doc.pk)],
		cwd=settings.BASE_DIR, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
	)


# ── 찾기 ──

def expand_query(q):
	q = " ".join((q or "").split())[:200]
	for ko, en in sorted(KO.items(), key=lambda x: -len(x[0])):
		q = q.replace(ko, f" {en} ")
	return " ".join(q.split())


def _terms(q):
	words = re.findall(r"[A-Za-z][A-Za-z0-9\-]+|\d+(?:\.\d+)*", q)
	stop = {"the", "and", "for", "with", "what", "how", "are", "is", "of", "in", "to", "a", "an", "or", "on", "by", "be", "can", "which", "when"}
	return [w for w in words if w.lower() not in stop]


def search(user, q, doc_id=None, kind="", limit=30):
	q = expand_query(q)
	qs = StdChunk.objects.filter(doc__user=user, doc__status=StdDoc.STATUS_READY).select_related("doc")
	if doc_id:
		qs = qs.filter(doc_id=doc_id)
	if kind in (StdChunk.KIND_TABLE, StdChunk.KIND_FIGURE):
		qs = qs.filter(kind=kind)
	# 절 번호로 바로 찾기 (36.3.12.11 / Table 36-30)
	m = re.fullmatch(r"(?:(table|figure)\s+)?([A-Z]?\d{1,3}(?:[.\-–]\d{1,4}){1,8}[a-z]?)", q, re.I)
	if m:
		num = m.group(2).replace("–", "-")
		hit = list(qs.filter(clause__iexact=(f"{m.group(1).title()} {num}" if m.group(1) else num)).order_by("doc_id", "order")[:limit])
		if not hit and not m.group(1):
			hit = list(qs.filter(clause__startswith=num).order_by("doc_id", "order")[:limit])
		if hit:
			return hit, q
	terms = _terms(q)
	if not terms:
		return [], q
	if connection.vendor == "postgresql":
		expr = "to_tsvector('english', coalesce(tools_stdchunk.clause, '') || ' ' || coalesce(tools_stdchunk.title, '') || ' ' || tools_stdchunk.text)"
		query = "websearch_to_tsquery('english', %s)"
		# 변경 이력·앞부분은 용어가 다 나와서 점수가 부풀므로 낮춤
		fig = "1" if kind == StdChunk.KIND_FIGURE or re.search(r"\bfig(ure)?s?\b|그림", q, re.I) else "0.55"
		rank = (f"(ts_rank_cd({expr}, {query}) + CASE WHEN to_tsvector('english', coalesce(tools_stdchunk.title, '')) @@ {query} THEN 0.6 ELSE 0 END)"
				f" * CASE WHEN tools_stdchunk.kind = 'figure' THEN {fig} ELSE 1 END"
				f" * CASE WHEN tools_stdchunk.title ILIKE '%%change history%%' OR tools_stdchunk.title ILIKE '%%revision history%%' OR tools_stdchunk.title = '앞부분' THEN 0.15 ELSE 1 END")
		def run(text):
			return list(qs.extra(where=[f"{expr} @@ {query}"], params=[text], select={"rank": rank}, select_params=[text, text]).order_by("-rank")[:limit])

		# 표준은 변수 이름을 붙여 씀 (drx-InactivityTimer) → 이웃한 두 단어를 붙인 형태로도 찾아서 합침
		variants = [q]
		if 1 < len(terms) <= 6 and '"' not in q:
			for i in range(len(terms) - 1):
				variants.append(" ".join(terms[:i] + [terms[i] + terms[i + 1]] + terms[i + 2:]))
			if len(terms) >= 3:
				variants.append("".join(terms))  # timeAlignmentTimer 처럼 셋 이상 붙인 이름
		best = {}
		for v in variants:
			for r in run(v):
				if r.id not in best or r.rank > best[r.id].rank:
					best[r.id] = r
		rows = sorted(best.values(), key=lambda r: -r.rank)[:limit]
		if not rows and len(terms) > 1:  # 다 들어간 게 없으면 하나라도 들어간 것
			rows = run(" or ".join(terms))
		return rows, q
	# SQLite (로컬·테스트): 모든 단어 포함, 제목에 있으면 앞으로
	for t in terms:
		stem = t[:-1] if len(t) > 5 and t.endswith("s") else t
		qs = qs.filter(models_q(stem))
	rows = list(qs[:400])
	want_fig = kind == StdChunk.KIND_FIGURE or re.search(r"\bfig(ure)?s?\b|그림", q, re.I)
	low = lambda c: (0.15 if ("change history" in c.title.lower() or c.title == "앞부분") else 1) * (0.55 if c.kind == StdChunk.KIND_FIGURE and not want_fig else 1)
	rows.sort(key=lambda c: (-low(c) * sum(c.title.lower().count(t.lower()) * 5 + c.text.lower().count(t.lower()) for t in terms), c.order))
	return rows[:limit], q


def models_q(stem):
	from django.db.models import Q
	return Q(text__icontains=stem) | Q(title__icontains=stem) | Q(clause__icontains=stem)


def snippet(text, terms, width=420):
	low = text.lower()
	stems = [t.lower()[:max(4, len(t) - 2)] for t in terms]
	pos = min((low.find(s) for s in stems if low.find(s) >= 0), default=0)
	start = max(0, pos - width // 3)
	end = min(len(text), start + width)
	piece = escape(text[start:end])
	for s in sorted(set(stems), key=len, reverse=True):
		if s:
			piece = re.sub(rf"(?i)\b({re.escape(escape(s))}[\w\-]*)", r"<mark>\1</mark>", piece)
	return ("… " if start else "") + piece + (" …" if end < len(text) else "")


def _chunk_json(c, terms):
	return {"id": c.id, "doc": c.doc_id, "doc_title": c.doc.title, "kind": c.kind, "clause": c.clause, "title": c.title, "page": c.page, "snippet": snippet(c.text, terms), "len": len(c.text)}


# ── 화면·API ──

@vip_required
def page(request):
	return render(request, "tools/stdlib.html", {"max_mb": MAX_FILE // 1024 // 1024})


def _doc_json(d):
	return {"id": d.id, "title": d.title, "filename": d.filename, "size": d.size, "pages": d.pages, "chunks": d.chunks, "status": d.status, "progress": d.progress, "error": d.error, "created": d.created_at.isoformat()}


@vip_required
@require_GET
def docs(request):
	# 30분 넘게 '나누는 중'이면 프로세스가 죽은 것으로 봄
	stale = timezone.now() - timedelta(minutes=30)
	StdDoc.objects.filter(user=request.user, status=StdDoc.STATUS_PROCESSING, updated_at__lt=stale).update(status=StdDoc.STATUS_ERROR, error="나누다가 멈췄어요. 다시 나누기를 눌러 주세요.")
	items = StdDoc.objects.filter(user=request.user)
	used = items.aggregate(s=Sum("size"))["s"] or 0
	return JsonResponse({"items": [_doc_json(d) for d in items], "used": used, "max_total": MAX_TOTAL, "max_file": MAX_FILE})


@vip_required
@require_POST
def upload(request):
	f = request.FILES.get("file")
	if not f:
		return JsonResponse({"error": "PDF 를 골라 주세요."}, status=400)
	if f.size > MAX_FILE:
		return JsonResponse({"error": f"{MAX_FILE // 1024 // 1024}MB 보다 큰 파일은 올릴 수 없어요."}, status=400)
	mine = StdDoc.objects.filter(user=request.user)
	if mine.count() >= MAX_DOCS:
		return JsonResponse({"error": f"문서는 {MAX_DOCS}개까지 둘 수 있어요."}, status=400)
	if (mine.aggregate(s=Sum("size"))["s"] or 0) + f.size > MAX_TOTAL:
		return JsonResponse({"error": "서재 용량(800MB)이 모자라요. 안 쓰는 문서를 지워 주세요."}, status=400)
	head = f.read(5)
	f.seek(0)
	if head != b"%PDF-":
		return JsonResponse({"error": "PDF 파일이 아니에요."}, status=400)
	title = (request.POST.get("title") or "").strip()[:200] or re.sub(r"\.pdf$", "", f.name, flags=re.I)[:200]
	doc = StdDoc(user=request.user, title=title, filename=f.name[:255], size=f.size)
	doc.file.save("x.pdf", f, save=False)
	doc.save()
	start_index(doc)
	return JsonResponse({"item": _doc_json(doc)})


@vip_required
@require_POST
def doc_action(request, pk, action):
	doc = _doc(request, pk)
	if action == "delete":
		doc.delete()
		return JsonResponse({"deleted": True})
	if action == "reindex":
		StdDoc.objects.filter(pk=doc.pk).update(status=StdDoc.STATUS_PROCESSING, progress=0, error="", updated_at=timezone.now())
		start_index(doc)
		doc.refresh_from_db()
		return JsonResponse({"item": _doc_json(doc)})
	if action == "rename":
		title = (_json(request).get("title") or "").strip()[:200]
		if title:
			doc.title = title
			doc.save(update_fields=["title", "updated_at"])
		return JsonResponse({"item": _doc_json(doc)})
	raise Http404


@vip_required
@require_GET
def search_view(request):
	q = (request.GET.get("q") or "").strip()
	if len(q) < 2:
		return JsonResponse({"error": "두 글자 이상 넣어 주세요."}, status=400)
	doc_id = request.GET.get("doc") or None
	rows, expanded = search(request.user, q, doc_id=doc_id, kind=request.GET.get("kind") or "")
	terms = _terms(expanded)
	return JsonResponse({"query": expanded, "items": [_chunk_json(c, terms) for c in rows]})


@vip_required
@require_GET
def chunk_view(request, pk):
	"""조각 전체 + 같은 절의 앞뒤 조각 (펼쳐 보기)."""
	c = StdChunk.objects.select_related("doc").filter(pk=pk, doc__user=request.user).first()
	if not c:
		raise Http404
	same = list(StdChunk.objects.filter(doc=c.doc, clause=c.clause, kind=c.kind).order_by("order")[:20]) if c.clause else [c]
	terms = _terms(expand_query(request.GET.get("q") or ""))

	def mark(text):
		h = escape(text)
		for s in sorted({t.lower()[:max(4, len(t) - 2)] for t in terms}, key=len, reverse=True):
			h = re.sub(rf"(?i)\b({re.escape(escape(s))}[\w\-]*)", r"<mark>\1</mark>", h)
		return h

	return JsonResponse({"clause": c.clause, "title": c.title, "doc_title": c.doc.title, "page": c.page,
						 "parts": [{"id": x.id, "page": x.page, "html": mark(x.text), "current": x.id == c.id} for x in same]})


@vip_required
@require_GET
def page_image(request, pk, page_no):
	doc = _doc(request, pk)
	if doc.status != StdDoc.STATUS_READY or not (1 <= page_no <= doc.pages):
		raise Http404
	import fitz

	with fitz.open(doc.file.path) as pdf:
		pix = pdf[page_no - 1].get_pixmap(dpi=min(200, max(80, int(request.GET.get("dpi") or 130))))
		png = pix.tobytes("png")
	res = HttpResponse(png, content_type="image/png")
	res["Cache-Control"] = "private, max-age=86400"
	return res


ASK_SYSTEM = (
	"너는 IEEE 802.11·3GPP 같은 통신 표준을 잘 아는 조교야. 주어진 표준 발췌(각각 [번호] 절·쪽 표시)만 근거로 한국어로 답해. "
	"규칙: (1) 발췌에 없는 내용은 지어내지 말고 '찾은 부분에는 없다'고 말해. (2) 답의 문장마다 근거 번호를 [1]처럼 붙여. "
	"(3) 표 값·필드 이름·비트 수 같은 정확한 값은 발췌에 있는 그대로 써. (4) 근거로 쓴 발췌마다 짧은 원문 영어 인용(한두 문장)을 quotes 에 넣어. "
	"(5) 전문 용어는 영어 그대로 써도 돼."
)
ASK_TOOL = {
	"name": "std_answer",
	"description": "표준 질문 답",
	"input_schema": {
		"type": "object",
		"properties": {
			"answer": {"type": "string", "description": "한국어 답 (근거 번호 [n] 포함, 줄바꿈 가능)"},
			"quotes": {"type": "array", "items": {"type": "object", "properties": {"n": {"type": "integer"}, "quote": {"type": "string"}}, "required": ["n", "quote"]}},
			"confident": {"type": "boolean", "description": "발췌만으로 충분히 답했는지"},
		},
		"required": ["answer", "quotes", "confident"],
	},
}


@vip_required
@require_POST
def ask(request):
	def run():
		data = _json(request)
		question = _text(data.get("q"), 500)
		if len(question) < 3:
			raise ai.AIError("질문을 넣어 주세요.")
		ids = [int(x) for x in (data.get("chunks") or []) if str(x).isdigit()][:10]
		if ids:
			found = list(StdChunk.objects.select_related("doc").filter(pk__in=ids, doc__user=request.user))
			found.sort(key=lambda c: ids.index(c.id))
		else:
			found, _ = search(request.user, data.get("search") or question, doc_id=data.get("doc") or None, limit=8)
		if not found:
			raise ai.AIError("질문과 관련된 부분을 서재에서 찾지 못했어요. 영어 키워드로 먼저 찾아보세요.")
		budget = AI_LIMITS.get(tier(request.user), {}).get("max_chars", 15000) - len(question) - 300
		# 긴 절은 여러 조각으로 나뉘어 있으니, 같은 절의 조각을 이어 붙여 한 근거로 (중복은 하나로)
		groups, seen = [], set()
		for c in found:
			key = (c.doc_id, c.kind, c.clause or f"#{c.id}")
			if key in seen:
				continue
			seen.add(key)
			if c.clause:
				sib = list(StdChunk.objects.filter(doc_id=c.doc_id, kind=c.kind, clause=c.clause, order__gte=c.order - 3, order__lte=c.order + 4).order_by("order"))
			else:
				sib = [c]
			groups.append((c, sib))
		# 가장 관련 높은 첫 근거에 40%, 나머지는 나눠 가짐
		rest = max(1, len(groups) - 1)
		parts, used, kept = [], 0, []
		for i, (c, sib) in enumerate(groups, start=1):
			each = max(800, int(budget * 0.4) if i == 1 and len(groups) > 1 else (budget - int(budget * 0.4)) // rest if len(groups) > 1 else budget)
			if c.clause:  # 첫 근거는 절 앞부분(정의·조건)이 잘리지 않게 더 넓게
				sib = list(StdChunk.objects.filter(doc_id=c.doc_id, kind=c.kind, clause=c.clause).order_by("order")[:12]) if i == 1 else sib
			body = "\n".join(x.text for x in sib)
			if len(body) > each:  # 맞힌 조각을 가운데 두고 자름
				pos = body.find(c.text[:200])
				start = max(0, min(pos - each // 3, len(body) - each)) if pos >= 0 else 0
				body = body[start:start + each]
			if used + len(body) > budget:
				break
			parts.append(f"[{i}] {c.doc.title} · {c.clause} {c.title} · p.{sib[0].page}\n{body}")
			kept.append((c, sib[0].page))
			used += len(body) + 80
		content = f"질문: {question}\n\n표준 발췌:\n\n" + "\n\n".join(parts)
		ai.check(request.user, len(content))
		raw = ai.call(request.user, "stdlib", system=ASK_SYSTEM, tool=ASK_TOOL, content=content, max_tokens=1800)
		sources = [{"n": i, "id": c.id, "doc": c.doc_id, "doc_title": c.doc.title, "clause": c.clause, "title": c.title, "page": page} for i, (c, page) in enumerate(kept, start=1)]
		quotes = [{"n": q.get("n"), "quote": _text(q.get("quote"), 600)} for q in (raw.get("quotes") or []) if isinstance(q, dict) and isinstance(q.get("n"), int) and 1 <= q["n"] <= len(sources)]
		return {"answer": str(raw.get("answer") or "").strip()[:6000], "quotes": quotes, "sources": sources, "confident": bool(raw.get("confident"))}
	return _respond(request, run)
