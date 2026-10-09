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
