"""업타임 확인과 장애·복구 알림."""

import socket
import ssl
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

from django.db import close_old_connections
from django.urls import reverse
from django.utils import timezone

from .models import UptimeCheck, UptimeTarget

FAILS_BEFORE_ALERT = 2  # 연속 2번 실패해야 장애로 판단 (일시적 끊김 무시)
TIMEOUT = 10
USER_AGENT = "smjgallery-uptime/1.0"


def probe(target):
    """(ok, latency_ms, status_code, error)"""
    started = time.perf_counter()
    try:
        if target.kind == UptimeTarget.KIND_TCP:
            host, _, port = target.target.rpartition(":")
            with socket.create_connection((host.strip("[]"), int(port)), timeout=TIMEOUT):
                pass
            return True, int((time.perf_counter() - started) * 1000), None, ""
        req = urllib.request.Request(target.target, headers={"User-Agent": USER_AGENT}, method="GET")
        with urllib.request.urlopen(req, timeout=TIMEOUT, context=ssl.create_default_context()) as res:
            res.read(1024)
            code = res.status
        return code < 400, int((time.perf_counter() - started) * 1000), code, "" if code < 400 else f"HTTP {code}"
    except urllib.error.HTTPError as exc:
        return False, int((time.perf_counter() - started) * 1000), exc.code, f"HTTP {exc.code}"
    except (OSError, ValueError, ssl.SSLError) as exc:
        reason = getattr(exc, "reason", exc)
        return False, None, None, str(reason)[:200] or exc.__class__.__name__


def _fmt_duration(delta):
    minutes = int(delta.total_seconds() // 60)
    if minutes < 60:
        return f"{minutes}분"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}시간 {minutes}분" if hours < 48 else f"{hours // 24}일 {hours % 24}시간"


def record(target, result):
    from notifications.models import Notification
    from notifications.service import notify

    ok, latency, code, error = result
    now = timezone.now()
    UptimeCheck.objects.create(target=target, ok=ok, latency_ms=latency, status_code=code, error=error)
    target.last_checked_at, target.last_latency_ms, target.last_error = now, latency, error
    link = reverse("studio:server") + "#uptime"
    if ok:
        if target.status == "down":
            down_for = _fmt_duration(now - (target.last_change_at or now))
            notify(Notification.KIND_MONITOR, f"✅ {target.name} 복구됐어요", f"{target.target} · 장애 {down_for} 만에 정상 ({latency}ms)", link)
        if target.status != "up":
            target.status, target.last_change_at = "up", now
        target.fail_streak = 0
    else:
        target.fail_streak += 1
        if target.status != "down" and target.fail_streak >= FAILS_BEFORE_ALERT:
            target.status, target.last_change_at = "down", now
            notify(Notification.KIND_MONITOR, f"🚨 {target.name} 응답이 없어요", f"{target.target} · {error}", link)
    target.save()


def due_targets(now=None):
    now = now or timezone.now()
    for t in UptimeTarget.objects.filter(enabled=True):
        if not t.last_checked_at or now - t.last_checked_at >= timedelta(minutes=t.interval_min) - timedelta(seconds=15):
            yield t


def check_targets(targets):
    targets = list(targets)
    if not targets:
        return 0

    def run(t):
        try:
            return t, probe(t)
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(run, targets))
    for t, result in results:
        record(t, result)
    return len(results)


def uptime_pct(target, hours):
    since = timezone.now() - timedelta(hours=hours)
    qs = target.checks.filter(checked_at__gte=since)
    total = qs.count()
    return round(qs.filter(ok=True).count() / total * 100, 2) if total else None


def cleanup():
    UptimeCheck.objects.filter(checked_at__lt=timezone.now() - timedelta(days=30)).delete()
