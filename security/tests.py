from datetime import timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from blog.models import Comment, GuestbookEntry, Post
from notifications.models import Notification

from .models import IPBlock, LoginEvent
from .utils import cleanup_old_records

User = get_user_model()


class LoginSecurityTests(TestCase):
    def setUp(self):
        cache.clear()
        self.admin = User.objects.create_superuser("admin", "a@example.com", "Admin-pw-123")
        self.member = User.objects.create_user("member", "m@example.com", "Member-pw-123")

    def login(self, username, password, ip="203.0.113.1"):
        return self.client.post(reverse("accounts:login"), {"username": username, "password": password}, HTTP_X_REAL_IP=ip, HTTP_USER_AGENT="UA/1")

    def test_records_success_and_failure(self):
        self.login("member", "wrong")
        self.login("member", "Member-pw-123")
        fail, ok = LoginEvent.objects.order_by("id")
        self.assertEqual((fail.result, fail.username, fail.ip), ("failed", "member", "203.0.113.1"))
        self.assertEqual((ok.result, ok.user, ok.user_agent), ("success", self.member, "UA/1"))

    def test_lock_after_repeated_failures(self):
        for _ in range(5):
            self.login("member", "wrong")
        res = self.login("member", "Member-pw-123")  # 맞는 비밀번호여도 15분 잠김
        self.assertContains(res, "잠시 잠겼어요")
        self.assertTrue(LoginEvent.objects.filter(result="locked").exists())
        cache.clear()
        self.assertEqual(self.login("member", "Member-pw-123").status_code, 302)

    def test_ip_lock_across_usernames(self):
        for i in range(10):
            self.login(f"guess{i}", "x", ip="198.51.100.9")
        self.assertContains(self.login("member", "Member-pw-123", ip="198.51.100.9"), "잠시 잠겼어요")
        self.assertEqual(self.login("member", "Member-pw-123", ip="198.51.100.10").status_code, 302)

    def test_admin_new_ip_alert(self):
        with mock.patch("notifications.service._run_background"):
            self.login("admin", "Admin-pw-123", ip="203.0.113.1")  # 첫 로그인은 기준이 없어 알림 없음
            self.client.logout()
            self.login("admin", "Admin-pw-123", ip="203.0.113.1")
            self.client.logout()
            self.assertFalse(Notification.objects.filter(kind="security").exists())
            self.login("admin", "Admin-pw-123", ip="192.0.2.77")
        n = Notification.objects.get(kind="security")
        self.assertIn("새 IP", n.title)
        self.assertIn("192.0.2.77", n.body)
        self.assertTrue(LoginEvent.objects.filter(ip="192.0.2.77", new_location=True).exists())


class IPBlockTests(TestCase):
    def setUp(self):
        cache.clear()
        self.admin = User.objects.create_superuser("admin", "a@example.com", "Admin-pw-123")

    def test_blocked_ip_gets_403(self):
        IPBlock.objects.create(network="198.51.100.0/24", reason="spam")
        res = self.client.get(reverse("blog:index"), HTTP_X_REAL_IP="198.51.100.20")
        self.assertContains(res, "접근이 차단됐어요", status_code=403)
        self.assertEqual(IPBlock.objects.get().hit_count, 1)
        self.assertEqual(self.client.get(reverse("blog:index"), HTTP_X_REAL_IP="198.51.101.20").status_code, 200)

    def test_expired_block_ignored(self):
        IPBlock.objects.create(network="198.51.100.5", expires_at=timezone.now() - timedelta(minutes=1))
        self.assertEqual(self.client.get(reverse("blog:index"), HTTP_X_REAL_IP="198.51.100.5").status_code, 200)

    def test_studio_block_and_unblock(self):
        self.client.force_login(self.admin)
        url = reverse("studio:security")
        self.client.post(url, {"action": "block", "network": "192.0.2.50", "reason": "test", "duration": "1d"}, HTTP_X_REAL_IP="203.0.113.1")
        b = IPBlock.objects.get()
        self.assertEqual(b.network, "192.0.2.50")
        self.assertIsNotNone(b.expires_at)
        self.assertEqual(self.client.get("/", HTTP_X_REAL_IP="192.0.2.50").status_code, 403)
        self.client.post(url, {"action": "unblock", "id": b.id}, HTTP_X_REAL_IP="203.0.113.1")
        self.assertEqual(self.client.get("/", HTTP_X_REAL_IP="192.0.2.50").status_code, 200)

    def test_cannot_block_own_ip_or_huge_ranges(self):
        self.client.force_login(self.admin)
        url = reverse("studio:security")
        self.client.post(url, {"action": "block", "network": "203.0.113.0/24"}, HTTP_X_REAL_IP="203.0.113.1")
        self.client.post(url, {"action": "block", "network": "10.0.0.0/8"}, HTTP_X_REAL_IP="203.0.113.1")
        self.client.post(url, {"action": "block", "network": "not-an-ip"}, HTTP_X_REAL_IP="203.0.113.1")
        self.assertFalse(IPBlock.objects.exists())

    def test_member_cannot_open_security(self):
        member = User.objects.create_user("member", "m@example.com", "pw")
        self.client.force_login(member)
        self.assertEqual(self.client.get(reverse("studio:security")).status_code, 302)


class ContentIPTests(TestCase):
    def setUp(self):
        cache.clear()
        self.admin = User.objects.create_superuser("admin", "a@example.com", "Admin-pw-123")
        self.member = User.objects.create_user("member", "m@example.com", "Member-pw-123")
        self.post = Post.objects.create(category="tech", title="글", slug="p1", author=self.admin, published_at=timezone.now())

    def test_comment_and_guestbook_record_ip(self):
        self.client.force_login(self.member)
        self.client.post(reverse("blog:post_detail", args=["p1"]), {"action": "comment", "content": "안녕"}, HTTP_X_REAL_IP="198.51.100.3", HTTP_USER_AGENT="Bot/2")
        self.client.post(reverse("blog:index"), {"message": "방명록"}, HTTP_X_REAL_IP="198.51.100.3")
        c = Comment.objects.get()
        self.assertEqual((c.author_ip, c.author_agent), ("198.51.100.3", "Bot/2"))
        self.assertEqual(GuestbookEntry.objects.get().author_ip, "198.51.100.3")

    def test_content_tab_filter_and_csv(self):
        Comment.objects.create(post=self.post, author=self.member, author_name="member", content="욕설 예시", author_ip="198.51.100.3", author_agent="Bot/2")
        GuestbookEntry.objects.create(author=self.member, author_name="member", message="다른 IP", author_ip="192.0.2.9")
        self.client.force_login(self.admin)
        res = self.client.get(reverse("studio:security"), {"tab": "content", "ip": "198.51.100"})
        self.assertEqual([r["text"] for r in res.context["rows"]], ["욕설 예시"])
        csv_res = self.client.get(reverse("studio:security"), {"tab": "content", "ip": "198.51.100", "export": "csv"})
        body = csv_res.content.decode("utf-8-sig")
        self.assertIn("욕설 예시", body)
        self.assertIn("198.51.100.3", body)
        self.assertNotIn("다른 IP", body)

    def test_retention_cleanup(self):
        old = timezone.now() - timedelta(days=91)
        c = Comment.objects.create(post=self.post, author=self.member, author_name="m", content="x", author_ip="198.51.100.3", author_agent="UA")
        Comment.objects.filter(pk=c.pk).update(created_at=old)
        e = LoginEvent.objects.create(username="m", ip="198.51.100.3", result="failed")
        LoginEvent.objects.filter(pk=e.pk).update(created_at=old)
        result = cleanup_old_records()
        c.refresh_from_db()
        self.assertEqual((c.author_ip, c.author_agent), (None, ""))
        self.assertFalse(LoginEvent.objects.filter(pk=e.pk).exists())
        self.assertEqual(result["login_events"], 1)


class IPLookupTests(TestCase):
    EXT = {
        "rdap": {"network": "CENSY", "range": "167.94.145.0 – 167.94.146.255", "cidr": "", "country": "", "orgs": ["Censys, Inc."], "abuse": ["scan-abuse@censys.io"], "registry": "ARIN", "registered": ""},
        "ipinfo": {"hostname": "53.146.94.167.censys-scanner.com", "city": "Frankfurt am Main", "region": "Hesse", "country": "DE", "asn": "AS398705", "isp": "Censys, Inc.", "loc": ""},
        "internetdb": {"ports": [], "tags": [], "vulns": [], "hostnames": [], "cpes": []},
        "tor": False, "abuseipdb": None, "rdns": ("53.146.94.167.censys-scanner.com", True),
    }

    def setUp(self):
        import tempfile
        from pathlib import Path
        from unittest import mock

        from django.contrib.auth import get_user_model
        from django.core.cache import cache

        cache.clear()
        self.admin = get_user_model().objects.create_superuser("admin", "a@example.com", "pw")
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        (root / "nginx").mkdir()
        (root / "nginx" / "access.log").write_text(
            '167.94.146.53 - - [10/Oct/2026:01:00:00 +0900] "GET /.env HTTP/1.1" 404 10 "-" "Mozilla/5.0 (compatible; CensysInspect/1.1)"\n'
            '1.2.3.4 - - [10/Oct/2026:01:00:01 +0900] "GET / HTTP/1.1" 200 10 "-" "x"\n'
            '167.94.146.53 - - [10/Oct/2026:01:00:02 +0900] "GET /relay/ws/x?token=SECRET HTTP/1.1" 400 10 "-" "Mozilla/5.0 (compatible; CensysInspect/1.1)"\n')
        (root / "auth.log").write_text("Oct 10 sshd[1]: Invalid user admin from 167.94.146.53 port 1\nOct 10 sshd[1]: Failed password for invalid user admin from 167.94.146.53 port 1 ssh2\n")
        self.patches = [mock.patch("monitor.logs.LOG_ROOT", root)]
        for name in ("rdap", "ipinfo", "internetdb", "abuseipdb", "reverse_dns"):
            key = "rdns" if name == "reverse_dns" else name
            self.patches.append(mock.patch(f"security.iplookup.{name}", return_value=self.EXT[key]))
        self.patches.append(mock.patch("security.iplookup.tor_exits", return_value=set()))
        for p in self.patches:
            p.start()
        LoginEvent.objects.create(username="root", ip="167.94.146.53", result=LoginEvent.RESULT_FAILED)
        self.client.force_login(self.admin)

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def test_report_page(self):
        from django.urls import reverse

        res = self.client.get(reverse("studio:security_ip", args=["167.94.146.53"]))
        self.assertContains(res, "Censys (인터넷 전체 스캔 연구 회사)")
        self.assertContains(res, "scan-abuse@censys.io")
        self.assertContains(res, "<b>2번</b>", html=False)  # nginx 접속 2줄
        self.assertContains(res, "/.env")
        self.assertNotContains(res, "SECRET")  # 토큰 가림
        self.assertContains(res, "admin<span")  # SSH 로 시도한 아이디
        self.assertContains(res, "root<span")  # 사이트 로그인 시도 아이디
        self.assertContains(res, "We observed unwanted/abusive traffic from 167.94.146.53")

    def test_verdicts(self):
        from security import iplookup

        cloud = {**self.EXT, "rdns": ("", False), "ipinfo": {**self.EXT["ipinfo"], "hostname": "", "isp": "DigitalOcean, LLC"}, "rdap": {**self.EXT["rdap"], "orgs": ["DigitalOcean, LLC"], "network": "DO"}}
        self.assertEqual(iplookup.verdict(cloud)["kind"], "cloud")
        kt = {**cloud, "ipinfo": {**cloud["ipinfo"], "isp": "Korea Telecom", "country": "KR"}, "rdap": {**cloud["rdap"], "orgs": [], "network": "KORNET-KR"}}
        self.assertEqual(iplookup.verdict(kt)["kind"], "isp")
        self.assertEqual(iplookup.verdict({**kt, "tor": True})["kind"], "tor")

    def test_private_ip_and_bad_input(self):
        from django.urls import reverse

        res = self.client.get(reverse("studio:security_ip", args=["10.0.0.1"]))
        self.assertContains(res, "사설·내부 IP")
        self.assertEqual(self.client.get("/studio/security/ip/not-an-ip/").status_code, 404)

    def test_admin_only(self):
        from django.contrib.auth import get_user_model
        from django.urls import reverse

        self.client.force_login(get_user_model().objects.create_user("u", "u@example.com", "pw"))
        self.assertNotEqual(self.client.get(reverse("studio:security_ip", args=["167.94.146.53"])).status_code, 200)
