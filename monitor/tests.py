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


class FakeS3:
	"""boto3 S3 클라이언트 중 백업이 쓰는 부분만."""

	def __init__(self):
		self.objects = {}  # key -> (bytes, LastModified)

	def upload_file(self, path, bucket, key):
		with open(path, "rb") as f:
			self.objects[key] = (f.read(), timezone.now())

	def download_file(self, bucket, key, path):
		with open(path, "wb") as f:
			f.write(self.objects[key][0])

	def delete_objects(self, Bucket, Delete):
		for o in Delete["Objects"]:
			self.objects.pop(o["Key"], None)

	def get_paginator(self, name):
		outer = self

		class P:
			def paginate(self, Bucket, Prefix):
				yield {"Contents": [{"Key": k, "Size": len(b), "LastModified": t} for k, (b, t) in sorted(outer.objects.items()) if k.startswith(Prefix)]}

		return P()


class BackupTests(TestCase):
	def setUp(self):
		import tempfile
		from pathlib import Path

		cache.clear()
		self.tmp = tempfile.TemporaryDirectory()
		root = Path(self.tmp.name)
		self.media = root / "media"
		(self.media / "posts").mkdir(parents=True)
		(self.media / "posts" / "a.jpg").write_bytes(b"x" * 100)
		(self.media / "b.txt").write_bytes(b"hello")
		self.s3 = FakeS3()
		self.patches = [
			self.settings(BACKUP_S3_BUCKET="bk", BACKUP_AWS_ACCESS_KEY_ID="id", BACKUP_AWS_SECRET_ACCESS_KEY="sk",
						  MEDIA_ROOT=self.media, PRIVATE_MEDIA_ROOT=root / "private_media", BACKUP_KEEP_DAYS=30, BACKUP_HOUR=4),
			mock.patch("monitor.backup.client", return_value=self.s3),
		]
		for p in self.patches:
			p.enable() if hasattr(p, "enable") else p.start()

	def tearDown(self):
		for p in reversed(self.patches):
			p.disable() if hasattr(p, "disable") else p.stop()
		self.tmp.cleanup()
		cache.clear()

	def test_run_uploads_db_and_only_changed_files(self):
		from django.db import connection

		if connection.vendor != "sqlite":
			self.skipTest("SQLite 백업 형식 확인 (PostgreSQL 은 pg_dump)")
		import gzip
		import sqlite3
		import tempfile

		from . import backup

		r = backup.run()
		self.assertTrue(r["ok"])
		self.assertEqual((r["uploaded"], r["skipped"]), (2, 0))
		self.assertIn("media/posts/a.jpg", self.s3.objects)
		# 올린 DB 를 풀어서 실제로 열리는 SQLite 인지 확인
		with tempfile.NamedTemporaryFile(suffix=".sqlite3") as f:
			f.write(gzip.decompress(self.s3.objects[r["db_key"]][0]))
			f.flush()
			tables = sqlite3.connect(f.name).execute("select name from sqlite_master where type='table'").fetchall()
		self.assertIn(("auth_user",), tables)

		(self.media / "b.txt").write_bytes(b"hello world")
		r2 = backup.run()
		self.assertEqual((r2["uploaded"], r2["skipped"]), (1, 1))
		self.assertEqual(backup.status()["db_key"], r2["db_key"])

	def test_prune_old_db_backups(self):
		from . import backup

		self.s3.objects["db/old.sqlite3.gz"] = (b"x", timezone.now() - timedelta(days=31))
		self.s3.objects["db/new.sqlite3.gz"] = (b"x", timezone.now() - timedelta(days=2))
		self.s3.objects["media/keep.jpg"] = (b"x", timezone.now() - timedelta(days=400))
		self.assertEqual(backup.prune_db(self.s3, 30), 1)
		self.assertEqual(sorted(self.s3.objects), ["db/new.sqlite3.gz", "media/keep.jpg"])

	def test_failure_is_recorded(self):
		from . import backup

		self.s3.upload_file = mock.Mock(side_effect=OSError("AccessDenied"))
		with self.assertRaises(OSError):
			backup.run()
		st = backup.status()
		self.assertFalse(st["ok"])
		self.assertIn("AccessDenied", st["error"])
		self.assertFalse(backup.is_running())

	def test_due_once_a_day_after_hour(self):
		import datetime as dt

		from . import backup

		tz = timezone.get_current_timezone()
		self.assertFalse(backup.due(dt.datetime(2026, 10, 9, 3, 59, tzinfo=tz)))
		self.assertTrue(backup.due(dt.datetime(2026, 10, 9, 4, 0, tzinfo=tz)))
		self.assertFalse(backup.due(dt.datetime(2026, 10, 9, 4, 1, tzinfo=tz)))
		self.assertTrue(backup.due(dt.datetime(2026, 10, 10, 9, 0, tzinfo=tz)))

	def test_download_command(self):
		import tempfile
		from pathlib import Path

		from . import backup

		backup.run()
		with tempfile.TemporaryDirectory() as out:
			call_command("backup_s3", download=out, stdout=open("/dev/null", "w"))
			files = sorted(p.relative_to(out).as_posix() for p in Path(out).rglob("*") if p.is_file())
		self.assertEqual(len([f for f in files if f.startswith("db/")]), 1)
		self.assertIn("media/posts/a.jpg", files)

	def test_server_page_backup_button(self):
		admin = get_user_model().objects.create_superuser("admin", "a@example.com", "pw")
		self.client.force_login(admin)
		with mock.patch("monitor.system.cpu_percent", return_value=5), mock.patch("monitor.backup.start_in_background") as start:
			self.assertContains(self.client.get(reverse("studio:server")), "아직 백업한 적이 없어요")
			self.client.post(reverse("studio:server"), {"action": "backup"})
		start.assert_called_once()

	def test_not_configured(self):
		from . import backup

		with self.settings(BACKUP_S3_BUCKET=""):
			self.assertFalse(backup.due())
			with self.assertRaises(RuntimeError):
				backup.run()


class LogsTests(TestCase):
	def setUp(self):
		import tempfile
		from pathlib import Path

		self.tmp = tempfile.TemporaryDirectory()
		root = Path(self.tmp.name)
		(root / "nginx").mkdir()
		(root / "nginx" / "access.log.1").write_text('1.1.1.1 - - [09/Oct/2026:23:00:00 +0900] "GET /old HTTP/1.1" 200 10 "-" "x"\n')
		lines = [f'2.2.2.2 - - [10/Oct/2026:00:00:{i:02d} +0900] "GET /games/{i} HTTP/1.1" 200 10 "-" "x"' for i in range(30)]
		lines.append('3.3.3.3 - - [10/Oct/2026:00:01:00 +0900] "GET /relay/ws/game/abc?token=SECRET123&pid=1 HTTP/1.1" 502 10 "-" "x"')
		lines.append('4.4.4.4 - - [10/Oct/2026:00:01:01 +0900] "GET /nope HTTP/1.1" 404 10 "-" "x"')
		(root / "nginx" / "access.log").write_text("\n".join(lines) + "\n")
		(root / "auth.log").write_text("Oct 10 sshd[1]: Failed password for invalid user root from 5.5.5.5\nOct 10 sudo: ubuntu : COMMAND=/bin/ls\n")
		self.patch = mock.patch("monitor.logs.LOG_ROOT", root)
		self.patch.start()

	def tearDown(self):
		self.patch.stop()
		self.tmp.cleanup()

	def test_tail_masks_and_levels(self):
		from . import logs

		data = logs.read("access", lines=200)
		texts = [l["text"] for l in data["lines"]]
		self.assertIn("/old", texts[0])  # 줄이 모자라면 어제 로그(.1)도 앞에 붙임
		self.assertTrue(all("SECRET123" not in t for t in texts))
		self.assertIn("token=•••", texts[-2])
		self.assertEqual([l["level"] for l in data["lines"][-2:]], ["err", "warn"])
		self.assertEqual(dict(data["summary"]["status"])["5xx"], 1)

	def test_filters(self):
		from . import logs

		self.assertEqual(len(logs.read("access", lines=200, level="err")["lines"]), 1)
		self.assertEqual(len(logs.read("access", lines=200, level="warn")["lines"]), 2)
		self.assertEqual(len(logs.read("access", lines=200, q="/GAMES/1")["lines"]), 11)  # 1, 10~19
		auth = logs.read("auth", lines=200)["lines"]
		self.assertEqual(auth[0]["level"], "warn")  # SSH 무작위 대입은 경고
		self.assertEqual(auth[1]["level"], "")

	def test_missing_source_and_page(self):
		from . import logs

		self.assertIn("없어요", logs.read("nginx_error")["error"])
		admin = get_user_model().objects.create_superuser("admin", "a@example.com", "pw")
		self.client.force_login(admin)
		self.assertContains(self.client.get(reverse("studio:server_logs") + "?source=access"), "nginx 접속")
		res = self.client.get(reverse("studio:server_logs") + "?source=access&format=json&level=err")
		self.assertEqual(len(res.json()["lines"]), 1)

	def test_admin_only(self):
		user = get_user_model().objects.create_user("u", "u@example.com", "pw")
		self.client.force_login(user)
		res = self.client.get(reverse("studio:server_logs") + "?format=json")
		self.assertNotEqual(res.status_code, 200)
