from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.db.models import Count, Q, Sum
from django.db.models.functions import TruncDate
from django.utils import timezone

from tools import ai
from tools.models import AIUsage
from tools.permissions import AI_LIMITS, TIER_LABELS

from .common import admin_view

PERIODS = [(1, "오늘"), (7, "7일"), (30, "30일")]
KRW_PER_USD = 1400  # 화면에 보여 주는 원화 어림값용


def _krw(usd):
    return int(round(float(usd or 0) * KRW_PER_USD))


@admin_view
def ai_usage(request):
    from django.shortcuts import render

    try:
        days = int(request.GET.get("days", 7))
    except ValueError:
        days = 7
    days = days if days in dict(PERIODS) else 7
    start = ai._today_start() - timedelta(days=days - 1)
    rows = AIUsage.objects.filter(created_at__gte=start)
    sums = dict(input_tokens=Sum("input_tokens"), output_tokens=Sum("output_tokens"), cost=Sum("cost_usd"))
    total = rows.aggregate(calls=Count("id"), ok=Count("id", filter=Q(ok=True)), **sums)

    labels = dict(AIUsage.FEATURES)
    by_feature = [{**r, "label": labels.get(r["feature"], r["feature"]), "krw": _krw(r["cost"])}
                  for r in rows.values("feature").annotate(calls=Count("id"), **sums).order_by("-calls")]
    by_user = [{**r, "tier_label": TIER_LABELS.get(r["tier"], r["tier"]), "krw": _krw(r["cost"])}
               for r in rows.values("user__username", "tier").annotate(calls=Count("id"), **sums).order_by("-cost", "-calls")[:30]]

    # 30일 날짜별 비용 막대
    month_start = ai._today_start() - timedelta(days=29)
    daily = {r["day"]: r for r in AIUsage.objects.filter(created_at__gte=month_start)
             .annotate(day=TruncDate("created_at", tzinfo=timezone.get_current_timezone()))
             .values("day").annotate(calls=Count("id"), cost=Sum("cost_usd"))}
    bars = []
    peak = max([float(r["cost"] or 0) for r in daily.values()] + [0.0001])  # 가장 많이 쓴 날 = 100%
    for i in range(30):
        day = timezone.localdate() - timedelta(days=29 - i)
        r = daily.get(day, {})
        cost = float(r.get("cost") or 0)
        bars.append({"day": day, "calls": r.get("calls", 0), "cost": cost, "pct": round(cost / peak * 100, 1) if peak else 0})

    spent = ai.spent_today()
    budget = Decimal(str(settings.AI_DAILY_BUDGET_USD))
    return render(request, "studio/ai.html", {
        "days": days,
        "periods": PERIODS,
        "total": {**total, "fail": total["calls"] - total["ok"], "krw": _krw(total["cost"])},
        "by_feature": by_feature,
        "by_user": by_user,
        "recent": AIUsage.objects.select_related("user")[:30],
        "labels": labels,
        "bars": bars,
        "budget": budget,
        "spent": spent,
        "spent_krw": _krw(spent),
        "budget_krw": _krw(budget),
        "budget_pct": min(100, round(float(spent / budget * 100), 1)) if budget else 0,
        "configured": bool(settings.ANTHROPIC_API_KEY),
        "model": settings.ANTHROPIC_MODEL,
        "price_in": settings.AI_PRICE_INPUT_PER_MTOK,
        "price_out": settings.AI_PRICE_OUTPUT_PER_MTOK,
        "limits": [(TIER_LABELS[k], v) for k, v in AI_LIMITS.items()],
        "krw_rate": KRW_PER_USD,
    })
