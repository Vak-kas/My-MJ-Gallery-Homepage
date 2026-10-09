"""이번 달 서버 트래픽 = 1시간마다 저장한 누적 카운터의 증가분 합 (재부팅 시 카운터가 0부터라 boot_id 로 보정)."""

from django.utils import timezone

from . import system
from .models import TrafficSnapshot


def take_snapshot():
    counters = system.network_counters()
    if not counters:
        return None
    return TrafficSnapshot.objects.create(boot_id=system.boot_id(), rx_bytes=counters[0], tx_bytes=counters[1])


def month_usage(now=None):
    now = timezone.localtime(now or timezone.now())
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    snaps = list(TrafficSnapshot.objects.filter(created_at__gte=start).order_by("created_at"))
    prev = TrafficSnapshot.objects.filter(created_at__lt=start).order_by("-created_at").first()
    rx = tx = 0
    for snap in snaps:
        if prev and prev.boot_id == snap.boot_id and snap.rx_bytes >= prev.rx_bytes:
            rx += snap.rx_bytes - prev.rx_bytes
            tx += snap.tx_bytes - prev.tx_bytes
        elif prev:  # 재부팅: 새 카운터 값 자체가 그 사이 사용량
            rx += snap.rx_bytes
            tx += snap.tx_bytes
        prev = snap
    current = system.network_counters()
    if current and prev and prev.boot_id == system.boot_id() and current[0] >= prev.rx_bytes:
        rx += current[0] - prev.rx_bytes
        tx += current[1] - prev.tx_bytes
    return {"rx": rx, "tx": tx, "total": rx + tx, "since": start, "samples": len(snaps), "tracking_since": snaps[0].created_at if snaps else None}


def cleanup():
    TrafficSnapshot.objects.filter(created_at__lt=timezone.now() - timezone.timedelta(days=100)).delete()
