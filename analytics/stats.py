"""Studio 통계 화면용 집계."""

from collections import Counter
from datetime import timedelta
from urllib.parse import unquote

from django.db.models import Count
from django.utils import timezone

from .models import PageView

RETENTION_DAYS = 90


def cleanup():
    PageView.objects.filter(day__lt=timezone.localdate() - timedelta(days=RETENTION_DAYS)).delete()


def _title_for(path):
    """경로를 사람이 읽을 이름으로 (글 제목, 도구 이름 등)."""
    from blog.models import Post
    from tools.registry import TOOLS

    if path == "/":
        return "🏠 홈"
    if path.startswith("/blog/post/"):
        slug = unquote(path[len("/blog/post/"):].strip("/").split("/")[0])
        post = Post.objects.filter(slug=slug).only("title").first()
        return f"📝 {post.title}" if post else path
    if path.startswith("/tools/"):
        slug = path[len("/tools/"):].strip("/").split("/")[0]
        if not slug:
            return "🧰 Tool 목록"
        tool = next((t for t in TOOLS if t["slug"] == slug), None)
        return f"{tool['icon']} {tool['title']}" if tool else path
    names = {"/blog/": "📚 블로그", "/blog/tech/": "📚 Tech", "/blog/board/": "📚 Board", "/blog/life/": "📚 Life", "/photos/": "🖼 갤러리"}
    return names.get(path, path)


def summary(days):
    today = timezone.localdate()
    start = today - timedelta(days=days - 1)
    qs = PageView.objects.filter(day__gte=start)

    by_day = {r["day"]: r for r in qs.values("day").annotate(views=Count("id"), visitors=Count("visitor", distinct=True))}
    series = []
    for i in range(days):
        d = start + timedelta(days=i)
        r = by_day.get(d, {})
        series.append({"day": d, "views": r.get("views", 0), "visitors": r.get("visitors", 0)})
    peak = max((s["views"] for s in series), default=0) or 1
    for s in series:
        s["pct"] = round(s["views"] / peak * 100)
        s["vpct"] = round(s["visitors"] / peak * 100)

    # 순방문자: 방문자 해시는 날마다 바뀌므로 기간 합계는 "날짜별 순방문자의 합"
    visitors_total = sum(s["visitors"] for s in series)
    views_total = sum(s["views"] for s in series)
    today_row = series[-1]

    def top(field_qs, limit=10):
        return list(field_qs[:limit])

    pages = top(qs.exclude(section="short").values("path").annotate(n=Count("id")).order_by("-n"), 30)
    posts = [p for p in pages if p["path"].startswith("/blog/post/")][:10]
    tools = [p for p in pages if p["path"].startswith("/tools/") and p["path"] != "/tools/"][:10]
    for row in pages + posts + tools:
        row["title"] = _title_for(row["path"])

    labels = dict(PageView.SOURCE_CHOICES)
    sources = [{"key": r["source"], "label": labels.get(r["source"], r["source"]), "n": r["n"]}
               for r in qs.exclude(source="internal").values("source").annotate(n=Count("visitor", distinct=True)).order_by("-n")]
    src_total = sum(s["n"] for s in sources) or 1
    for s in sources:
        s["pct"] = round(s["n"] / src_total * 100)
    referrers = top(qs.exclude(referrer_host="").values("referrer_host").annotate(n=Count("id")).order_by("-n"))

    dev_labels = dict(PageView.DEVICE_CHOICES)
    devices = [{"label": dev_labels.get(r["device"], r["device"]), "n": r["n"]}
               for r in qs.values("device").annotate(n=Count("visitor", distinct=True)).order_by("-n")]
    dev_total = sum(d["n"] for d in devices) or 1
    for d in devices:
        d["pct"] = round(d["n"] / dev_total * 100)

    hours = Counter(timezone.localtime(t).hour for t in qs.values_list("created_at", flat=True)[:50000])
    hour_peak = max(hours.values(), default=0) or 1
    hourly = [{"h": h, "n": hours.get(h, 0), "pct": round(hours.get(h, 0) / hour_peak * 100)} for h in range(24)]

    member_views = qs.filter(is_member=True).count()
    return {
        "days": days, "start": start, "today": today,
        "series": series, "views_total": views_total, "visitors_total": visitors_total,
        "today_views": today_row["views"], "today_visitors": today_row["visitors"],
        "member_pct": round(member_views / views_total * 100) if views_total else 0,
        "pages": pages[:10], "posts": posts, "tools": tools,
        "sources": sources, "referrers": referrers, "devices": devices, "hourly": hourly,
        "short_clicks": qs.filter(section="short").count(),
    }
