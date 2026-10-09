from datetime import timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from notifications.models import Notification

from . import traffic, uptime
from .models import TrafficSnapshot, UptimeCheck, UptimeTarget


class UptimeTests(TestCase):
	def setUp(self):
		cache.clear()
		self.target = UptimeTarget.objects.create(name="블로그", target="https://example.com", interval_min=5)

	def tearDown(self):
		cache.clear()

	def run_with(self, *results):
		with mock.patch("monitor.uptime.probe", side_effect=list(results)), mock.patch("notifications.service._run_background"):
			for _ in results:
				uptime.check_targets([UptimeTarget.objects.get(pk=self.target.pk)])
		self.target.refresh_from_db()

	def test_alert_after_two_failures_and_recovery(self):
		self.run_with((True, 50, 200, ""))
		self.assertEqual(self.target.status, "up")
		self.run_with((False, None, None, "timed out"))
		self.assertEqual(self.target.status, "up")  # 한 번은 봐줌
		self.assertFalse(Notification.objects.exists())
		self.run_with((False, None, None, "timed out"))
		self.assertEqual(self.target.status, "down")
		alert = Notification.objects.get()
		self.assertEqual(alert.kind, "monitor")
		self.assertIn("응답이 없어요", alert.title)
		self.run_with((True, 40, 200, ""))
		self.assertEqual(self.target.status, "up")
		self.assertIn("복구", Notification.objects.order_by("-id").first().title)
		self.assertEqual(UptimeCheck.objects.count(), 4)
		self.assertEqual(uptime.uptime_pct(self.target, 24), 50.0)

	def test_due_targets_respects_interval(self):
		now = timezone.now()
		UptimeTarget.objects.filter(pk=self.target.pk).update(last_checked_at=now - timedelta(minutes=2))
		self.assertEqual(list(uptime.due_targets(now)), [])
		UptimeTarget.objects.filter(pk=self.target.pk).update(last_checked_at=now - timedelta(minutes=5))
		self.assertEqual(len(list(uptime.due_targets(now))), 1)

	def test_probe_tcp_and_http(self):
		with mock.patch("monitor.uptime.socket.create_connection") as conn:
			ok, latency, code, err = uptime.probe(UptimeTarget(kind="tcp", target="example.com:22"))
		self.assertTrue(ok)
		conn.assert_called_once_with(("example.com", 22), timeout=uptime.TIMEOUT)
		with mock.patch("monitor.uptime.urllib.request.urlopen", side_effect=OSError("refused")):
			ok, *_rest, err = uptime.probe(UptimeTarget(kind="http", target="https://example.com"))
		self.assertFalse(ok)
		self.assertIn("refused", err)

	def test_scheduler_command(self):
		with mock.patch("monitor.uptime.probe", return_value=(True, 10, 200, "")), \
				mock.patch("monitor.system.network_counters", return_value=(1000, 2000)), \
				mock.patch("monitor.system.boot_id", return_value="b1"):
			call_command("run_scheduled")
			call_command("run_scheduled")  # 1시간 안이면 트래픽 스냅샷은 한 번만
		self.target.refresh_from_db()
		self.assertEqual(self.target.status, "up")
		self.assertEqual(TrafficSnapshot.objects.count(), 1)
		self.assertTrue(cache.get("monitor:scheduler:last_run"))


class TrafficTests(TestCase):
	def test_month_usage_handles_reboot(self):
		now = timezone.now()
		start = timezone.localtime(now).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
		def snap(at, boot, rx, tx):
			s = TrafficSnapshot.objects.create(boot_id=boot, rx_bytes=rx, tx_bytes=tx)
			TrafficSnapshot.objects.filter(pk=s.pk).update(created_at=at)
		snap(start - timedelta(hours=1), "b1", 100, 100)    # 지난달 마지막
		snap(start + timedelta(hours=1), "b1", 300, 200)    # +200 / +100
		snap(start + timedelta(hours=2), "b2", 50, 70)      # 재부팅 → 50 / 70
		snap(start + timedelta(hours=3), "b2", 150, 170)    # +100 / +100
		with mock.patch("monitor.system.network_counters", return_value=None):
			usage = traffic.month_usage(now)
		self.assertEqual((usage["rx"], usage["tx"]), (350, 270))


class ServerPageTests(TestCase):
	def setUp(self):
		cache.clear()
		User = get_user_model()
		self.admin = User.objects.create_superuser("admin", "a@example.com", "pw")
		self.client.force_login(self.admin)

	def test_page_and_add_targets(self):
		with mock.patch("monitor.uptime.probe", return_value=(True, 12, 200, "")), mock.patch("monitor.system.cpu_percent", return_value=5):
			res = self.client.get(reverse("studio:server"))
			self.assertContains(res, "서버 상태")
			self.assertContains(res, "예약 작업(cron)이 돌고 있지 않아요")
			self.client.post(reverse("studio:server"), {"action": "add", "name": "홈", "kind": "http", "target": "smjgallery.kr", "interval": "5"})
			self.client.post(reverse("studio:server"), {"action": "add", "name": "SSH", "kind": "tcp", "target": "smjgallery.kr:22", "interval": "1"})
			self.client.post(reverse("studio:server"), {"action": "add", "name": "잘못", "kind": "tcp", "target": "no-port", "interval": "1"})
		self.assertEqual(list(UptimeTarget.objects.values_list("target", "status")), [("smjgallery.kr:22", "up"), ("https://smjgallery.kr", "up")])

	def test_member_cannot_open(self):
		member = get_user_model().objects.create_user("m", "m@example.com", "pw")
		self.client.force_login(member)
		self.assertEqual(self.client.get(reverse("studio:server")).status_code, 302)
