"""논문 찾기 3단계 — ✨AI 정리 (구조 요약 / 서론 흐름 분석 / 여러 논문 묶어 보기).

AI 한도는 다른 AI 기능과 같이 씀 (tools/ai.py). 공개 논문을 정리한 결과는 남의 개인 글이 아니라서
내용 해시로 30일 캐시해 두고, 캐시에 있으면 AI 를 다시 부르지 않음(횟수도 안 줄어듦).
"""

import hashlib
import json
import re

from django.core.cache import cache
from django.views.decorators.http import require_POST

from . import ai
from .ai_views import _json, _respond, _text
from .permissions import AI_LIMITS, tier

CACHE_AI = 30 * 24 * 60 * 60
SECTION_KEYS = ["abstract", "introduction", "related", "system", "problem", "proposed", "analysis", "simulation", "conclusion"]
# 글자 수가 모자랄 때 어느 섹션을 얼마나 남길지 (비율)
SHARE = {"abstract": 0.08, "introduction": 0.22, "related": 0.06, "system": 0.24, "problem": 0.12, "proposed": 0.14, "analysis": 0.04, "simulation": 0.07, "conclusion": 0.03}

FIELDS = [
	("one_line", "한 줄 요약"),
	("scenario", "시나리오·네트워크"),
	("channel", "채널 모델"),
	("threat", "공격·간섭 모델"),
	("objective", "목표·최적화 문제"),
	("method", "제안 기법"),
	("metrics", "성능 지표"),
	("baselines", "비교 기법"),
	("assumptions", "주요 가정"),
	("limitations", "한계·향후 과제"),
]

SUMMARY_SYSTEM = (
	"너는 무선통신·네트워크 분야 대학원생을 돕는 연구 조교야. 주어진 논문 발췌(제목·초록·서론·시스템 모델·문제·제안 기법·결과)를 읽고 "
	"논문의 구조를 정해진 칸에 정리해. 모든 칸은 한국어로 짧게(1~2문장, 120자 안팎) 쓰되 기술 용어·약어는 영어 그대로 써도 돼 "
	"(예: LEO 위성 상향링크, Rician fading, SCA, secrecy rate). 수식이 중요하면 짧은 LaTeX 로 적어도 돼. "
	"발췌에 없는 내용은 지어내지 말고 '언급 없음'이라고 써. 공격·간섭 모델이 없는 논문이면 '해당 없음'."
)
SUMMARY_TOOL = {
	"name": "paper_structure",
	"description": "논문 구조 정리",
	"input_schema": {
		"type": "object",
		"properties": {
			**{k: {"type": "string", "description": label} for k, label in FIELDS},
			"keywords": {"type": "array", "items": {"type": "string"}, "description": "영어 검색 키워드 3~6개 (관련 논문 더 찾기용)"},
		},
		"required": [k for k, _ in FIELDS] + ["keywords"],
	},
}

INTRO_SYSTEM = (
	"너는 영어 논문 쓰기를 가르치는 지도교수야. 주어진 논문 서론의 문단들(P1, P2, …)을 읽고 각 문단이 서론에서 하는 역할과 요지를 한국어로 정리해. "
	"역할은 background(분야 배경·중요성), prior(기존 연구 소개), gap(한계·문제 제기), this(이 논문이 한 일·기여), organization(논문 구성 안내) 중 하나. "
	"그다음 서론 전체 흐름을 '배경 → … → 구성' 처럼 한 줄로, 이 서론에서 배울 점 2~4개, 그리고 남의 문장을 베끼지 않고도 쓸 수 있는 "
	"일반적인 학술 연결 표현 패턴(예: 'Motivated by ..., we ...', 'To the best of our knowledge, ...') 4~8개를 뽑아. "
	"원문 문장을 그대로 길게 옮기지 마."
)
INTRO_TOOL = {
	"name": "intro_flow",
	"description": "서론 흐름 분석",
	"input_schema": {
		"type": "object",
		"properties": {
			"paragraphs": {"type": "array", "items": {"type": "object", "properties": {
				"n": {"type": "integer", "description": "문단 번호 (P 뒤 숫자)"},
				"role": {"type": "string", "enum": ["background", "prior", "gap", "this", "organization"]},
				"gist": {"type": "string", "description": "이 문단 요지 한 줄 (한국어)"},
			}, "required": ["n", "role", "gist"]}},
			"flow": {"type": "string", "description": "서론 전체 흐름 한 줄"},
			"lessons": {"type": "array", "items": {"type": "string"}, "description": "이 서론에서 배울 점"},
			"phrases": {"type": "array", "items": {"type": "string"}, "description": "재사용 가능한 일반 학술 표현 패턴 (영어, 짧게)"},
		},
		"required": ["paragraphs", "flow", "lessons", "phrases"],
	},
}

GROUP_SYSTEM = (
	"너는 무선통신 분야 연구 지도교수야. 여러 논문의 구조 정리(JSON)를 보고 관련 연구(literature review)를 쓰기 좋게 묶어 줘. "
	"비슷한 접근끼리 묶음을 만들고(논문 번호로), 묶음마다 공통점과 서로 다른 점을 한국어로 짧게. "
	"그리고 이 논문들이 공통으로 다루지 않은 '연구 공백'(가정이 강한 부분, 빠진 시나리오·지표 등)을 근거와 함께 2~5개 제안해. 지어내지 말고 주어진 정리만 근거로."
)
GROUP_TOOL = {
	"name": "related_work_map",
	"description": "논문 묶어 보기",
	"input_schema": {
		"type": "object",
		"properties": {
			"groups": {"type": "array", "items": {"type": "object", "properties": {
				"name": {"type": "string", "description": "묶음 이름 (예: DRL 기반 anti-jamming)"},
				"papers": {"type": "array", "items": {"type": "integer"}, "description": "논문 번호들 (1부터)"},
				"common": {"type": "string"},
				"differences": {"type": "string"},
			}, "required": ["name", "papers", "common", "differences"]}},
			"gaps": {"type": "array", "items": {"type": "object", "properties": {
				"gap": {"type": "string"}, "why": {"type": "string"},
			}, "required": ["gap", "why"]}},
			"overview": {"type": "string", "description": "전체 흐름 2~3문장"},
		},
		"required": ["groups", "gaps", "overview"],
	},
}


# 모델이 가끔 여러 칸을 한 칸 안에 "</a> <parameter name=\"b\">…" 처럼 이어 붙여 보냄 → 다시 나눔
_LEAK = re.compile(r'\s*(?:</[^>]*>\s*)*<parameter name="([^"]+)">\s*')


def repair(raw, keys):
	out = dict(raw)
	for k, v in raw.items():
		if isinstance(v, str) and '<parameter name="' in v:
			parts = _LEAK.split(v)
			out[k] = re.sub(r"\s*</[^>]*>\s*$", "", parts[0])
			for name, val in zip(parts[1::2], parts[2::2]):
				val = re.sub(r"\s*(?:</[^>]*>\s*)+$", "", val).strip()
				cur = str(out.get(name) or "").strip()
				if name in keys and val and (not cur or cur in ("언급 없음", "해당 없음")):
					out[name] = val
	return out


def _as_list(v):
	"""목록이어야 하는데 글자로 온 경우("a, b, c" 나 '["a","b"]')도 받아 줌."""
	if isinstance(v, list):
		return v
	if isinstance(v, str):
		try:
			parsed = json.loads(v)
			if isinstance(parsed, list):
				return parsed
		except ValueError:
			pass
		return [x.strip(' "\'') for x in re.split(r"[,;\n]", v)]
	return []


def _max_chars(user):
	t = tier(user)
	return AI_LIMITS.get(t, {}).get("max_chars", 4000)


def _fit(sections, budget):
	"""섹션 글을 정해진 글자 수 안으로 (섹션마다 비율대로, 남는 몫은 다른 섹션에)."""
	texts = {k: str(sections.get(k) or "").strip() for k in SECTION_KEYS}
	texts = {k: v for k, v in texts.items() if v}
	if sum(len(v) for v in texts.values()) <= budget:
		return texts
	share = {k: SHARE[k] for k in texts}
	total = sum(share.values())
	quota = {k: int(budget * share[k] / total) for k in texts}
	spare = sum(max(0, quota[k] - len(texts[k])) for k in texts)
	big = [k for k in texts if len(texts[k]) > quota[k]]
	for k in big:
		quota[k] += spare // max(1, len(big))
	return {k: v if len(v) <= quota[k] else v[:quota[k]] + " …(생략)" for k, v in texts.items()}


def _cached(kind, payload, user, chars, call):
	key = f"paper-ai:{kind}:" + hashlib.sha1(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
	hit = cache.get(key)
	if hit is not None:
		if tier(user) == "anon":
			raise ai.AIError("AI 기능은 로그인한 회원만 쓸 수 있어요.", 401)
		return {**hit, "cached": True}
	ai.check(user, chars)
	result = call()
	cache.set(key, result, CACHE_AI)
	return {**result, "cached": False}


@require_POST
def paper_ai(request):
	def run():
		data = _json(request)
		mode = data.get("mode")
		title = _text(data.get("title"), 300)
		if mode == "summary":
			budget = _max_chars(request.user) - len(title) - 200
			sec = _fit(data.get("sections") or {}, max(1500, budget))
			if not sec:
				raise ai.AIError("정리할 원문이 없어요.")
			content = f"제목: {title}\n\n" + "\n\n".join(f"## {k}\n{v}" for k, v in sec.items())

			def call():
				raw = repair(ai.call(request.user, "paper", system=SUMMARY_SYSTEM, tool=SUMMARY_TOOL, content=content, max_tokens=1500), {k for k, _ in FIELDS})
				return {"fields": [{"key": k, "label": label, "value": _text(raw.get(k), 400) or "언급 없음"} for k, label in FIELDS],
						"keywords": [_text(x, 60) for x in _as_list(raw.get("keywords"))[:6] if str(x).strip()]}
			return _cached("summary", {"t": title, "s": sec}, request.user, len(content), call)

		if mode == "intro":
			paras = [str(p or "").strip() for p in (data.get("paragraphs") or [])][:30]
			paras = [p for p in paras if p]
			if not paras:
				raise ai.AIError("서론 문단이 없어요.")
			budget = max(1500, _max_chars(request.user) - len(title) - 200)
			each = max(200, budget // len(paras))
			content = f"제목: {title}\n\n" + "\n\n".join(f"P{i + 1}: {p[:each]}" for i, p in enumerate(paras))

			def call():
				raw = ai.call(request.user, "paper", system=INTRO_SYSTEM, tool=INTRO_TOOL, content=content, max_tokens=2000)
				roles = {"background", "prior", "gap", "this", "organization"}
				out = []
				for p in raw.get("paragraphs") or []:
					if isinstance(p, dict) and isinstance(p.get("n"), int) and 1 <= p["n"] <= len(paras):
						out.append({"n": p["n"], "role": p.get("role") if p.get("role") in roles else "background", "gist": _text(p.get("gist"), 200)})
				return {"paragraphs": out, "flow": _text(raw.get("flow"), 300),
						"lessons": [_text(x, 250) for x in _as_list(raw.get("lessons"))[:5] if str(x).strip()],
						"phrases": [_text(x, 120) for x in _as_list(raw.get("phrases"))[:8] if str(x).strip()]}
			return _cached("intro", {"t": title, "p": [p[:each] for p in paras]}, request.user, len(content), call)

		if mode == "group":
			papers = [p for p in (data.get("papers") or [])[:8] if isinstance(p, dict)]
			if len(papers) < 2:
				raise ai.AIError("두 편 이상 정리한 다음 묶어 볼 수 있어요.")
			compact = [{"n": i + 1, "title": _text(p.get("title"), 200), **{f["key"]: _text(f.get("value"), 300) for f in (p.get("fields") or []) if isinstance(f, dict) and f.get("key")}}
					   for i, p in enumerate(papers)]
			content = json.dumps(compact, ensure_ascii=False)

			def call():
				raw = ai.call(request.user, "paper", system=GROUP_SYSTEM, tool=GROUP_TOOL, content=content, max_tokens=2000)
				groups = [{"name": _text(g.get("name"), 80), "papers": [n for n in (g.get("papers") or []) if isinstance(n, int) and 1 <= n <= len(papers)],
						   "common": _text(g.get("common"), 300), "differences": _text(g.get("differences"), 300)}
						  for g in (raw.get("groups") or [])[:6] if isinstance(g, dict) and g.get("name")]
				gaps = [{"gap": _text(g.get("gap"), 200), "why": _text(g.get("why"), 300)} for g in (raw.get("gaps") or [])[:5] if isinstance(g, dict) and g.get("gap")]
				return {"groups": groups, "gaps": gaps, "overview": _text(raw.get("overview"), 500)}
			return _cached("group", compact, request.user, len(content), call)

		raise ai.AIError("알 수 없는 요청이에요.")
	return _respond(request, run)
