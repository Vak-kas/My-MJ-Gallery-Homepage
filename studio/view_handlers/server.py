import re
from datetime import datetime

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from accounts.models import SignupRequest
from monitor import backup, system, traffic, uptime
from monitor.management.commands.run_scheduled import HEARTBEAT_KEY
from monitor.models import UptimeTarget

from .common import admin_view

HOSTPORT = re.compile(r"^[\w.\-\[\]:]+:\d{1,5}$")


def _relay_status():
    from tools import relay_client
    try:
        return {"stream": len(relay_client.list_rooms()), "live": len(relay_client.list_live()), "ok": True}
    except relay_client.RelayError as exc:
        return {"ok": False, "error": str(exc)}


def _app_stats():
    from blog.models import Post
    from tools.models import ClipItem, SharedFile
    from django.db.models import Sum

    User = get_user_model()
    return {
        "users": User.objects.filter(is_active=True).count(),
        "pending": SignupRequest.objects.filter(status=SignupRequest.STATUS_PENDING).count(),
        "posts": Post.objects.filter(is_published=True).count(),
        "shared_files": SharedFile.objects.filter(completed=True).count(),
        "shared_bytes": SharedFile.objects.filter(completed=True).aggregate(s=Sum("size"))["s"] or 0,
        "clip_bytes": ClipItem.objects.aggregate(s=Sum("size"))["s"] or 0,
    }


def _add_target(request):
    name = (request.POST.get("name") or "").strip()[:60]
    kind = request.POST.get("kind")
    raw = (request.POST.get("target") or "").strip()
    try:
        interval = int(request.POST.get("interval") or 5)
    except ValueError:
        interval = 5
    if interval not in UptimeTarget.INTERVALS:
        interval = 5
    if kind == UptimeTarget.KIND_TCP:
        if not HOSTPORT.match(raw):
            messages.error(request, "포트 확인은 host:port 형식으로 적어 주세요. 예: smjgallery.kr:22")
            return
    else:
        kind = UptimeTarget.KIND_HTTP
        if raw and "://" not in raw:
            raw = "https://" + raw
        if not re.match(r"^https?://[^\s/]+", raw):
            messages.error(request, "http:// 또는 https:// 로 시작하는 주소를 적어 주세요.")
            return
    if UptimeTarget.objects.count() >= 30:
        messages.error(request, "감시 대상은 30개까지 둘 수 있어요.")
        return
    target = UptimeTarget.objects.create(name=name or raw[:60], kind=kind, target=raw[:300], interval_min=interval, created_by=request.user)
    uptime.check_targets([target])  # 추가하자마자 한 번 확인
    messages.success(request, f"'{target.name}' 감시를 시작했어요.")


def _backup_status():
    st = backup.status() or {}
    at = datetime.fromisoformat(st["at"]) if st.get("at") else None
    return {
        **st,
        "configured": backup.configured(),
        "running": backup.is_running(),
        "at": at,
        "stale": bool(backup.configured() and (not at or (timezone.now() - at).total_seconds() > 2 * 24 * 60 * 60)),
        "bucket": settings.BACKUP_S3_BUCKET,
        "keep_days": settings.BACKUP_KEEP_DAYS,
        "hour": settings.BACKUP_HOUR,
    }


@admin_view
def server(request):
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "backup":
            if not backup.configured():
                messages.error(request, "백업 설정(.env)이 아직 없어요.")
            elif backup.is_running():
                messages.error(request, "이미 백업이 돌고 있어요.")
            else:
                backup.start_in_background()
                messages.success(request, "백업을 시작했어요. 잠시 뒤 새로고침하면 결과가 보여요.")
            return redirect(reverse("studio:server") + "#backup")
        elif action == "add":
            _add_target(request)
        elif action in {"delete", "toggle", "check"}:
            target = get_object_or_404(UptimeTarget, pk=request.POST.get("id"))
            if action == "delete":
                target.delete()
                messages.success(request, "감시 대상을 지웠어요.")
            elif action == "toggle":
                target.enabled = not target.enabled
                target.save(update_fields=["enabled"])
            else:
                uptime.check_targets([target])
                messages.success(request, f"'{target.name}' 을(를) 지금 확인했어요.")
        return redirect(reverse("studio:server") + "#uptime")

    snap = system.snapshot()
    month = traffic.month_usage()
    allowance = settings.SERVER_TRANSFER_ALLOWANCE_GB * 1024 ** 3
    heartbeat = cache.get(HEARTBEAT_KEY)
    heartbeat_at = datetime.fromisoformat(heartbeat) if heartbeat else None
    targets = list(UptimeTarget.objects.all())
    for t in targets:
        t.pct24 = uptime.uptime_pct(t, 24)
        t.pct7d = uptime.uptime_pct(t, 24 * 7)
        t.recent = list(reversed(list(t.checks.all()[:40])))
    return render(request, "studio/server.html", {
        "sys": snap,
        "month": month,
        "allowance": allowance,
        "allowance_pct": round(month["total"] / allowance * 100, 1) if allowance else None,
        "relay": _relay_status(),
        "app": _app_stats(),
        "heartbeat_at": heartbeat_at,
        "scheduler_ok": bool(heartbeat_at and (timezone.now() - heartbeat_at).total_seconds() < 180),
        "backup": _backup_status(),
        "targets": targets,
        "intervals": UptimeTarget.INTERVALS,
    })
