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
