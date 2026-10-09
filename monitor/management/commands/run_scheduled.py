"""1분마다 cron 으로 실행: 업타임 확인, 1시간마다 트래픽 기록, 하루 한 번 오래된 기록 정리.

  * * * * * cd /home/ubuntu/projects/smjgallery && venv/bin/python manage.py run_scheduled >/dev/null 2>&1
"""

from django.core.cache import cache
from django.core.management.base import BaseCommand
from django.utils import timezone

from monitor import traffic, uptime
from monitor.models import TrafficSnapshot

HEARTBEAT_KEY = "monitor:scheduler:last_run"


class Command(BaseCommand):
    help = "업타임 확인·트래픽 기록·오래된 기록 정리 (cron 에서 1분마다)"

    def handle(self, *args, **options):
        lock = cache.add("monitor:scheduler:lock", 1, 55)  # 이전 실행이 아직 돌고 있으면 건너뜀
        if not lock:
            return
        try:
            now = timezone.now()
            checked = uptime.check_targets(uptime.due_targets(now))

            last = TrafficSnapshot.objects.order_by("-created_at").first()
            if not last or (now - last.created_at).total_seconds() >= 55 * 60:
                traffic.take_snapshot()

            if cache.add(f"monitor:daily:{timezone.localdate().isoformat()}", 1, 26 * 60 * 60):
                self.daily_cleanup()

            cache.set(HEARTBEAT_KEY, now.isoformat(), 7 * 24 * 60 * 60)
            if options.get("verbosity", 1) > 1:
                self.stdout.write(f"업타임 {checked}개 확인")
        finally:
            cache.delete("monitor:scheduler:lock")

    def daily_cleanup(self):
        from analytics import stats
        from security.utils import cleanup_old_records
        from tools.share_views import cleanup_expired

        cleanup_old_records()
        stats.cleanup()
        cleanup_expired()
        uptime.cleanup()
        traffic.cleanup()
