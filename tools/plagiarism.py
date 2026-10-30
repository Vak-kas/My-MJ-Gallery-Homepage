"""표절 검사.

① 문서끼리 비교 — 전부 브라우저에서 (파일·글이 서버로 오지 않음), 누구나
② 공개 논문 비교 — 브라우저가 고른 문장 몇 개만 받아 OpenAlex 에서 비슷한 논문을 찾아 초록을 돌려줌, 회원
④ AI 말 바꾸기 탐지 — 두 글을 Claude 로 비교 (tools/ai.py 의 한도·예산), 회원
입력한 글은 저장하지 않는다.
"""

import hashlib
import json
import re
from datetime import date

from django.core.cache import cache
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_POST

from . import ai
from .papers import SELECT, PaperError, _openalex, normalize
from .permissions import PLAGIARISM_PAPER_LIMITS, PLAGIARISM_SENTENCES, tier

PAPERS_PER_SENTENCE = 5
SENTENCE_MIN, SENTENCE_MAX = 30, 400
ABSTRACT_MAX = 4000
CACHE_DAY = 24 * 60 * 60
WORD = re.compile(r"[\w]+", re.U)


def plagiarism(request):
	return render(request, "tools/plagiarism.html", {
		"paper_limit": PLAGIARISM_PAPER_LIMITS.get(tier(request.user)),
		"sentences": PLAGIARISM_SENTENCES,
	})


def _err(message, status=400):
	return JsonResponse({"error": message}, status=status)


def _used_key(user):
	return f"plagiarism:papers:{user.id}:{date.today().isoformat()}"


def papers_left(user):
	limit = PLAGIARISM_PAPER_LIMITS.get(tier(user))
	if limit is None:
		return None
	return max(0, limit - (cache.get(_used_key(user)) or 0))


def _search(sentence):
	"""문장 하나로 OpenAlex 검색 (하루 캐시)."""
	key = "plagiarism:oa:" + hashlib.sha256(sentence.encode()).hexdigest()[:24]
	hit = cache.get(key)
	if hit is not None:
		return hit
	# OpenAlex 검색어는 단어만 (따옴표·기호가 섞이면 검색 문법으로 읽힘)
	query = " ".join(WORD.findall(sentence))[:300]
	data = _openalex({"search": query, "per-page": PAPERS_PER_SENTENCE, "select": SELECT})
	items = []
	for w in data.get("results") or []:
		p = normalize(w)
		if p["title"] and p["abstract"]:
			items.append({k: p[k] for k in ("id", "title", "year", "venue", "url", "doi", "arxiv")} | {
				"authors": p["authors"][:4], "author_count": p["author_count"], "abstract": p["abstract"][:ABSTRACT_MAX],
			})
	cache.set(key, items, CACHE_DAY)
	return items


@require_POST
def papers_check(request):
	if not request.user.is_authenticated:
		return _err("공개 논문 비교는 로그인한 회원만 쓸 수 있어요.", 401)
	left = papers_left(request.user)
	if left == 0:
		return _err(f"공개 논문 비교는 하루 {PLAGIARISM_PAPER_LIMITS[tier(request.user)]}번까지예요. 내일 다시 써 주세요.", 429)
	try:
		data = json.loads(request.body or b"{}")
	except ValueError:
		return _err("요청 형식이 올바르지 않아요.")
	sentences = [" ".join(str(s).split())[:SENTENCE_MAX] for s in (data.get("sentences") or []) if isinstance(s, str)]
	sentences = [s for s in sentences if len(s) >= SENTENCE_MIN][:PLAGIARISM_SENTENCES]
	if not sentences:
		return _err(f"{SENTENCE_MIN}자 넘는 문장이 있어야 찾을 수 있어요.")
	papers, order = {}, []
	try:
		for i, sentence in enumerate(sentences):
			for p in _search(sentence):
				if p["id"] not in papers:
					papers[p["id"]] = {**p, "found_by": []}
					order.append(p["id"])
				papers[p["id"]]["found_by"].append(i)
	except PaperError as exc:
		return _err(str(exc), exc.status)
	if left is not None:
		cache.set(_used_key(request.user), (cache.get(_used_key(request.user)) or 0) + 1, CACHE_DAY)
	return JsonResponse({"papers": [papers[k] for k in order], "sentences": sentences, "left": papers_left(request.user)})


# ── ④ AI 말 바꾸기 탐지 ──
KINDS = ["말 바꾸기", "번역", "요약·압축", "순서 바꾸기", "아이디어 차용"]
VERDICTS = ["높음", "보통", "낮음", "거의 없음"]
AI_TOOL = {
	"name": "report_paraphrase",
	"description": "두 글 A, B 사이에서 그대로 복사가 아닌 '바꿔 쓴' 표절 의심 구간을 보고한다.",
	"input_schema": {
		"type": "object",
		"properties": {
			"verdict": {"type": "string", "enum": VERDICTS, "description": "B 를 바꿔 써서 A 를 만들었을(또는 그 반대) 가능성"},
			"score": {"type": "integer", "minimum": 0, "maximum": 100, "description": "의심 정도 0~100"},
			"summary": {"type": "string", "description": "판단 이유를 한국어 2~3문장으로"},
			"pairs": {
				"type": "array",
				"description": "의심 구간, 중요한 순서로 최대 8개 (없으면 빈 배열)",
				"items": {
					"type": "object",
					"properties": {
						"a_quote": {"type": "string", "description": "A 의 해당 부분을 원문 그대로 복사 (200자 이내, 고치지 말 것)"},
						"b_quote": {"type": "string", "description": "B 의 해당 부분을 원문 그대로 복사 (200자 이내, 고치지 말 것)"},
						"kind": {"type": "string", "enum": KINDS},
						"note": {"type": "string", "description": "어떻게 바꿨는지 한국어 한 문장 (인용 표시·출처가 있으면 그것도)"},
					},
					"required": ["a_quote", "b_quote", "kind", "note"],
				},
			},
		},
		"required": ["verdict", "score", "summary", "pairs"],
	},
}
AI_SYSTEM = (
	"너는 학술 글쓰기 표절 검토를 돕는다. 글자 그대로 같은 부분은 이미 기계가 찾았으니, "
	"단어를 동의어로 바꾸거나 어순·문장 구조만 바꾼 '말 바꾸기', 다른 언어를 옮긴 '번역', 내용을 줄인 '요약·압축', "
	"문단 순서만 바꾼 것, 독특한 주장·논리 흐름을 그대로 가져온 '아이디어 차용'을 찾는다. "
	"흔한 표현, 일반 상식, 용어 정의, 공식·표준 문구, 따옴표와 출처를 밝힌 인용은 표절로 보지 않는다(note 에 적는다). "
	"a_quote·b_quote 는 반드시 각 글에서 글자 그대로 복사한다. 확실하지 않으면 적게 보고한다. 결과는 판단 보조일 뿐이다."
)


def _norm(text):
	return re.sub(r"[\W_]+", "", text or "", flags=re.U).lower()


def _text(value, limit):
	return " ".join(str(value or "").split())[:limit]


@require_POST
def plagiarism_ai(request):
	try:
		data = json.loads(request.body or b"{}")
	except ValueError:
		return JsonResponse({"error": "요청 형식이 올바르지 않아요.", "quota": ai.status(request.user)}, status=400)
	a, b = str(data.get("a") or ""), str(data.get("b") or "")
	label_a, label_b = _text(data.get("label_a") or "A", 80), _text(data.get("label_b") or "B", 80)
	try:
		ai.check(request.user, len(a) + len(b))
		if len(a.strip()) < 50 or len(b.strip()) < 50:
			raise ai.AIError("두 글 모두 50자 넘게 있어야 비교할 수 있어요.")
		if _norm(a) == _norm(b):
			raise ai.AIError("두 글이 똑같아요. 위의 문서끼리 비교 결과로 충분해요.")
		content = f"글 A ({label_a}):\n<<<A\n{a}\nA>>>\n\n글 B ({label_b}):\n<<<B\n{b}\nB>>>"
		raw = ai.call(request.user, "plagiarism", system=AI_SYSTEM, tool=AI_TOOL, content=content, max_tokens=2000)
	except ai.AIError as exc:
		return JsonResponse({"error": exc.message, "quota": ai.status(request.user)}, status=exc.status)
	na, nb = _norm(a), _norm(b)
	pairs = []
	for p in (raw.get("pairs") or [])[:8]:
		if not isinstance(p, dict):
			continue
		qa, qb = _text(p.get("a_quote"), 240), _text(p.get("b_quote"), 240)
		if not qa or not qb:
			continue
		pairs.append({
			"a": qa, "b": qb, "kind": p.get("kind") if p.get("kind") in KINDS else "말 바꾸기", "note": _text(p.get("note"), 300),
			# AI 가 지어낸 인용이 아닌지: 공백·기호를 빼고 원문에 있는지
			"verified": bool(_norm(qa)) and _norm(qa) in na and bool(_norm(qb)) and _norm(qb) in nb,
		})
	try:
		score = max(0, min(100, int(raw.get("score") or 0)))
	except (TypeError, ValueError):
		score = 0
	return JsonResponse({
		"verdict": raw.get("verdict") if raw.get("verdict") in VERDICTS else "보통",
		"score": score, "summary": _text(raw.get("summary"), 500), "pairs": pairs, "quota": ai.status(request.user),
	})
