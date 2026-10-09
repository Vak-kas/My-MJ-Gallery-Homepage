"""AI 기능 공통: 회원 등급별 하루 횟수·글자 수, 사이트 전체 하루 예산, 사용 기록, Claude 호출.

각 기능은 check() 로 먼저 막을지 정하고, call() 로 부른다. 입력 글과 결과는 저장하지 않는다.
"""

import json
import urllib.error
import urllib.request
from datetime import datetime, time
from decimal import Decimal

from django.conf import settings
from django.db.models import Sum
from django.utils import timezone

from .models import AIUsage
from .permissions import AI_LIMITS, TIER_LABELS, tier

API_URL = "https://api.anthropic.com/v1/messages"


class AIError(Exception):
	def __init__(self, message, status=400):
		super().__init__(message)
		self.message = message
		self.status = status


def _today_start():
	return timezone.make_aware(datetime.combine(timezone.localdate(), time.min))


def used_today(user):
	return AIUsage.objects.filter(user=user, ok=True, created_at__gte=_today_start()).count()


def spent_today():
	return AIUsage.objects.filter(created_at__gte=_today_start()).aggregate(s=Sum("cost_usd"))["s"] or Decimal("0")


def cost_of(input_tokens, output_tokens):
	usd = (input_tokens * settings.AI_PRICE_INPUT_PER_MTOK + output_tokens * settings.AI_PRICE_OUTPUT_PER_MTOK) / 1_000_000
	return Decimal(str(round(usd, 6)))


def status(user):
	"""화면에 보여 줄 남은 횟수 등."""
	t = tier(user)
	if t == "anon":
		return {"enabled": False, "tier": t, "reason": "login"}
	lim = AI_LIMITS[t]
	used = used_today(user)
	budget_over = t != "admin" and settings.AI_DAILY_BUDGET_USD > 0 and spent_today() >= Decimal(str(settings.AI_DAILY_BUDGET_USD))
	return {
		"enabled": bool(settings.ANTHROPIC_API_KEY) and not budget_over,
		"tier": t,
		"tier_label": TIER_LABELS[t],
		"per_day": lim["per_day"],
		"used": used,
		"remaining": None if lim["per_day"] is None else max(0, lim["per_day"] - used),
		"max_chars": lim["max_chars"],
		"reason": "" if settings.ANTHROPIC_API_KEY and not budget_over else ("budget" if budget_over else "off"),
	}


def check(user, chars=0):
	"""쓸 수 있으면 한도 정보를, 아니면 AIError."""
	t = tier(user)
	if t == "anon":
		raise AIError("AI 기능은 로그인한 회원만 쓸 수 있어요.", 401)
	if not settings.ANTHROPIC_API_KEY:
		raise AIError("AI 기능이 아직 설정되지 않았어요.", 503)
	lim = AI_LIMITS[t]
	if chars > lim["max_chars"]:
		raise AIError(f"한 번에 {lim['max_chars']:,}자까지 보낼 수 있어요. (지금 {chars:,}자)", 400)
	if t == "admin":
		return lim
	if lim["per_day"] is not None and used_today(user) >= lim["per_day"]:
		raise AIError(f"AI 기능은 하루 {lim['per_day']}번까지 쓸 수 있어요. 내일 다시 써 주세요.", 429)
	if settings.AI_DAILY_BUDGET_USD > 0 and spent_today() >= Decimal(str(settings.AI_DAILY_BUDGET_USD)):
		raise AIError("오늘 사이트 전체 AI 사용량이 다 찼어요. 내일 다시 써 주세요.", 503)
	return lim


def _post(body):
	req = urllib.request.Request(API_URL, data=json.dumps(body).encode(), method="POST", headers={
		"x-api-key": settings.ANTHROPIC_API_KEY,
		"anthropic-version": "2023-06-01",
		"content-type": "application/json",
	})
	with urllib.request.urlopen(req, timeout=40) as res:
		return json.loads(res.read().decode())


def call(user, feature, *, system, content, tool, max_tokens=900):
	"""정해진 도구(tool_use) 형식으로만 답을 받아 그 입력값(dict)을 돌려줌. 성공·실패 모두 기록."""
	body = {
		"model": settings.ANTHROPIC_MODEL,
		"max_tokens": max_tokens,
		"system": system,
		"tools": [tool],
		"tool_choice": {"type": "tool", "name": tool["name"]},
		"messages": [{"role": "user", "content": content}],
	}
	row = AIUsage(user=user if getattr(user, "is_authenticated", False) else None, feature=feature, tier=tier(user))
	try:
		data = _post(body)
	except urllib.error.HTTPError as exc:
		row.ok = False
		row.save()
		if exc.code == 429:
			raise AIError("AI 가 지금 바빠요. 잠시 뒤 다시 시도해 주세요.", 429)
		raise AIError("AI 답을 받지 못했어요. 잠시 뒤 다시 시도해 주세요.", 502)
	except (OSError, ValueError):
		row.ok = False
		row.save()
		raise AIError("AI 답을 받지 못했어요. 잠시 뒤 다시 시도해 주세요.", 502)
	usage = data.get("usage") or {}
	row.input_tokens = int(usage.get("input_tokens") or 0)
	row.output_tokens = int(usage.get("output_tokens") or 0)
	row.cost_usd = cost_of(row.input_tokens, row.output_tokens)
	result = next((b.get("input") for b in data.get("content", []) if b.get("type") == "tool_use"), None)
	row.ok = isinstance(result, dict)
	row.save()
	if not row.ok:
		raise AIError("AI 답의 형식이 이상해요. 다시 시도해 주세요.", 502)
	return result
