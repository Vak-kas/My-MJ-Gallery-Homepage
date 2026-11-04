from django.shortcuts import render

from analytics import stats

from .common import admin_view

RANGES = [(1, "오늘"), (7, "7일"), (30, "30일"), (90, "90일")]


@admin_view
def analytics(request):
    try:
        days = int(request.GET.get("days") or 7)
    except ValueError:
        days = 7
    if days not in dict(RANGES):
        days = 7
    stats.cleanup()
    return render(request, "studio/analytics.html", {"s": stats.summary(days), "ranges": RANGES, "days": days})


@admin_view
def analytics_live(request):
    """실시간 현황: 지금 접속 중(최근 5분)·최근 활동 흐름. 30초마다 JSON 으로 갱신."""
    from django.http import JsonResponse
    from django.utils import timezone

    data = stats.live()
    if request.GET.get("format") == "json":
        fmt = lambda dt: timezone.localtime(dt).strftime("%H:%M:%S")  # noqa: E731
        return JsonResponse({
            "ok": True, "online_total": data["online_total"], "online_members": data["online_members"], "today_views": data["today_views"],
            "online": [dict(p, last_at=fmt(p["last_at"])) for p in data["online"]],
            "stream": [dict(v, at=fmt(v["at"])) for v in data["stream"]],
        })
    return render(request, "studio/analytics_live.html", {"live": data})
