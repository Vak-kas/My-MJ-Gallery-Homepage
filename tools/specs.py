"""📘 3GPP TS/TR 찾기.

3GPP '규격 현황표'(www.3gpp.org/dynareport?code=status-report.htm, 모든 규격 × 릴리스)를 하루에 한 번 받아
번호·제목·담당 작업반·릴리스별 최신 버전을 정리해 두고, 번호·제목 낱말로 찾음.
문서 파일은 3GPP 공식 주소(ftp/Specs/archive)로 바로 이어 줌 (이 사이트가 다시 배포하지 않음).
현황표는 5MB 라 받는 데 수십 초 걸릴 때가 있어서 요청 안에서 기다리지 않고, 저장해 둔 목록(없으면 코드에 넣어 둔
data/3gpp_specs.json.gz)으로 바로 답한 뒤 뒤에서 새로 받음. 손으로 새로 받기: manage.py specs_refresh
"""

import gzip
import html
import json
import re
import threading
import urllib.error
import urllib.request
from pathlib import Path

from django.core.cache import cache
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_GET

STATUS_URL = "https://www.3gpp.org/dynareport?code=status-report.htm"
USER_AGENT = "smjgallery.kr 3GPP spec finder (+https://smjgallery.kr/tools/specs/)"
INDEX_KEY = "specs:index:v1"
INDEX_SECONDS = 24 * 60 * 60
BACKUP_SECONDS = 30 * 24 * 60 * 60
MAX_RESULTS = 80

WG_NAMES = {
	"R1": "RAN1 · 물리 계층", "R2": "RAN2 · 무선 프로토콜", "R3": "RAN3 · 무선망 구조", "R4": "RAN4 · RF·성능", "R5": "RAN5 · 단말 시험",
	"RP": "RAN 총회", "S1": "SA1 · 서비스 요구", "S2": "SA2 · 시스템 구조", "S3": "SA3 · 보안", "S4": "SA4 · 코덱·미디어",
	"S5": "SA5 · 관리·과금", "S6": "SA6 · 응용", "SP": "SA 총회", "C1": "CT1 · 단말↔코어 신호", "C3": "CT3 · 망 연동",
	"C4": "CT4 · 코어 프로토콜", "C6": "CT6 · SIM·카드", "CP": "CT 총회",
}
SERIES = [
	("21", "용어·요구 사항 일반"), ("22", "서비스 요구"), ("23", "시스템 구조 (5GC 등)"), ("24", "단말↔코어 신호 (NAS)"),
	("25", "3G UTRA"), ("26", "코덱·미디어"), ("27", "데이터"), ("28", "관리 (OAM)"), ("29", "코어망 신호"),
	("31", "SIM·USIM"), ("32", "과금·관리"), ("33", "보안"), ("34", "단말 시험"), ("35", "보안 알고리즘"),
	("36", "4G LTE"), ("37", "여러 무선 기술 공통"), ("38", "5G NR"),
]
# 한국어·흔한 말 → 3GPP 제목에 나오는 말 (하나라도 맞으면 됨)
SYNONYMS = {
	"위성": ["satellite", "non-terrestrial", "ntn"], "비지상": ["non-terrestrial", "ntn", "satellite"], "ntn": ["non-terrestrial", "ntn", "satellite"],
	"측위": ["positioning", "location"], "위치": ["positioning", "location"], "인공지능": ["ai", "artificial intelligence", "machine learning"],
	"ai": ["ai", "artificial intelligence"], "ml": ["ml", "machine learning"], "사이드링크": ["sidelink"], "보안": ["security"],
	"핸드오버": ["handover", "mobility"], "이동성": ["mobility"], "빔": ["beam"], "채널": ["channel"], "채널모델": ["channel model"],
	"물리계층": ["physical layer"], "레드캡": ["redcap", "reduced capability"], "redcap": ["redcap", "reduced capability"],
	"에너지": ["energy", "power saving"], "절전": ["power saving", "energy"], "코어망": ["core network", "5gc", "5g system"],
	"슬라이싱": ["slicing", "slice"], "시험": ["test", "conformance"], "차량": ["v2x", "vehicle"], "드론": ["uav", "aerial"],
	"iot": ["iot", "machine type", "mtc"], "센싱": ["sensing", "isac"], "isac": ["sensing", "isac"], "6g": ["6g"],
	"rrc": ["rrc", "radio resource control"], "mac": ["mac", "medium access control"], "rlc": ["rlc", "radio link control"],
	"pdcp": ["pdcp", "packet data convergence"], "nas": ["nas", "non-access-stratum"], "rf": ["radio transmission", "rf"],
}


class SpecError(Exception):
	pass


def ver_code(ver):
	"""19.4.0 → j40 (3GPP 파일 이름 규칙: 10 이상은 a, b, c …)."""
	parts = ver.split(".")
	if len(parts) != 3 or not all(p.isdigit() for p in parts):
		return None
	return "".join(str(n) if n < 10 else chr(ord("a") + n - 10) for n in map(int, parts))


def doc_links(number, ver=None):
	series = number.split(".")[0]
	folder = f"https://www.3gpp.org/ftp/Specs/archive/{series}_series/{number}/"
	links = {"page": f"https://www.3gpp.org/DynaReport/{number.replace('.', '')}.htm", "folder": folder}
	code = ver_code(ver) if ver else None
	if code:
		links["zip"] = f"{folder}{number.replace('.', '')}-{code}.zip"
	return links


def parse_status(text):
	"""현황표 HTML → {번호: {...}}."""
	specs = {}
	for table in re.finditer(r'id="a3dyntab-(active|dead)(Rel-\d+|R99)"(.*?)</table>', text, re.S):
		state, rel_raw, body = table.groups()
		rel = "99" if rel_raw == "R99" else rel_raw.split("-")[1]
		for row in re.finditer(r"<tr[^>]*>(.*?)</tr>", body, re.S):
			cells = [html.unescape(re.sub(r"<[^>]+>", "", c)).strip() for c in re.findall(r"<td[^>]*>(.*?)</td>", row.group(1), re.S)]
			if len(cells) < 5 or not re.fullmatch(r"\d{2}\.\d{3}(?:-\d{1,2})?", cells[1]):
				continue
			kind, number, title, ver, wg = cells[:5]
			s = specs.setdefault(number, {"type": kind, "number": number, "title": title, "wg": wg, "rels": {}, "dead": True, "top": -1})
			s["rels"][rel] = ver
			if state == "active":
				s["dead"] = False
			rel_n = int(rel) if rel != "99" else 3  # R99 는 Rel-4 앞
			if rel_n > s["top"]:
				s["top"], s["title"], s["wg"], s["type"] = rel_n, title, wg, kind  # 가장 새 릴리스의 제목을 씀
	return specs


def _fetch_status():
	req = urllib.request.Request(STATUS_URL, headers={"User-Agent": USER_AGENT})
	# 3GPP 는 chunked 로 보내고 연결을 바로 안 닫아서 read(큰 수)는 끝까지 기다림 → 조금씩 끝(빈 조각)까지 읽음
	parts, size = [], 0
	with urllib.request.urlopen(req, timeout=40) as res:
		while size < 20 * 1024 * 1024:
			chunk = res.read1(256 * 1024)
			if not chunk:
				break
			parts.append(chunk)
			size += len(chunk)
			if b"</html>" in chunk[-4096:].lower():  # 문서 끝을 받았으면 연결이 닫히길 기다리지 않음
				break
	return b"".join(parts).decode("utf-8", "replace")


SNAPSHOT = Path(__file__).resolve().parent / "data" / "3gpp_specs.json.gz"


def _snapshot():
	"""코드에 같이 넣어 둔 목록 (처음 켰을 때나 3GPP 가 안 될 때)."""
	with gzip.open(SNAPSHOT, "rt", encoding="utf-8") as f:
		return json.load(f)


def refresh_index():
	"""3GPP 현황표를 받아 새 목록으로 바꿈. 성공하면 True. (받는 데 수십 초 걸릴 수 있어서 요청 밖에서 부름)"""
	try:
		specs = parse_status(_fetch_status())
	except (urllib.error.URLError, OSError, ValueError):
		return False
	if len(specs) < 500:
		return False
	data = {"specs": specs, "fetched": timezone.now().isoformat()}
	cache.set(INDEX_KEY, data, INDEX_SECONDS)
	cache.set(INDEX_KEY + ":backup", data, BACKUP_SECONDS)
	return True


def _refresh_later():
	# 10분에 한 번만 시도 (여러 요청·여러 프로세스가 동시에 받지 않게)
	if cache.add(INDEX_KEY + ":lock", 1, 10 * 60):
		threading.Thread(target=refresh_index, daemon=True).start()


def load_index():
	data = cache.get(INDEX_KEY)
	if data is not None:
		return data
	data = cache.get(INDEX_KEY + ":backup")
	if data is None:
		try:
			data = _snapshot()
		except (OSError, ValueError):
			raise SpecError("3GPP 규격 목록을 읽지 못했어요. 잠시 뒤 다시 해 주세요.")
	cache.set(INDEX_KEY, data, 60 * 60)  # 새 목록을 받는 동안 1시간 쓰고
	_refresh_later()  # 뒤에서 새로 받음
	return data


NUM_RE = re.compile(r"^(?:3gpp\s*)?(?:ts|tr)?\s*(\d{2})\.?(\d{3})(?:-(\d{1,2}))?$", re.I)


def _term_patterns(term):
	words = SYNONYMS.get(term.lower().replace(" ", ""), [term.lower()])
	pats = []
	for w in words:
		esc = re.escape(w)
		# 짧은 약어(MAC·RRC·AI)는 낱말 경계로만 — machine 안의 mac 같은 것 빼기
		pats.append(re.compile(rf"(?<![a-z0-9]){esc}(?![a-z0-9])" if len(w) <= 4 else esc, re.I))
	return pats


def search(specs, q, *, kind="", series="", wg="", rel="", dead=False):
	q = " ".join(q.split())[:100]
	m = NUM_RE.match(q.replace(" ", "")) if q else None
	if m:
		number = f"{m.group(1)}.{m.group(2)}" + (f"-{m.group(3)}" if m.group(3) else "")
		hits = [s for n, s in specs.items() if n == number or n.startswith(number + "-") or (not m.group(3) and n.startswith(number))]
		return sorted(hits, key=lambda s: s["number"])[:MAX_RESULTS], len(hits)
	terms = [t for t in re.split(r"[\s,]+", q) if t]
	groups = [_term_patterns(t) for t in terms]
	out = []
	for s in specs.values():
		if (kind and s["type"] != kind) or (series and not s["number"].startswith(series + ".")) or (wg and s["wg"] != wg):
			continue
		if rel and rel not in s["rels"]:
			continue
		if s["dead"] and not dead:
			continue
		hay = f"{s['title']} {s['number']}"
		if not all(any(p.search(hay) for p in pats) for pats in groups):
			continue
		score = s["top"] + (0 if s["dead"] else 50) + (5 if s["type"] == "TS" else 0)
		low = s["title"].lower()
		if q and q.lower() in low:
			score += 30
		if any(f"({t.lower()})" in low for t in terms):
			score += 10  # 제목 괄호 속 약어가 그대로 맞음: "Radio Resource Control (RRC)"
		if s["number"].startswith("38."):
			score += 3  # 5G NR 을 조금 먼저
		out.append((score, s))
	out.sort(key=lambda x: (-x[0], x[1]["number"]))
	return [s for _, s in out[:MAX_RESULTS]], len(out)


def _rel_key(r):
	return 3 if r == "99" else int(r)


def to_json(s):
	rels = sorted(s["rels"].items(), key=lambda kv: -_rel_key(kv[0]))
	latest_rel, latest_ver = rels[0]
	return {
		"type": s["type"], "number": s["number"], "title": s["title"], "wg": s["wg"], "wg_name": WG_NAMES.get(s["wg"], s["wg"]),
		"withdrawn": s["dead"],
		"latest": {"rel": latest_rel, "ver": latest_ver, **doc_links(s["number"], latest_ver)},
		"releases": [{"rel": r, "ver": v, "zip": doc_links(s["number"], v).get("zip")} for r, v in rels],
	}


def page(request):
	return render(request, "tools/specs.html", {
		"series": SERIES, "wgs": sorted(WG_NAMES.items()), "releases": [str(n) for n in range(21, 7, -1)],
	})


@require_GET
def search_view(request):
	g = request.GET
	kind = g.get("type", "") if g.get("type") in ("TS", "TR") else ""
	series = g.get("series", "") if re.fullmatch(r"\d{2}", g.get("series", "")) else ""
	wg = g.get("wg", "") if g.get("wg", "") in WG_NAMES else ""
	rel = g.get("rel", "") if re.fullmatch(r"\d{1,2}", g.get("rel", "")) else ""
	q = g.get("q", "")
	if not q.strip() and not (series or wg or rel):
		return JsonResponse({"error": "번호나 낱말을 넣거나, 시리즈·작업반·릴리스를 골라 주세요."}, status=400)
	try:
		data = load_index()
	except SpecError as exc:
		return JsonResponse({"error": str(exc)}, status=502)
	hits, total = search(data["specs"], q, kind=kind, series=series, wg=wg, rel=rel, dead=g.get("dead") == "1")
	return JsonResponse({"items": [to_json(s) for s in hits], "total": total, "count": len(data["specs"]), "fetched": data["fetched"]})
