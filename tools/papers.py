"""논문 찾기 — 키워드로 논문 검색 (OpenAlex 전체 / arXiv 최신), 참고문헌·인용 꼬리 물기, 내 논문함.

- OpenAlex: 무료 공개 논문 DB. 키 없이도 되지만 서버 전체 하루 약 $0.1(검색 100번). OPENALEX_API_KEY(무료)를 넣으면 하루 $1(검색 약 1000번).
  검색은 1번에 $0.001, 목록(참고문헌·인용)은 $0.0001. 응답 헤더의 남은 예산을 기억해 두고 바닥나면 멈춤.
- 검색어는 통신 분야 약어를 넓혀서(NTN → NTN OR non-terrestrial OR satellite) 제목·초록에서 찾음.
- 관련도 상위 100개를 한 번에 받아서 인용순·최신순은 그 안에서 다시 정렬 (전체를 인용순으로 하면 엉뚱한 유명 논문이 섞임).
"""

import hashlib
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.http import JsonResponse
from django.views.decorators.http import require_GET, require_POST

from security.utils import client_ip

from .permissions import quota_multiplier, tier

API = "https://api.openalex.org/works"
UA = "MjGallery-Papers/1.0 (https://smjgallery.kr)"
PER_PAGE = 100
CACHE_SEARCH = 24 * 60 * 60
WINDOW = 10 * 60
LIMITS = {"anon": 15, "member": 60, "vip": 60, "admin": None}  # 10분에 외부 조회 몇 번 (캐시는 안 셈)
BUDGET_KEY = "papers:oa-remaining-usd"
MIN_BUDGET = 0.003
ARXIV_SOURCE = "S4306400194"
SUBFIELDS = "1705|2208|2202"  # 컴퓨터 네트워크·통신 / 전기전자 / 항공우주

# 약어·한국어 → 같이 찾을 말 (소문자 키)
SYNONYMS = {
	"ntn": ["NTN", '"non-terrestrial"', '"satellite communication"', '"satellite network"', '"satellite-terrestrial"', '"satellite internet"'],
	"non-terrestrial": ['"non-terrestrial"', "NTN"],
	"leo": ["LEO", '"low earth orbit"'],
	"geo": ["GEO", '"geostationary"'],
	"uav": ["UAV", "drone", '"unmanned aerial"'],
	"ris": ["RIS", '"reconfigurable intelligent surface"', "IRS", '"intelligent reflecting surface"'],
	"irs": ["IRS", '"intelligent reflecting surface"', "RIS"],
	"isac": ["ISAC", '"integrated sensing and communication"', "JCAS"],
	"jamming": ["jamming", "jammer", '"anti-jamming"'],
	"jammer": ["jammer", "jamming"],
	"pls": ['"physical layer security"', '"secrecy rate"'],
	"noma": ["NOMA", '"non-orthogonal multiple access"'],
	"rsma": ["RSMA", '"rate-splitting"'],
	"mimo": ["MIMO", '"multiple-input multiple-output"'],
	"mmwave": ["mmWave", '"millimeter wave"'],
	"thz": ["THz", "terahertz"],
	"swipt": ["SWIPT", '"wireless information and power transfer"'],
	"mec": ["MEC", '"mobile edge computing"', '"multi-access edge computing"'],
	"d2d": ["D2D", '"device-to-device"'],
	"v2x": ["V2X", '"vehicle-to-everything"'],
	"haps": ["HAPS", '"high altitude platform"'],
	"drl": ["DRL", '"deep reinforcement learning"'],
	"6g": ["6G"],
	"위성": ['"satellite communication"', '"satellite network"', "satellite"], "재밍": ["jamming", "jammer"], "드론": ["UAV", "drone"], "무인기": ["UAV", "drone"],
	"보안": ["security"], "물리계층보안": ['"physical layer security"'], "빔포밍": ["beamforming"], "강화학습": ['"reinforcement learning"'],
	"딥러닝": ['"deep learning"'], "최적화": ["optimization"], "채널": ["channel"], "간섭": ["interference"], "저궤도": ["LEO", '"low earth orbit"'],
	"전력": ["power"], "통신": ["communication"], "네트워크": ["network"], "센싱": ["sensing"], "추정": ["estimation"],
}
# 여러 단어짜리 표현 (먼저 묶음)
PHRASES = ["physical layer security", "reconfigurable intelligent surface", "intelligent reflecting surface", "integrated sensing and communication",
		   "non terrestrial", "low earth orbit", "deep reinforcement learning", "reinforcement learning", "deep learning", "beam forming",
		   "channel estimation", "resource allocation", "power allocation", "secrecy rate", "edge computing", "federated learning", "anti jamming"]

VENUES = {
	"twc": ("IEEE TWC", ["S63459445"]), "jsac": ("IEEE JSAC", ["S90422530"]), "tcom": ("IEEE TCOM", ["S196647941"]),
	"tvt": ("IEEE TVT", ["S10936095"]), "wcl": ("IEEE WCL", ["S2500830676"]), "coml": ("IEEE Comm. Letters", ["S147316732"]),
	"iotj": ("IEEE IoT-J", ["S2480266640"]), "tifs": ("IEEE TIFS", ["S61310614"]), "taes": ("IEEE TAES", ["S193624734"]),
	"comst": ("IEEE COMST", ["S23688054"]), "tmc": ("IEEE TMC", ["S69141925"]), "wcm": ("IEEE Wireless Comm.", ["S146764194"]),
	"net": ("IEEE Network", ["S186584794"]), "ojcoms": ("IEEE OJ-COMS", ["S4210202420"]), "access": ("IEEE Access", ["S2485537415"]),
	"globecom": ("GLOBECOM", ["S4363608563", "S4210205019"]), "icc": ("ICC", ["S4306419201"]), "wcnc": ("WCNC", ["S4210195247"]),
	"vtc": ("VTC", ["S4210185404", "S7407087783", "S7407088007"]), "infocom": ("INFOCOM", ["S7407087743"]),
	"arxiv": ("arXiv", [ARXIV_SOURCE]),
}
SORTS = {"relevance", "cited", "recent"}
SELECT = ",".join(["id", "doi", "ids", "title", "publication_year", "publication_date", "type", "cited_by_count", "referenced_works_count",
				   "authorships", "primary_location", "locations", "open_access", "best_oa_location", "biblio", "abstract_inverted_index"])
ARXIV_ID = re.compile(r"arxiv\.org/(?:abs|pdf)/([0-9]{4}\.[0-9]{4,5}|[a-z\-]+(?:\.[A-Z]{2})?/[0-9]{7})", re.I)
ARXIV_DOI = re.compile(r"10\.48550/arxiv\.(.+)$", re.I)


class PaperError(Exception):
	def __init__(self, message, status=400):
		super().__init__(message)
		self.status = status


# ── 검색어 ──

def build_query(raw, expand=True):
	"""(불리언 검색어, 설명용 묶음 [(입력, [같이 찾는 말])]). AND·OR·따옴표를 직접 쓰면 그대로."""
	raw = " ".join((raw or "").replace(",", " ").split())[:300]
	if not raw:
		return "", []
	if re.search(r'\b(AND|OR|NOT)\b|"', raw):
		return raw, [(raw, [])]
	text = raw.lower().replace("-", " ")
	tokens = []
	for ph in PHRASES:
		if ph in text:
			tokens.append(ph)
			text = text.replace(ph, " ")
	tokens += [t for t in text.split() if t]
	groups, parts = [], []
	for t in tokens:
		key = t.replace(" ", "-") if t.replace(" ", "-") in SYNONYMS else t.replace(" ", "")
		syn = SYNONYMS.get(key) if expand else None
		if not syn and not expand and re.search(r"[가-힣]", t):
			syn = SYNONYMS.get(key)  # 한국어는 넓히기를 꺼도 영어로 바꿈
		if syn:
			parts.append("(" + " OR ".join(syn) + ")" if len(syn) > 1 else syn[0])
			groups.append((t, [s.strip('"') for s in syn]))
		else:
			term = f'"{t}"' if " " in t else t
			parts.append(term)
			groups.append((t, []))
	return " AND ".join(parts), groups


# ── OpenAlex ──

def _remember_budget(headers):
	left = headers.get("X-RateLimit-Remaining-USD") or headers.get("x-ratelimit-remaining-usd")
	if left is not None:
		try:
			cache.set(BUDGET_KEY, float(left), 60 * 60)
		except ValueError:
			pass


def _openalex(params):
	left = cache.get(BUDGET_KEY)
	if left is not None and left < MIN_BUDGET:
		raise PaperError("오늘 쓸 수 있는 논문 검색량을 다 썼어요. 내일(한국 시간 오전 9시) 다시 열려요.", 503)
	key = getattr(settings, "OPENALEX_API_KEY", "")
	if key:
		params = {**params, "api_key": key}
	url = API + "?" + urllib.parse.urlencode(params)
	req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
	try:
		with urllib.request.urlopen(req, timeout=15) as res:
			_remember_budget(res.headers)
			return json.loads(res.read().decode("utf-8"))
	except urllib.error.HTTPError as exc:
		_remember_budget(exc.headers or {})
		if exc.code == 429:
			raise PaperError("논문 DB 사용량이 많아서 잠시 막혔어요. 조금 뒤에 다시 해 주세요.", 503)
		if exc.code == 400:
			raise PaperError("검색어를 알아듣지 못했어요. 괄호·따옴표를 확인해 주세요.", 400)
		raise PaperError("논문 DB 가 응답하지 않아요. 잠시 뒤 다시 시도해 주세요.", 502)
	except (OSError, ValueError):
		raise PaperError("논문 DB 에 연결하지 못했어요. 잠시 뒤 다시 시도해 주세요.", 502)


def _abstract(inv):
	if not inv:
		return ""
	pos = {}
	for word, idxs in inv.items():
		for i in idxs:
			pos[i] = word
	text = " ".join(pos[i] for i in sorted(pos))
	return text[:4000]


def _arxiv_of(w):
	m = ARXIV_DOI.search(((w.get("ids") or {}).get("doi") or w.get("doi") or ""))
	if m:
		return re.sub(r"v\d+$", "", m.group(1))
	for loc in [w.get("primary_location") or {}] + (w.get("locations") or []):
		for url in (loc.get("landing_page_url") or "", loc.get("pdf_url") or ""):
			m = ARXIV_ID.search(url)
			if m:
				return re.sub(r"v\d+$", "", m.group(1))
	return ""


def normalize(w):
	src = ((w.get("primary_location") or {}).get("source") or {})
	doi = (w.get("doi") or "").replace("https://doi.org/", "")
	arxiv = _arxiv_of(w)
	if doi.lower().startswith("10.48550/arxiv."):
		doi = ""  # arXiv 가 붙인 DOI 는 출판 DOI 가 아님
	bib = w.get("biblio") or {}
	oa = w.get("best_oa_location") or {}
	authors = [((a.get("author") or {}).get("display_name") or "").strip() for a in (w.get("authorships") or [])]
	authors = [a for a in authors if a]
	venue = src.get("display_name") or ""
	vtype = src.get("type") or ""
	if src.get("id", "").endswith(ARXIV_SOURCE):
		venue, vtype = "arXiv", "repository"
	date = w.get("publication_date") or ""
	pages = "-".join(p for p in (bib.get("first_page"), bib.get("last_page")) if p)
	return {
		"id": (w.get("id") or "").rsplit("/", 1)[-1],
		"title": " ".join(re.sub(r"<[^>]+>", "", w.get("title") or "").split()),
		"year": w.get("publication_year"),
		"date": date,
		"type": w.get("type") or "",
		"venue": venue,
		"venue_type": vtype,  # journal / conference / repository
		"publisher": src.get("host_organization_name") or "",
		"authors": authors[:15],
		"author_count": len(authors),
		"cited_by": w.get("cited_by_count") or 0,
		"refs": w.get("referenced_works_count") or 0,
		"abstract": _abstract(w.get("abstract_inverted_index")),
		"doi": doi,
		"arxiv": arxiv,
		"is_oa": bool((w.get("open_access") or {}).get("is_oa")),
		"pdf": oa.get("pdf_url") or (f"https://arxiv.org/pdf/{arxiv}" if arxiv else ""),
		"url": f"https://doi.org/{doi}" if doi else (f"https://arxiv.org/abs/{arxiv}" if arxiv else (oa.get("landing_page_url") or "")),
		"volume": bib.get("volume") or "",
		"issue": bib.get("issue") or "",
		"pages": pages,
	}


def _filters(opts, boolean):
	f = [f"title_and_abstract.search:{boolean}"] if not opts.get("body") else []
	f.append("type:article|preprint|review|letter")
	if opts.get("from_year"):
		f.append(f"from_publication_date:{opts['from_year']}-01-01")
	if opts.get("to_year"):
		f.append(f"to_publication_date:{opts['to_year']}-12-31")
	if opts.get("oa"):
		f.append("open_access.is_oa:true")
	if opts.get("field", True) and not opts.get("venues"):
		f.append(f"primary_topic.subfield.id:{SUBFIELDS}")
	ids = [sid for v in opts.get("venues") or [] for sid in VENUES.get(v, ("", []))[1]]
	if ids:
		f.append("primary_location.source.id:" + "|".join(ids))
	return ",".join(f)


def _sort(items, how):
	if how == "cited":
		return sorted(items, key=lambda i: -i["cited_by"])
	if how == "recent":
		return sorted(items, key=lambda i: i["date"] or "", reverse=True)
	return items


def search_openalex(opts):
	boolean, groups = build_query(opts["q"], opts.get("expand", True))
	if not boolean:
		raise PaperError("검색어를 넣어 주세요.")
	params = {"filter": _filters(opts, boolean), "per-page": PER_PAGE, "page": opts.get("page", 1), "select": SELECT, "sort": "relevance_score:desc"}
	if opts.get("body"):
		params["search"] = boolean
	data = _openalex(params)
	items = [normalize(w) for w in data.get("results") or []]
	items = [i for i in items if i["title"]]
	return {"total": (data.get("meta") or {}).get("count") or 0, "items": items, "query": boolean, "groups": groups, "has_more": opts.get("page", 1) * PER_PAGE < ((data.get("meta") or {}).get("count") or 0)}


def related(work_id, kind):
	"""kind = refs (이 논문이 인용한 것) / citedby (이 논문을 인용한 것). 인용 많은 순."""
	if not re.fullmatch(r"W\d{3,12}", work_id or ""):
		raise PaperError("논문 번호가 이상해요.")
	flt = f"cited_by:{work_id}" if kind == "refs" else f"cites:{work_id}"
	data = _openalex({"filter": flt, "per-page": PER_PAGE, "sort": "cited_by_count:desc", "select": SELECT})
	items = [i for i in (normalize(w) for w in data.get("results") or []) if i["title"]]
	return {"total": (data.get("meta") or {}).get("count") or 0, "items": items, "query": "", "groups": [], "has_more": False}


# ── arXiv 최신 ──

def search_arxiv(opts):
	boolean, groups = build_query(opts["q"], opts.get("expand", True))
	if not boolean:
		raise PaperError("검색어를 넣어 주세요.")
	# OpenAlex 불리언 → arXiv 문법 (각 말에 all: 붙이기)
	q = re.sub(r'("[^"]+"|[^\s()]+)', lambda m: m.group(1) if m.group(1) in ("AND", "OR", "NOT") else f"all:{m.group(1)}", boolean)
	q = q.replace("NOT", "ANDNOT")
	if opts.get("field", True):
		q = f"({q}) AND (cat:eess.SP OR cat:cs.IT OR cat:cs.NI OR cat:eess.SY OR cat:cs.CR)"
	start = (opts.get("page", 1) - 1) * 50
	url = "https://export.arxiv.org/api/query?" + urllib.parse.urlencode({"search_query": q, "start": start, "max_results": 50, "sortBy": "submittedDate", "sortOrder": "descending"})
	req = urllib.request.Request(url, headers={"User-Agent": UA})
	try:
		with urllib.request.urlopen(req, timeout=30) as res:  # arXiv API 는 가끔 느림
			raw = res.read()
	except OSError:
		raise PaperError("arXiv 에 연결하지 못했어요. 잠시 뒤 다시 시도해 주세요.", 502)
	ns = {"a": "http://www.w3.org/2005/Atom", "x": "http://arxiv.org/schemas/atom", "o": "http://a9.com/-/spec/opensearch/1.1/"}
	try:
		root = ET.fromstring(raw)
	except ET.ParseError:
		raise PaperError("arXiv 응답을 읽지 못했어요.", 502)
	total = int(root.findtext("o:totalResults", "0", ns) or 0)
	items = []
	for e in root.findall("a:entry", ns):
		eid = e.findtext("a:id", "", ns)
		if "/abs/" not in eid:
			continue
		aid = re.sub(r"v\d+$", "", eid.split("/abs/")[-1])
		date = (e.findtext("a:published", "", ns) or "")[:10]
		doi = (e.findtext("x:doi", "", ns) or "").strip()
		jref = " ".join((e.findtext("x:journal_ref", "", ns) or "").split())
		items.append({
			"id": "", "title": " ".join((e.findtext("a:title", "", ns) or "").split()), "year": int(date[:4]) if date[:4].isdigit() else None,
			"date": date, "type": "preprint", "venue": jref or "arXiv", "venue_type": "repository", "publisher": "arXiv",
			"authors": [" ".join((a.findtext("a:name", "", ns) or "").split()) for a in e.findall("a:author", ns)][:15],
			"author_count": len(e.findall("a:author", ns)), "cited_by": None, "refs": None,
			"abstract": " ".join((e.findtext("a:summary", "", ns) or "").split())[:4000],
			"doi": doi, "arxiv": aid, "is_oa": True, "pdf": f"https://arxiv.org/pdf/{aid}", "url": f"https://arxiv.org/abs/{aid}",
			"volume": "", "issue": "", "pages": "", "category": (e.find("x:primary_category", ns).get("term") if e.find("x:primary_category", ns) is not None else ""),
		})
	return {"total": total, "items": items, "query": q, "groups": groups, "has_more": start + 50 < total}


# ── 화면에서 부르는 API ──

def _count(request):
	limit = LIMITS[tier(request.user)]
	if limit is None:
		return False
	limit *= quota_multiplier(request.user)
	who = f"u{request.user.id}" if request.user.is_authenticated else f"ip{client_ip(request)}"
	key = f"papers-rate:{who}"
	now = time.time()
	bucket = cache.get(key)
	if not bucket or now - bucket["start"] >= WINDOW:
		bucket = {"start": now, "count": 0}
	if bucket["count"] >= limit:
		return True
	bucket["count"] += 1
	cache.set(key, bucket, max(1, int(bucket["start"] + WINDOW - now)))
	return False


def _opts(get):
	def year(v):
		return int(v) if (v or "").isdigit() and 1900 <= int(v) <= 2100 else None

	def flag(name, default):
		v = get.get(name)
		return default if v is None else v in ("1", "true", "on")

	try:
		page = max(1, min(20, int(get.get("page") or 1)))
	except ValueError:
		page = 1
	return {
		"q": (get.get("q") or "").strip()[:300], "source": "arxiv" if get.get("source") == "arxiv" else "openalex",
		"from_year": year(get.get("from")), "to_year": year(get.get("to")), "oa": flag("oa", False), "body": flag("body", False),
		"field": flag("field", True), "expand": flag("expand", True), "page": page,
		"venues": [v for v in (get.get("venues") or "").split(",") if v in VENUES][:12],
		"sort": get.get("sort") if get.get("sort") in SORTS else "relevance",
	}


@require_GET
def search_view(request):
	rel = request.GET.get("rel") or ""
	opts = _opts(request.GET)
	if rel:
		kind, _, wid = rel.partition(":")
		key = f"papers:rel:{kind}:{wid}"
	else:
		if len(opts["q"]) < 2:
			return JsonResponse({"error": "검색어를 두 글자 이상 넣어 주세요."}, status=400)
		key = "papers:s:" + hashlib.sha1(json.dumps({k: v for k, v in opts.items() if k != "sort"}, sort_keys=True).encode()).hexdigest()
	data = cache.get(key)
	if data is None:
		if _count(request):
			return JsonResponse({"error": "검색이 너무 잦아요. 10분 뒤 다시 해 주세요."}, status=429)
		try:
			if rel:
				data = related(wid, "refs" if kind == "refs" else "citedby")
			elif opts["source"] == "arxiv":
				data = search_arxiv(opts)
			else:
				data = search_openalex(opts)
		except PaperError as exc:
			return JsonResponse({"error": str(exc)}, status=exc.status)
		cache.set(key, data, CACHE_SEARCH)
	if not rel and opts["source"] == "openalex":
		data = {**data, "items": _sort(data["items"], opts["sort"])}
	return JsonResponse({**data, "venues": {k: v[0] for k, v in VENUES.items()}})


# ── 내 논문함 ──

def _paper_json(p):
	return {"id": p.id, "key": p.key, "data": p.data, "status": p.status, "starred": p.starred, "note": p.note, "created": p.created_at.isoformat()}


@login_required
def shelf_list(request):
	from .models import SavedPaper

	return JsonResponse({"items": [_paper_json(p) for p in SavedPaper.objects.filter(user=request.user)]})


@login_required
@require_POST
def shelf_save(request):
	from .models import SavedPaper

	try:
		body = json.loads(request.body or b"{}")
		data = body["data"]
		assert isinstance(data, dict) and data.get("title")
	except (ValueError, KeyError, AssertionError):
		return JsonResponse({"error": "논문 정보가 이상해요."}, status=400)
	key = (data.get("doi") or "").lower() or (f"arxiv:{data['arxiv']}" if data.get("arxiv") else "") or data.get("id") or data["title"].lower()[:200]
	if SavedPaper.objects.filter(user=request.user).count() >= 1000 and not SavedPaper.objects.filter(user=request.user, key=key).exists():
		return JsonResponse({"error": "논문함은 1000편까지 담을 수 있어요."}, status=400)
	keep = ("id", "title", "year", "date", "type", "venue", "venue_type", "publisher", "authors", "author_count", "cited_by", "refs", "abstract", "doi", "arxiv", "is_oa", "pdf", "url", "volume", "issue", "pages")
	clean = {k: data.get(k) for k in keep}
	clean["abstract"] = str(clean.get("abstract") or "")[:4000]
	paper, _ = SavedPaper.objects.update_or_create(user=request.user, key=key[:255], defaults={"data": clean})
	return JsonResponse({"item": _paper_json(paper)})


@login_required
@require_POST
def shelf_update(request, pk):
	from .models import SavedPaper

	paper = SavedPaper.objects.filter(user=request.user, pk=pk).first()
	if not paper:
		return JsonResponse({"error": "없는 논문이에요."}, status=404)
	try:
		body = json.loads(request.body or b"{}")
	except ValueError:
		return JsonResponse({"error": "요청이 이상해요."}, status=400)
	if body.get("delete"):
		paper.delete()
		return JsonResponse({"deleted": True})
	if body.get("status") in dict(SavedPaper.STATUS_CHOICES):
		paper.status = body["status"]
	if "starred" in body:
		paper.starred = bool(body["starred"])
	if "note" in body:
		paper.note = str(body["note"])[:2000]
	paper.save()
	return JsonResponse({"item": _paper_json(paper)})
