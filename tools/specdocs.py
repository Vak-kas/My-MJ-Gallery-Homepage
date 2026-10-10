"""🔎 3GPP 본문 검색.

관리자가 고른 규격(기본: NR 주요 규격·NTN)의 최신판 zip 을 3GPP 공식 주소에서 받아, 워드(.docx) 본문을
절 단위로 나눠 DB 에 넣고 PostgreSQL 전문 검색으로 찾음. 받은 문서 파일은 나누고 바로 지움(다시 배포하지 않음).
검색 결과는 누구나 짧은 미리보기로, 절 전체 글은 로그인한 회원만 봄.

나누기는 따로 뜬 프로세스(manage.py spec_index)가 하나씩 함 — 3GPP 서버가 느려서(수 MB 에 수십 초) 요청 안에서 하지 않음.
"""

import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from xml.etree.ElementTree import iterparse

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.db import connection, transaction
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from . import specs
from .models import SpecChunk, SpecDoc
from .stdlib import _terms, expand_query, snippet

# 처음 '기본 규격 받기' 로 넣는 것 — NR 주요 규격 + NTN·채널·코어 몇 개
DEFAULT_SPECS = [
	"38.300", "38.304", "38.305", "38.306", "38.211", "38.212", "38.213", "38.214", "38.215",
	"38.321", "38.322", "38.323", "38.331", "38.401",
	"38.101-5", "38.108", "38.811", "38.821", "38.863", "38.901",
	"36.300", "23.501",
]
USER_AGENT = "smjgallery.kr 3GPP spec search (+https://smjgallery.kr/tools/specs/)"
MAX_ZIP = 150 * 1024 * 1024
CHUNK_CHARS = 1800
RUN_LOCK = "specdocs:running"
PAUSE = 10  # 규격 하나 받은 뒤 쉬는 초

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
M = "{http://schemas.openxmlformats.org/officeDocument/2006/math}"
HEADING_RE = re.compile(r"^(Heading(\d)|H6)$")
BULLET_RE = re.compile(r"^B\d$")


# ── 워드 본문 나누기 ──

def _ptext(p):
	out = []
	for el in p.iter():
		if el.tag in (W + "t", M + "t") and el.text:
			out.append(el.text)
		elif el.tag == W + "tab":
			out.append("\t")
		elif el.tag in (W + "br", W + "cr"):
			out.append("\n")
	return "".join(out).replace("\xa0", " ")


def _style(p):
	ppr = p.find(W + "pPr")
	st = ppr.find(W + "pStyle") if ppr is not None else None
	return st.get(W + "val") if st is not None else ""


def _split_heading(text):
	"""'5.1.1\tRandom Access …' → ('5.1.1', 'Random Access …'), 'Annex A (normative):\t…' → ('A', …)."""
	text = text.strip()
	num, _, title = text.partition("\t")
	num, title = num.strip(), " ".join(title.split())
	if title and re.fullmatch(r"(?:Annex\s+)?[A-Z]?\d*(?:\.\w+)*", num) and len(num) <= 30:
		return num.replace("Annex ", ""), title
	return "", " ".join(text.split())


def _asn1_title(code, fallback):
	m = re.search(r"^\s*([A-Za-z][\w-]*)\s*::=", code, re.M)
	return m.group(1) if m else fallback


def parse_docx(path, progress=None):
	"""docx → [{kind, clause, title, text}]. 큰 문서(수백 MB XML)도 메모리를 적게 쓰게 iterparse."""
	chunks = []
	state = {"clause": "", "title": "앞부분", "buf": [], "asn": [], "caption": "", "last_num": ""}

	def flush_text():
		text = "\n".join(state["buf"]).strip()
		state["buf"] = []
		if not text:
			return
		# 긴 절은 문단 경계에서 나눔
		piece = ""
		for para in text.split("\n"):
			if piece and len(piece) + len(para) > CHUNK_CHARS:
				chunks.append({"kind": SpecChunk.KIND_CLAUSE, "clause": state["clause"], "title": state["title"], "text": piece.strip()})
				piece = ""
			piece += para + "\n"
		if piece.strip():
			chunks.append({"kind": SpecChunk.KIND_CLAUSE, "clause": state["clause"], "title": state["title"], "text": piece.strip()[:20000]})

	def flush_asn():
		code = "\n".join(state["asn"]).rstrip()
		state["asn"] = []
		if code.strip():
			for k in range(0, len(code), 12000):
				chunks.append({"kind": SpecChunk.KIND_ASN1, "clause": state["clause"], "title": _asn1_title(code[k:k + 12000], state["title"])[:300], "text": code[k:k + 12000]})

	with zipfile.ZipFile(path) as z:
		size = z.getinfo("word/document.xml").file_size or 1
		with z.open("word/document.xml") as f:
			depth = 0  # 표 안이면 1 이상
			for event, el in iterparse(f, events=("start", "end")):
				if el.tag == W + "tbl":
					if event == "start":
						depth += 1
						continue
					depth -= 1
					if depth:
						continue
					flush_asn()
					rows = []
					for tr in el.iter(W + "tr"):
						# 칸 안의 문단은 ' · ' 로 (필드 이름 · 설명)
						cells = [" · ".join(t for t in (" ".join(_ptext(p).split()) for p in tc.iter(W + "p")) if t) for tc in tr.findall(W + "tc")]
						if any(cells):
							rows.append(" | ".join(cells))
					if rows:
						title = state["caption"] or f"{state['title']} — 표"
						# 긴 표는 줄 경계에서 6000자 안팎으로 나눔 (머리 줄은 조각마다 다시 붙임)
						head, piece, first = rows[0], "", True
						for row in rows:
							if piece and len(piece) + len(row) > 6000:
								chunks.append({"kind": SpecChunk.KIND_TABLE, "clause": state["clause"], "title": (title + ("" if first else " (이어서)"))[:300], "text": piece.strip()[:12000]})
								piece, first = head + "\n", False
							piece += row + "\n"
						if piece.strip():
							chunks.append({"kind": SpecChunk.KIND_TABLE, "clause": state["clause"], "title": (title + ("" if first else " (이어서)"))[:300], "text": piece.strip()[:12000]})
					state["caption"] = ""
					el.clear()
					continue
				if event != "end" or el.tag != W + "p" or depth:
					continue
				st = _style(el)
				text = _ptext(el)
				el.clear()
				if st.startswith("TOC") or st in ("ZA", "ZB", "ZT", "ZU", "ZV", "ZH"):
					continue  # 목차·표지
				if st == "PL":
					state["asn"].append(text.rstrip("\n"))
					continue
				if state["asn"]:
					flush_asn()
				if HEADING_RE.match(st):
					flush_text()
					num, title = _split_heading(text)
					if num:
						state["last_num"] = num[:40]
					else:  # 38.331 의 '–\tNTN-Config' 처럼 번호 없는 제목은 위 절 번호를 물려받음
						title = title.lstrip("–-— ").strip()
					state["clause"], state["title"] = (num[:40] or state["last_num"]), title
					state["title"] = (state["title"] or "(제목 없음)")[:300]
					if progress and len(chunks) % 50 == 0:
						progress(min(95, int(f.tell() / size * 100)) if hasattr(f, "tell") else 50)
					continue
				t = " ".join(text.split())
				if not t:
					continue
				if st == "TH":
					state["caption"] = t  # 다음 표의 제목
					continue
				if st == "TF":
					state["buf"].append(f"[그림] {t}")
					continue
				if BULLET_RE.match(st):
					t = "• " + t
				elif st == "NO" and not t.startswith("NOTE"):
					t = "NOTE: " + t
				state["buf"].append(t)
	flush_asn()
	flush_text()
	return [c for c in chunks if c["text"].strip()]


# ── 받기·나누기 ──

def _download(url, dest):
	req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
	size = 0
	with urllib.request.urlopen(req, timeout=120) as res, open(dest, "wb") as out:
		while True:
			chunk = res.read1(256 * 1024)
			if not chunk:
				break
			size += len(chunk)
			if size > MAX_ZIP:
				raise ValueError("문서가 너무 커요 (150MB 넘음)")
			out.write(chunk)
	return size


def _latest(number):
	info = specs.load_index()["specs"].get(number)
	if not info:
		raise ValueError("3GPP 목록에 없는 번호예요")
	j = specs.to_json(info)
	if not j["latest"].get("zip"):
		raise ValueError("받을 수 있는 버전이 없어요 (초안만 있음)")
	return info, j


def index_spec(doc):
	"""규격 하나를 받아 나눔. 실패하면 상태에 이유만 남김."""
	SpecDoc.objects.filter(pk=doc.pk).update(status=SpecDoc.STATUS_PROCESSING, progress=1, error="")
	tmp = tempfile.mkdtemp(prefix="spec-")
	try:
		info, j = _latest(doc.number)
		if doc.chunks and doc.version == j["latest"]["ver"]:  # 이미 최신판
			SpecDoc.objects.filter(pk=doc.pk).update(status=SpecDoc.STATUS_READY, progress=100, error="")
			return
		zpath = os.path.join(tmp, "spec.zip")
		_download(j["latest"]["zip"], zpath)
		SpecDoc.objects.filter(pk=doc.pk).update(progress=30)
		with zipfile.ZipFile(zpath) as z:
			docs = sorted((i for i in z.infolist() if i.filename.lower().endswith(".docx")), key=lambda i: -i.file_size)
			if not docs:
				olds = [i for i in z.infolist() if i.filename.lower().endswith(".doc")]
				raise ValueError("옛 워드(.doc) 형식이라 읽지 못했어요" if olds else "zip 안에 워드 문서가 없어요")
			dpath = z.extract(docs[0], tmp)
		os.remove(zpath)

		def progress(p):
			SpecDoc.objects.filter(pk=doc.pk).update(progress=30 + p * 6 // 10)

		chunks = parse_docx(dpath, progress)
		if len(chunks) < 3:
			raise ValueError("본문을 거의 뽑지 못했어요")
		with transaction.atomic():
			SpecChunk.objects.filter(doc=doc).delete()
			SpecChunk.objects.bulk_create([SpecChunk(doc=doc, order=i, **c) for i, c in enumerate(chunks)], batch_size=1000)
			SpecDoc.objects.filter(pk=doc.pk).update(
				status=SpecDoc.STATUS_READY, progress=100, chunks=len(chunks), error="", kind=info["type"], title=info["title"][:300],
				version=j["latest"]["ver"], release=j["latest"]["rel"], zip_url=j["latest"]["zip"], indexed_at=timezone.now(),
			)
	except Exception as exc:  # noqa: BLE001 — 어떤 실패든 화면에 이유를 보여 줌
		msg = str(exc)[:300] or exc.__class__.__name__
		if isinstance(exc, urllib.error.HTTPError):
			msg = f"3GPP 에서 받지 못했어요 (HTTP {exc.code})"
		# 예전 버전이 나눠져 있으면 그대로 쓰게 둠
		ready = SpecChunk.objects.filter(doc=doc).exists()
		SpecDoc.objects.filter(pk=doc.pk).update(status=SpecDoc.STATUS_READY if ready else SpecDoc.STATUS_ERROR, progress=100 if ready else 0, error=msg)
	finally:
		for root, dirs, files in os.walk(tmp, topdown=False):
			for name in files:
				os.remove(os.path.join(root, name))
			for name in dirs:
				os.rmdir(os.path.join(root, name))
		os.rmdir(tmp)


def run_pending():
	"""기다리는 규격을 하나씩 (manage.py spec_index 가 부름). 한 번에 하나의 프로세스만."""
	if not cache.add(RUN_LOCK, os.getpid(), 3 * 60 * 60):
		return 0
	n = 0
	try:
		while True:
			doc = SpecDoc.objects.filter(status=SpecDoc.STATUS_PENDING).order_by("updated_at", "id").first()
			if not doc:
				break
			index_spec(doc)
			cache.set(RUN_LOCK, os.getpid(), 3 * 60 * 60)
			n += 1
			time.sleep(PAUSE)  # 3GPP 서버에 몰아서 받지 않게
	finally:
		cache.delete(RUN_LOCK)
	return n


def queue(numbers):
	"""받을 목록에 넣음 (이미 있으면 새 버전 확인으로). 받는 중인 건 그대로."""
	for number in numbers:
		doc, _ = SpecDoc.objects.get_or_create(number=number)
		if doc.status != SpecDoc.STATUS_PROCESSING:
			SpecDoc.objects.filter(pk=doc.pk).update(status=SpecDoc.STATUS_PENDING, error="")
	return numbers


def start_worker():
	subprocess.Popen(
		[sys.executable, str(Path(settings.BASE_DIR) / "manage.py"), "spec_index", "--pending"],
		cwd=settings.BASE_DIR, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
	)


# ── 찾기 ──

LOW_TITLES = ("change history", "references", "foreword", "앞부분", "abbreviations", "definitions")


def normalize(q):
	"""K_offset·N_TA 처럼 아래 첨자를 밑줄로 쓴 것 → 문서에 적힌 Koffset·NTA."""
	return re.sub(r"\b([A-Za-z]{1,3})_\{?([A-Za-z0-9]+)\}?", r"\1\2", q)


def search(q, doc_id=None, kind="", limit=30):
	q = expand_query(normalize(q))
	qs = SpecChunk.objects.filter(doc__chunks__gt=0).select_related("doc")
	if doc_id:
		qs = qs.filter(doc_id=doc_id)
	if kind in (SpecChunk.KIND_CLAUSE, SpecChunk.KIND_TABLE, SpecChunk.KIND_ASN1):
		qs = qs.filter(kind=kind)
	# 절 번호로 바로 (6.3.2 / 5.1.1a)
	if re.fullmatch(r"[A-Z]?\d{1,2}(?:\.\w{1,4}){1,7}", q) and doc_id:
		hit = list(qs.filter(clause=q).order_by("order")[:limit]) or list(qs.filter(clause__startswith=q + ".").order_by("order")[:limit])
		if hit:
			return hit, q
	terms = _terms(q)
	if not terms:
		return [], q
	ident = any(re.search(r"[a-z][A-Z]|-r1\d|\w-\w", t) for t in terms)  # ta-Common, NTN-Config-r17 같은 이름
	if connection.vendor == "postgresql":
		expr = "to_tsvector('english', coalesce(tools_specchunk.clause, '') || ' ' || coalesce(tools_specchunk.title, '') || ' ' || tools_specchunk.text)"
		query = "websearch_to_tsquery('english', %s)"
		low = " OR ".join(f"tools_specchunk.title ILIKE '%%{t}%%'" for t in LOW_TITLES)
		rank = (f"(ts_rank_cd({expr}, {query}) + CASE WHEN to_tsvector('english', coalesce(tools_specchunk.title, '')) @@ {query} THEN 0.6 ELSE 0 END)"
				f" * CASE WHEN {low} THEN 0.2 ELSE 1 END"
				f" * CASE WHEN tools_specchunk.kind = 'asn1' THEN {1.4 if ident else 0.8} ELSE 1 END")

		def run(text):
			return list(qs.extra(where=[f"{expr} @@ {query}"], params=[text], select={"rank": rank}, select_params=[text, text]).order_by("-rank")[:limit])

		variants = [q]
		if 1 < len(terms) <= 6 and '"' not in q:
			for i in range(len(terms) - 1):
				variants.append(" ".join(terms[:i] + [terms[i] + terms[i + 1]] + terms[i + 2:]))
		best = {}
		for v in variants:
			for r in run(v):
				if r.id not in best or r.rank > best[r.id].rank:
					best[r.id] = r
		rows = sorted(best.values(), key=lambda r: -r.rank)[:limit]
		if len(rows) < 10 and all(len(t) >= 4 for t in terms):
			# 낱말 검색은 cellSpecificKoffset 안의 Koffset 같은 일부를 못 찾음 → 글자 그대로 한 번 더
			sub = qs
			for t in terms:
				sub = sub.filter(text__icontains=t)
			seen = {r.id for r in rows}
			rows += [r for r in sub.order_by("doc_id", "order")[:limit] if r.id not in seen][:limit - len(rows)]
		if not rows and len(terms) > 1:
			rows = run(" or ".join(terms))
		return rows, q
	# SQLite (로컬·시험): 모든 낱말 포함
	from django.db.models import Q
	for t in terms:
		qs = qs.filter(Q(text__icontains=t) | Q(title__icontains=t) | Q(clause__icontains=t))
	rows = list(qs[:400])

	def score(c):
		w = 0.2 if any(x in c.title.lower() for x in LOW_TITLES) else 1
		w *= (1.4 if ident else 0.8) if c.kind == SpecChunk.KIND_ASN1 else 1
		return -w * sum(c.title.lower().count(t.lower()) * 5 + c.text.lower().count(t.lower()) for t in terms)

	rows.sort(key=lambda c: (score(c), c.order))
	return rows[:limit], q


def _doc_label(d):
	return f"{d.kind} {d.number}" + (f" v{d.version}" if d.version else "")


def _chunk_json(c, terms):
	return {
		"id": c.id, "doc": c.doc_id, "doc_label": _doc_label(c.doc), "doc_title": c.doc.title, "zip": c.doc.zip_url,
		"kind": c.kind, "clause": c.clause, "title": c.title, "snippet": snippet(c.text, terms, 360),
	}


@require_GET
def search_view(request):
	q = (request.GET.get("q") or "").strip()
	if len(q) < 2:
		return JsonResponse({"error": "두 글자 이상 넣어 주세요."}, status=400)
	try:
		doc_id = int(request.GET.get("doc") or 0) or None
	except ValueError:
		doc_id = None
	rows, used = search(q, doc_id, request.GET.get("kind", ""))
	terms = _terms(used)
	return JsonResponse({"items": [_chunk_json(c, terms) for c in rows], "query": used})


@require_GET
def chunk_view(request, pk):
	"""절 전체 (같은 절의 조각을 이어 붙임) — 회원만."""
	if not request.user.is_authenticated:
		return JsonResponse({"error": "절 전체 글은 로그인한 회원만 볼 수 있어요. 미리보기와 공식 문서 링크는 누구나 써요."}, status=401)
	c = SpecChunk.objects.select_related("doc").filter(pk=pk).first()
	if not c:
		return JsonResponse({"error": "없는 조각이에요."}, status=404)
	if c.kind == SpecChunk.KIND_CLAUSE:
		parts = list(SpecChunk.objects.filter(doc=c.doc, clause=c.clause, title=c.title, kind=SpecChunk.KIND_CLAUSE).order_by("order")[:20])
	else:
		parts = [c]
	return JsonResponse({
		"id": c.id, "doc_label": _doc_label(c.doc), "kind": c.kind, "clause": c.clause, "title": c.title,
		"text": "\n".join(p.text for p in parts)[:60000],
		"cite": f"3GPP {c.doc.kind} {c.doc.number} V{c.doc.version}" + (f", clause {c.clause}" if c.clause else ""),
	})


def _docs_payload():
	try:
		index = specs.load_index()["specs"]
	except specs.SpecError:
		index = {}
	out = []
	for d in SpecDoc.objects.all():
		latest = specs.to_json(index[d.number])["latest"]["ver"] if d.number in index else ""
		out.append({
			"id": d.id, "number": d.number, "kind": d.kind, "title": d.title, "version": d.version, "release": d.release,
			"status": d.status, "progress": d.progress, "chunks": d.chunks, "error": d.error, "latest": latest,
			"outdated": bool(d.version and latest and latest != d.version),
		})
	return out


@require_GET
def docs_view(request):
	return JsonResponse({"docs": _docs_payload(), "running": bool(cache.get(RUN_LOCK)), "admin": request.user.is_superuser})


@login_required
@require_POST
def admin_view(request):
	"""관리자: 규격 넣기·새 버전 받기·빼기."""
	if not request.user.is_superuser:
		return JsonResponse({"error": "관리자만 할 수 있어요."}, status=403)
	action = request.POST.get("action", "")
	if action == "add":
		raw = re.findall(r"\d{2}\.\d{3}(?:-\d{1,2})?", request.POST.get("numbers", ""))
		numbers = list(dict.fromkeys(raw))[:40] if raw else []
		if not numbers:
			return JsonResponse({"error": "38.331 처럼 규격 번호를 넣어 주세요."}, status=400)
		queue(numbers)
	elif action == "default":
		queue(DEFAULT_SPECS)
	elif action == "update":
		queue([d["number"] for d in _docs_payload() if d["outdated"] or d["status"] == SpecDoc.STATUS_ERROR])
	elif action == "remove":
		SpecDoc.objects.filter(number=request.POST.get("number", "")).delete()
		return JsonResponse({"docs": _docs_payload(), "running": bool(cache.get(RUN_LOCK)), "admin": True})
	else:
		return JsonResponse({"error": "모르는 요청이에요."}, status=400)
	if not cache.get(RUN_LOCK):
		start_worker()
	return JsonResponse({"docs": _docs_payload(), "running": True, "admin": True})
