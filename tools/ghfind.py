"""깃허브 코드 찾기 — 키워드 또는 아이디어(✨AI 가 검색어로 바꿈)로 저장소를 찾고, ✨AI 가 내 아이디어와 맞는지 평가.

- GitHub REST 검색 API. 토큰 없이는 검색 분당 10번·README 시간당 60번 → GITHUB_TOKEN(권한 없는 무료 토큰)을 넣으면 분당 30번·시간당 5000번.
- 검색 결과 6시간, README 하루 캐시. 사람마다 10분 횟수 제한.
- 논문 코드: arXiv 번호·제목이 README·설명에 들어간 저장소.
"""

import base64
import hashlib
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from django.conf import settings
from django.core.cache import cache
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST

from security.utils import client_ip

from . import ai
from .ai_views import _json, _respond, _text
from .permissions import AI_LIMITS, quota_multiplier, tier

API = "https://api.github.com"
WINDOW = 10 * 60
LIMITS = {"anon": 10, "member": 40, "vip": 40, "admin": None}
SORTS = {"best": None, "stars": "stars", "updated": "updated"}
# 라이선스: 가져다 써도 되는지 한 줄 안내
LICENSE_NOTE = {
	"MIT": "자유롭게 (출처 표시)", "Apache-2.0": "자유롭게 (출처·변경 표시)", "BSD-3-Clause": "자유롭게 (출처 표시)", "BSD-2-Clause": "자유롭게 (출처 표시)",
	"ISC": "자유롭게 (출처 표시)", "Unlicense": "완전히 자유", "CC0-1.0": "완전히 자유", "MPL-2.0": "고친 파일은 공개",
	"GPL-2.0": "가져다 쓰면 내 코드도 GPL 공개", "GPL-3.0": "가져다 쓰면 내 코드도 GPL 공개", "AGPL-3.0": "서버로 써도 코드 공개 의무", "LGPL-3.0": "라이브러리로만 쓰면 비교적 자유",
}


class GhError(Exception):
	def __init__(self, message, status=400):
		super().__init__(message)
		self.status = status


def _get(path, accept="application/vnd.github+json"):
	headers = {"Accept": accept, "User-Agent": "MjGallery-GitHub/1.0 (https://smjgallery.kr)", "X-GitHub-Api-Version": "2022-11-28"}
	token = getattr(settings, "GITHUB_TOKEN", "")
	if token:
		headers["Authorization"] = f"Bearer {token}"
	req = urllib.request.Request(API + path, headers=headers)
	try:
		with urllib.request.urlopen(req, timeout=15) as res:
			return res.read()
	except urllib.error.HTTPError as exc:
		if exc.code in (403, 429) and (exc.headers or {}).get("X-RateLimit-Remaining") == "0":
			raise GhError("깃허브 검색 한도에 걸렸어요. 1분쯤 뒤에 다시 해 주세요.", 429)
		if exc.code == 404:
			raise GhError("찾을 수 없어요.", 404)
		if exc.code == 422:
			raise GhError("검색어를 깃허브가 알아듣지 못했어요. 단어를 바꿔 보세요.", 400)
		raise GhError("깃허브가 응답하지 않아요. 잠시 뒤 다시 해 주세요.", 502)
	except OSError:
		raise GhError("깃허브에 연결하지 못했어요.", 502)


def _repo(r):
	lic = (r.get("license") or {}).get("spdx_id") or ""
	if lic == "NOASSERTION":
		lic = "기타"
	return {
		"name": r.get("full_name", ""), "url": r.get("html_url", ""), "desc": (r.get("description") or "")[:400],
		"stars": r.get("stargazers_count", 0), "forks": r.get("forks_count", 0), "lang": r.get("language") or "",
		"license": lic, "license_note": LICENSE_NOTE.get(lic, "라이선스 없음 — 원칙상 가져다 쓰면 안 돼요, 저자에게 물어보기" if not lic else "라이선스 원문 확인"),
		"pushed": (r.get("pushed_at") or "")[:10], "created": (r.get("created_at") or "")[:10], "topics": (r.get("topics") or [])[:8],
		"archived": bool(r.get("archived")), "fork": bool(r.get("fork")), "avatar": (r.get("owner") or {}).get("avatar_url", ""),
		"homepage": r.get("homepage") or "", "issues": r.get("open_issues_count", 0),
	}


def search(q, sort="best", lang="", min_stars=0, since=""):
	q = " ".join((q or "").split())[:250]
	if not q:
		raise GhError("검색어를 넣어 주세요.")
	full = q
	if lang:
		full += f" language:{lang}"
	if min_stars:
		full += f" stars:>={min_stars}"
	if since:
		full += f" pushed:>={since}"
	key = "gh:s:" + hashlib.sha1(f"{full}|{sort}".encode()).hexdigest()
	hit = cache.get(key)
	if hit is not None:
		return hit, True
	params = {"q": full, "per_page": 30}
	if SORTS.get(sort):
		params.update(sort=SORTS[sort], order="desc")
	data = json.loads(_get("/search/repositories?" + urllib.parse.urlencode(params)))
	out = {"total": data.get("total_count", 0), "items": [_repo(r) for r in data.get("items") or []], "query": full}
	cache.set(key, out, 6 * 60 * 60)
	return out, False


REPO_NAME = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9\-]{0,38})/[A-Za-z0-9_.\-]{1,100}")


def valid_name(name):
	"""owner/repo 모양만 (../ 같은 경로 이동 막기)."""
	return bool(REPO_NAME.fullmatch(name or "")) and ".." not in name and not name.split("/")[1].startswith(".")


def readme(name):
	if not valid_name(name):
		raise GhError("저장소 이름이 이상해요.")
	key = f"gh:readme:{name}"
	hit = cache.get(key)
	if hit is not None:
		return hit, True
	try:
		raw = json.loads(_get(f"/repos/{name}/readme"))
		text = base64.b64decode(raw.get("content") or "").decode("utf-8", "replace")
	except GhError as exc:
		if exc.status != 404:
			raise
		text = ""
	# 그림·배지·HTML 태그 빼고 앞부분만
	text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)
	text = re.sub(r"<[^>]+>", "", text)
	text = re.sub(r"\n{3,}", "\n\n", text).strip()[:6000]
	cache.set(key, text, 24 * 60 * 60)
	return text, False


def _count(request):
	limit = LIMITS[tier(request.user)]
	if limit is None:
		return False
	limit *= quota_multiplier(request.user)
	who = f"u{request.user.id}" if request.user.is_authenticated else f"ip{client_ip(request)}"
	key = f"gh-rate:{who}"
	now = time.time()
	bucket = cache.get(key)
	if not bucket or now - bucket["start"] >= WINDOW:
		bucket = {"start": now, "count": 0}
	if bucket["count"] >= limit:
		return True
	bucket["count"] += 1
	cache.set(key, bucket, max(1, int(bucket["start"] + WINDOW - now)))
	return False


@ensure_csrf_cookie
def page(request):
	return render(request, "tools/github.html", {"has_token": bool(getattr(settings, "GITHUB_TOKEN", ""))})


@require_GET
def search_view(request):
	g = request.GET
	try:
		min_stars = max(0, min(100000, int(g.get("stars") or 0)))
	except ValueError:
		min_stars = 0
	since = g.get("since") or ""
	if since and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", since):
		since = ""
	lang = re.sub(r"[^\w+#.\- ]", "", g.get("lang") or "")[:30]
	queries = [q for q in (g.getlist("q") or []) if q.strip()][:5]
	if not queries:
		return JsonResponse({"error": "검색어를 넣어 주세요."}, status=400)
	merged, order, errors = {}, [], []
	for q in queries:
		try:
			key = "gh:s:" + hashlib.sha1(f"{q}|{g.get('sort')}".encode()).hexdigest()
			if cache.get(key) is None and _count(request):
				errors.append("검색이 너무 잦아요. 10분 뒤 다시 해 주세요.")
				break
			res, _ = search(q, g.get("sort") or "best", lang, min_stars, since)
		except GhError as exc:
			errors.append(str(exc))
			continue
		for i, r in enumerate(res["items"]):
			if r["name"] not in merged:
				merged[r["name"]] = {**r, "hits": 0, "best": i}
				order.append(r["name"])
			merged[r["name"]]["hits"] += 1
			merged[r["name"]]["best"] = min(merged[r["name"]]["best"], i)
	items = [merged[n] for n in order]
	if len(queries) > 1:  # 여러 검색어에서 같이 나온 것·위에 나온 것 먼저
		items.sort(key=lambda r: (-r["hits"], r["best"], -r["stars"]))
	if not items and errors:
		return JsonResponse({"error": errors[0]}, status=429 if "잦아요" in errors[0] or "한도" in errors[0] else 502)
	return JsonResponse({"items": items[:40], "queries": queries, "warning": errors[0] if errors else ""})


@require_GET
def readme_view(request):
	name = request.GET.get("name") or ""
	if not valid_name(name):
		return JsonResponse({"error": "저장소 이름이 이상해요."}, status=400)
	try:
		if cache.get(f"gh:readme:{name}") is None and _count(request):
			return JsonResponse({"error": "너무 잦아요. 10분 뒤 다시 해 주세요."}, status=429)
		text, _ = readme(name)
	except GhError as exc:
		return JsonResponse({"error": str(exc)}, status=exc.status)
	return JsonResponse({"name": name, "text": text})


QUERY_SYSTEM = (
	"너는 깃허브에서 오픈소스를 잘 찾는 개발자야. 사용자가 한국어로 말한 아이디어를 구현한 저장소를 찾기 위한 GitHub 저장소 검색어를 3~4개 만들어. "
	"규칙: 영어 키워드 2~4개로 짧게(너무 길면 결과가 0개), 서로 다른 표현·동의어로, 필요하면 language:python 같은 한정자 하나까지. "
	"따옴표·in:readme 는 꼭 필요할 때만. 그리고 사용자가 실제로 원하는 걸 한 줄로 정리해."
)
QUERY_TOOL = {"name": "gh_queries", "description": "깃허브 검색어", "input_schema": {"type": "object", "properties": {
	"queries": {"type": "array", "items": {"type": "string"}}, "intent": {"type": "string", "description": "원하는 것 한 줄 (한국어)"},
}, "required": ["queries", "intent"]}}

JUDGE_SYSTEM = (
	"너는 오픈소스를 골라 주는 시니어 개발자야. 사용자 아이디어와 후보 저장소들(설명·토픽·별·언어·라이선스·README 앞부분)을 보고 "
	"저장소마다 아이디어에 얼마나 맞는지 0~5점, 한 줄 이유(한국어), 바로 쓸 수 있는지/참고만 할지 판단해. "
	"README 에 근거가 없으면 추측하지 말고 '설명만으로는 불확실'이라고 해. 라이선스가 없거나 GPL 이면 그 점도 짚어. 마지막에 가장 추천할 저장소와 이유, 직접 만들 때의 팁을 한두 문장."
)
JUDGE_TOOL = {"name": "gh_judge", "description": "저장소 평가", "input_schema": {"type": "object", "properties": {
	"repos": {"type": "array", "items": {"type": "object", "properties": {
		"name": {"type": "string"}, "score": {"type": "integer"}, "reason": {"type": "string"}, "use": {"type": "string", "enum": ["바로 사용", "고쳐서 사용", "참고만", "안 맞음"]},
	}, "required": ["name", "score", "reason", "use"]}},
	"pick": {"type": "string", "description": "가장 추천하는 저장소 full_name (없으면 빈 문자열)"},
	"advice": {"type": "string"},
}, "required": ["repos", "pick", "advice"]}}


@require_POST
def ai_view(request):
	def run():
		data = _json(request)
		mode = data.get("mode")
		idea = _text(data.get("idea"), 1000)
		if len(idea) < 4:
			raise ai.AIError("아이디어를 조금 더 자세히 써 주세요.")
		if mode == "queries":
			key = "gh:aiq:" + hashlib.sha1(idea.encode()).hexdigest()
			hit = cache.get(key)
			if hit:
				if tier(request.user) == "anon":
					raise ai.AIError("AI 기능은 로그인한 회원만 쓸 수 있어요.", 401)
				return {**hit, "cached": True}
			ai.check(request.user, len(idea))
			raw = ai.call(request.user, "github", system=QUERY_SYSTEM, tool=QUERY_TOOL, content=f"아이디어: {idea}", max_tokens=500)
			qs = [" ".join(str(q).split())[:120] for q in (raw.get("queries") or []) if str(q).strip()][:4]
			if not qs:
				raise ai.AIError("검색어를 만들지 못했어요. 다시 해 주세요.", 502)
			out = {"queries": qs, "intent": _text(raw.get("intent"), 200)}
			cache.set(key, out, 7 * 24 * 60 * 60)
			return out
		if mode == "judge":
			names = [n for n in (data.get("repos") or []) if isinstance(n, dict) and valid_name(str(n.get("name") or ""))][:8]
			if not names:
				raise ai.AIError("평가할 저장소가 없어요.")
			blocks = []
			for r in names:
				try:
					text, _ = readme(r["name"])
				except GhError:
					text = ""
				blocks.append(f"### {r['name']}\n설명: {_text(r.get('desc'), 300)}\n토픽: {', '.join(r.get('topics') or [])}\n별 {r.get('stars')} · {r.get('lang')} · 라이선스 {r.get('license') or '없음'} · 마지막 수정 {r.get('pushed')}\nREADME:\n{text[:900]}")
			content = f"아이디어: {idea}\n\n후보 저장소:\n\n" + "\n\n".join(blocks)
			limit = AI_LIMITS.get(tier(request.user), {}).get("max_chars", 4000)
			if len(content) > limit:
				content = content[:limit]
			ai.check(request.user, len(content))
			raw = ai.call(request.user, "github", system=JUDGE_SYSTEM, tool=JUDGE_TOOL, content=content, max_tokens=1500)
			valid = {r["name"] for r in names}
			repos = [{"name": x["name"], "score": max(0, min(5, int(x.get("score") or 0))), "reason": _text(x.get("reason"), 300), "use": x.get("use") or "참고만"}
					 for x in (raw.get("repos") or []) if isinstance(x, dict) and x.get("name") in valid]
			return {"repos": repos, "pick": raw.get("pick") if raw.get("pick") in valid else "", "advice": _text(raw.get("advice"), 600)}
		raise ai.AIError("알 수 없는 요청이에요.")
	return _respond(request, run)
