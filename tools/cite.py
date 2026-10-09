"""논문 인용 — DOI·arXiv·제목으로 서지 정보를 찾아 하나의 모양으로 정리. 인용 형식(BibTeX·APA…)은 화면(JS)이 만듦.

출처는 공개 API 두 곳:
- Crossref (api.crossref.org) — DOI 메타데이터·제목 검색. CROSSREF_MAILTO 를 넣으면 'polite pool' 로 감
- arXiv (export.arxiv.org) — 프리프린트
- 3GPP 포털 (www.3gpp.org/DynaReport/<번호>.htm) — TS·TR 규격의 제목·종류·릴리스별 버전과 날짜.
  BibTeX 모양은 martisak/3gpp-citations(MIT) 의 @techreport 형식을 따름
남의 서버에 부담을 주지 않게 결과는 오래 캐시하고, 사람마다 10분 횟수 제한.
"""

import difflib
import html
import json
import re
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

from django.conf import settings
from django.core.cache import cache
from django.http import JsonResponse

from security.utils import client_ip

from .permissions import quota_multiplier, tier

WINDOW = 10 * 60
LIMITS = {"anon": 20, "member": 60, "vip": 60, "admin": None}  # 10분에 몇 번 (캐시에 있는 건 안 셈)
CACHE_WORK = 30 * 24 * 60 * 60
CACHE_SEARCH = 24 * 60 * 60
MAX_QUERY = 300

DOI_RE = re.compile(r"(10\.\d{4,9}/[^\s\"<>]+)", re.I)
ARXIV_NEW = re.compile(r"(?:arxiv[:\s]*|arxiv\.org/(?:abs|pdf)/)?(\d{4}\.\d{4,5})(v\d+)?(?:\.pdf)?\s*$", re.I)
ARXIV_OLD = re.compile(r"(?:arxiv[:\s]*|arxiv\.org/(?:abs|pdf)/)?([a-z\-]+(?:\.[A-Z]{2})?/\d{7})(v\d+)?\s*$", re.I)
TAG_RE = re.compile(r"<[^>]+>")
# "TS 38.321", "3GPP TR 38.901 v17.0.0", "38321", "36.331-h20" 같은 것
GPP_RE = re.compile(r"^(?:3gpp\s*)?(?:(TS|TR)\s*)?(\d{2})\.?(\d{3})(?:\s*(?:v|version|-)\s*(\d{1,2}\.\d{1,2}\.\d{1,2}))?$", re.I)

CROSSREF_TYPES = {
	"journal-article": "article", "proceedings-article": "inproceedings", "book": "book", "monograph": "book",
	"edited-book": "book", "book-chapter": "incollection", "book-section": "incollection", "posted-content": "preprint",
	"dissertation": "thesis", "report": "report", "dataset": "misc",
}
MONTHS = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


class CiteError(Exception):
	def __init__(self, message, status=400):
		super().__init__(message)
		self.status = status


def classify(q):
	"""('doi'|'arxiv'|'search', 값)."""
	q = q.strip()
	m = DOI_RE.search(q)
	if m:
		return "doi", m.group(1).rstrip(".,;)").lower()
	m = GPP_RE.match(" ".join(q.split()))
	if m and (m.group(1) or "." in q or q.lower().startswith("3gpp") or q.isdigit()):
		return "3gpp", f"{m.group(2)}.{m.group(3)}" + (f"@{m.group(4)}" if m.group(4) else "")
	for rx in (ARXIV_NEW, ARXIV_OLD):
		m = rx.search(q)
		if m and (m.start() == 0 or "arxiv" in q.lower()):
			return "arxiv", m.group(1)
	return "search", " ".join(q.split())


def _clean(text):
	text = html.unescape(TAG_RE.sub("", str(text or "")))
	return " ".join(text.split())


def _get(url, accept="application/json"):
	mailto = getattr(settings, "CROSSREF_MAILTO", "")
	ua = "MjGallery-Cite/1.0 (https://smjgallery.kr" + (f"; mailto:{mailto}" if mailto else "") + ")"
	req = urllib.request.Request(url, headers={"Accept": accept, "User-Agent": ua})
	try:
		with urllib.request.urlopen(req, timeout=10) as res:
			return res.read()
	except urllib.error.HTTPError as exc:
		if exc.code == 404:
			raise CiteError("찾을 수 없어요. DOI·arXiv 번호를 다시 확인해 주세요.", 404)
		raise CiteError("논문 정보 서버가 지금 응답하지 않아요. 잠시 뒤 다시 시도해 주세요.", 502)
	except OSError:
		raise CiteError("논문 정보 서버에 연결하지 못했어요. 잠시 뒤 다시 시도해 주세요.", 502)


def _from_crossref(w):
	def date_parts(*keys):
		for k in keys:
			parts = (w.get(k) or {}).get("date-parts") or []
			if parts and parts[0] and parts[0][0]:
				return parts[0]
		return []

	dp = date_parts("published-print", "published-online", "issued", "created")
	authors = []
	for a in w.get("author") or []:
		if a.get("family"):
			authors.append({"family": _clean(a["family"]), "given": _clean(a.get("given"))})
		elif a.get("name"):
			authors.append({"family": _clean(a["name"]), "given": "", "literal": True})
	editors = [{"family": _clean(a.get("family") or a.get("name")), "given": _clean(a.get("given"))} for a in w.get("editor") or []]
	container = w.get("container-title") or []
	title = w.get("title") or []
	subtitle = w.get("subtitle") or []
	full_title = _clean(title[0]) if title else ""
	if subtitle and subtitle[0] and _clean(subtitle[0]).lower() not in full_title.lower():
		full_title += ": " + _clean(subtitle[0])
	kind = CROSSREF_TYPES.get(w.get("type"), "misc")
	doi = w.get("DOI") or ""  # 대소문자는 출판사가 준 그대로 (찾을 땐 구분 안 함)
	return {
		"type": kind,
		"title": full_title,
		"authors": authors,
		"editors": editors,
		"year": dp[0] if dp else None,
		"month": dp[1] if len(dp) > 1 else None,
		"container": _clean(container[0]) if container else "",
		"short_container": _clean((w.get("short-container-title") or [""])[0]),
		"volume": _clean(w.get("volume")),
		"issue": _clean(w.get("issue")),
		"pages": _clean(w.get("page")).replace("--", "-"),
		"article_number": _clean(w.get("article-number")),
		"publisher": _clean(w.get("publisher")),
		"doi": doi,
		"url": f"https://doi.org/{doi}" if doi else _clean(w.get("URL")),
		"isbn": _clean((w.get("ISBN") or [""])[0]),
		"arxiv": "",
		"source": "crossref",
	}


def by_doi(doi):
	key = f"cite:doi:{doi}"
	hit = cache.get(key)
	if hit:
		return hit, True
	raw = _get("https://api.crossref.org/works/" + urllib.parse.quote(doi, safe="/:;()"))
	try:
		item = _from_crossref(json.loads(raw)["message"])
	except (ValueError, KeyError, TypeError):
		raise CiteError("논문 정보를 읽지 못했어요.", 502)
	cache.set(key, item, CACHE_WORK)
	return item, False


ARXIV_NS = {"a": "http://www.w3.org/2005/Atom", "x": "http://arxiv.org/schemas/atom"}


def _arxiv_entries(raw):
	ns = ARXIV_NS
	out = []
	for entry in ET.fromstring(raw).findall("a:entry", ns):
		eid = entry.findtext("a:id", "", ns) or ""
		if entry.find("a:title", ns) is None or eid.endswith("/api/errors"):
			continue
		arxiv_id = re.sub(r"v\d+$", "", eid.split("/abs/")[-1])
		authors = []
		for a in entry.findall("a:author", ns):
			name = _clean(a.findtext("a:name", "", ns))
			if not name:
				continue
			given, _, family = name.rpartition(" ")
			authors.append({"family": family or name, "given": given})
		published = entry.findtext("a:published", "", ns)
		cat = entry.find("x:primary_category", ns)
		out.append({
			"type": "preprint",
			"title": _clean(entry.findtext("a:title", "", ns)),
			"authors": authors,
			"editors": [],
			"year": int(published[:4]) if published[:4].isdigit() else None,
			"month": int(published[5:7]) if published[5:7].isdigit() else None,
			"container": "arXiv",
			"short_container": "",
			"volume": "", "issue": "", "pages": "", "article_number": "",
			"publisher": "arXiv",
			"doi": (entry.findtext("x:doi", "", ns) or "").strip().lower(),
			"url": f"https://arxiv.org/abs/{arxiv_id}",
			"isbn": "",
			"arxiv": arxiv_id,
			"primary_class": cat.get("term", "") if cat is not None else "",
			"journal_ref": _clean(entry.findtext("x:journal_ref", "", ns)),
			"source": "arxiv",
		})
	return out


def by_arxiv(arxiv_id):
	key = f"cite:arxiv:{arxiv_id}"
	hit = cache.get(key)
	if hit:
		return hit, True
	raw = _get("https://export.arxiv.org/api/query?id_list=" + urllib.parse.quote(arxiv_id, safe="/.") + "&max_results=1", accept="application/atom+xml")
	try:
		entries = _arxiv_entries(raw)
	except ET.ParseError:
		raise CiteError("arXiv 정보를 읽지 못했어요.", 502)
	if not entries:
		raise CiteError("arXiv 에서 찾을 수 없어요. 번호를 다시 확인해 주세요.", 404)
	item = entries[0]
	cache.set(key, item, CACHE_WORK)
	return item, False


def _text(raw):
	s = raw.decode("utf-8", "replace")
	s = re.sub(r"<script.*?</script>|<style.*?</style>", " ", s, flags=re.S | re.I)
	return " ".join(html.unescape(TAG_RE.sub(" ", s)).split())


def by_3gpp(spec):
	"""spec = '38.321' 또는 '38.321@17.0.0' (버전 지정). 릴리스별 버전 목록도 함께 돌려줌."""
	number, _, want = spec.partition("@")
	key = f"cite:3gpp:{number}"
	base = cache.get(key)
	cached = base is not None
	if not cached:
		text = _text(_get(f"https://www.3gpp.org/DynaReport/{number.replace('.', '')}.htm", accept="text/html"))
		title = re.search(r"Title:\s*(.+?)\s+Status:", text)
		kind = re.search(r"Type:\s*Technical (specification|report)\s*\((TS|TR)\)", text, re.I)
		if not title or f"Specification #: {number}" not in text:
			raise CiteError(f"3GPP 규격 {number} 을(를) 찾지 못했어요. 번호를 확인해 주세요.", 404)
		versions = []
		for v, d in re.findall(r"\b(\d{1,2}\.\d{1,2}\.\d{1,2})\s+(\d{4}-\d{2}-\d{2})\b", text):
			if all(v != x["version"] for x in versions):
				versions.append({"version": v, "date": d})
		versions.sort(key=lambda x: tuple(int(n) for n in x["version"].split(".")), reverse=True)
		base = {
			"number": number,
			"title": title.group(1).strip(),
			"spec_type": (kind.group(2).upper() if kind else ("TR" if number.split(".")[1][0] == "9" else "TS")),
			"versions": versions[:120],
		}
		cache.set(key, base, 7 * 24 * 60 * 60)
	versions = base["versions"]
	pick = next((v for v in versions if v["version"] == want), None) if want else (versions[0] if versions else None)
	if want and not pick:
		raise CiteError(f"{number} 에 {want} 버전이 없어요.", 404)
	long_type = "Technical Specification (TS)" if base["spec_type"] == "TS" else "Technical Report (TR)"
	date = pick["date"] if pick else ""
	# 릴리스마다 최신 버전 하나씩 (고르기용)
	latest_per_release = []
	for v in versions:
		if all(v["version"].split(".")[0] != x["version"].split(".")[0] for x in latest_per_release):
			latest_per_release.append(v)
	item = {
		"type": "standard",
		"title": base["title"],
		"authors": [{"family": "3GPP", "given": "", "literal": True}],
		"editors": [],
		"year": int(date[:4]) if date else None,
		"month": int(date[5:7]) if date else None,
		"day": int(date[8:10]) if date else None,
		"container": "", "short_container": "", "volume": "", "issue": "", "pages": "", "article_number": "",
		"publisher": "3rd Generation Partnership Project (3GPP)",
		"institution": "3rd Generation Partnership Project (3GPP)",
		"number": f"{base['spec_type']} {number}",
		"spec_number": number,
		"spec_type": base["spec_type"],
		"report_type": long_type,
		"version": pick["version"] if pick else "",
		"release": int(pick["version"].split(".")[0]) if pick else None,
		"releases": latest_per_release[:12],
		"doi": "", "isbn": "", "arxiv": "",
		"url": f"https://www.3gpp.org/DynaReport/{number.replace('.', '')}.htm",
		"source": "3gpp",
	}
	return item, cached


def search(query):
	key = "cite:q:" + re.sub(r"\W+", "-", query.lower())[:200]
	hit = cache.get(key)
	if hit is not None:
		return hit, True
	params = urllib.parse.urlencode({
		"query.bibliographic": query, "rows": 6,
		"select": "DOI,title,subtitle,author,editor,issued,published-print,published-online,container-title,short-container-title,volume,issue,page,article-number,publisher,type,ISBN,URL",
	})
	raw = _get("https://api.crossref.org/works?" + params)
	try:
		items = [_from_crossref(w) for w in json.loads(raw)["message"]["items"]]
	except (ValueError, KeyError, TypeError):
		raise CiteError("검색 결과를 읽지 못했어요.", 502)
	try:
		raw = _get("https://export.arxiv.org/api/query?" + urllib.parse.urlencode({"search_query": f'ti:"{query}"', "max_results": 3}), accept="application/atom+xml")
		items += _arxiv_entries(raw)
	except (CiteError, ET.ParseError):
		pass  # arXiv 가 안 되면 Crossref 결과만
	q = query.lower()

	def score(i):
		t = i["title"].lower()
		return (t == q, difflib.SequenceMatcher(None, q, t).ratio())

	items = sorted((i for i in items if i["title"]), key=score, reverse=True)[:8]
	cache.set(key, items, CACHE_SEARCH)
	return items, False


def _count(request):
	"""외부 API 를 실제로 부를 때만 셈. 넘으면 True."""
	limit = LIMITS[tier(request.user)]
	if limit is None:
		return False
	limit *= quota_multiplier(request.user)
	who = f"u{request.user.id}" if request.user.is_authenticated else f"ip{client_ip(request)}"
	key = f"cite-rate:{who}"
	now = time.time()
	bucket = cache.get(key)
	if not bucket or now - bucket["start"] >= WINDOW:
		bucket = {"start": now, "count": 0}
	if bucket["count"] >= limit:
		return True
	bucket["count"] += 1
	cache.set(key, bucket, max(1, int(bucket["start"] + WINDOW - now)))
	return False


def lookup(request):
	q = (request.GET.get("q") or "").strip()[:MAX_QUERY]
	if len(q) < 3:
		return JsonResponse({"error": "DOI·arXiv 번호·3GPP 규격 번호나 논문 제목을 넣어 주세요."}, status=400)
	kind, value = classify(q)
	cache_key = {"doi": f"cite:doi:{value}", "arxiv": f"cite:arxiv:{value}", "3gpp": f"cite:3gpp:{value.partition('@')[0]}"}.get(kind) or "cite:q:" + re.sub(r"\W+", "-", value.lower())[:200]
	cached = cache.get(cache_key)
	if cached is None and _count(request):
		return JsonResponse({"error": "조회가 너무 잦아요. 10분 뒤 다시 시도해 주세요."}, status=429)
	try:
		if kind == "doi":
			items = [by_doi(value)[0]]
		elif kind == "arxiv":
			items = [by_arxiv(value)[0]]
		elif kind == "3gpp":
			items = [by_3gpp(value)[0]]
		else:
			items = search(value)[0]
	except CiteError as exc:
		return JsonResponse({"error": str(exc)}, status=exc.status)
	return JsonResponse({"kind": kind, "query": value, "items": items})
