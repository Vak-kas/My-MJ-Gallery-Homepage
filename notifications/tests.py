from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import SignupRequest
from blog.models import Comment, GuestbookEntry, Post

from .models import Notification

User = get_user_model()


class SignupApprovalTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser("admin", "a@example.com", "pw")

    def signup(self, username="newbie", message="친구 소개로 왔어요"):
        return self.client.post(reverse("accounts:signup"), {
            "username": username, "email": f"{username}@example.com",
            "password1": "Very-strong-pw-123", "password2": "Very-strong-pw-123", "message": message,
        })

    def test_signup_creates_pending_inactive_user_and_notification(self):
        res = self.signup()
        self.assertContains(res, "가입 신청이 접수됐어요")
        user = User.objects.get(username="newbie")
        self.assertFalse(user.is_active)
        self.assertEqual(user.signup_request.status, SignupRequest.STATUS_PENDING)
        self.assertEqual(user.signup_request.message, "친구 소개로 왔어요")
        n = Notification.objects.get()
        self.assertEqual(n.kind, Notification.KIND_SIGNUP)
        self.assertIn("newbie", n.title)
        self.assertNotIn("_auth_user_id", self.client.session)  # 자동 로그인 안 됨

    def test_pending_user_login_message(self):
        self.signup()
        res = self.client.post(reverse("accounts:login"), {"username": "newbie", "password": "Very-strong-pw-123"})
        self.assertContains(res, "승인 대기 중")
        res = self.client.post(reverse("accounts:login"), {"username": "newbie", "password": "wrong"})
        self.assertContains(res, "아이디 또는 비밀번호가 올바르지 않습니다")

    def test_approve_then_login(self):
        self.signup()
        user = User.objects.get(username="newbie")
        self.client.force_login(self.admin)
        res = self.client.get(reverse("studio:users"), {"state": "pending"})
        self.assertEqual([u.username for u in res.context["users"]], ["newbie"])
        self.client.post(reverse("studio:users"), {"action": "activate", "ids": [user.id]})
        user.refresh_from_db()
        self.assertTrue(user.is_active)
        self.assertEqual(user.signup_request.status, SignupRequest.STATUS_APPROVED)
        self.assertEqual(user.signup_request.decided_by, self.admin)
        self.client.logout()
        res = self.client.post(reverse("accounts:login"), {"username": "newbie", "password": "Very-strong-pw-123"})
        self.assertEqual(res.status_code, 302)

    def test_reject(self):
        self.signup()
        user = User.objects.get(username="newbie")
        self.client.force_login(self.admin)
        self.client.post(reverse("studio:users"), {"action": "reject", "ids": [user.id]})
        user.refresh_from_db()
        self.assertFalse(user.is_active)
        self.assertEqual(user.signup_request.status, SignupRequest.STATUS_REJECTED)
        res = self.client.get(reverse("studio:users"), {"state": "pending"})
        self.assertEqual(res.context["users"], [])
        self.client.logout()
        res = self.client.post(reverse("accounts:login"), {"username": "newbie", "password": "Very-strong-pw-123"})
        self.assertContains(res, "승인되지 않았어요")


class NotificationTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser("admin", "a@example.com", "pw")
        self.member = User.objects.create_user("member", "m@example.com", "pw")
        self.post = Post.objects.create(category="tech", title="내 글", slug="p1", author=self.admin, published_at=timezone.now())

    def test_admin_own_actions_do_not_notify(self):
        Comment.objects.create(post=self.post, author=self.admin, author_name="admin", content="내 댓글")
        GuestbookEntry.objects.create(author=self.admin, author_name="admin", message="hi")
        self.assertEqual(Notification.objects.count(), 0)  # 관리자 본인 글(setUp)도 알림 없음

    def test_member_activity_notifies(self):
        Comment.objects.create(post=self.post, author=self.member, author_name="member", content="좋아요")
        GuestbookEntry.objects.create(author=self.member, author_name="member", message="안녕")
        Post.objects.create(category="board", title="회원 글", slug="p2", author=self.member, published_at=timezone.now())
        Post.objects.create(category="board", title="임시", slug="p3", author=self.member, is_published=False)
        kinds = sorted(Notification.objects.values_list("kind", flat=True))
        self.assertEqual(kinds, ["comment", "guestbook", "post"])

    def test_bell_count_and_open_marks_read(self):
        Comment.objects.create(post=self.post, author=self.member, author_name="member", content="좋아요")
        self.client.force_login(self.admin)
        res = self.client.get(reverse("blog:index"))
        self.assertEqual(res.context["notif_unread_count"], 1)
        self.assertContains(res, reverse("notifications:list"))
        n = Notification.objects.get()
        res = self.client.post(reverse("notifications:open", args=[n.id]))
        self.assertRedirects(res, reverse("blog:post_detail", args=["p1"]) + "#comments", fetch_redirect_response=False)
        n.refresh_from_db()
        self.assertTrue(n.is_read)

    def test_member_cannot_see_notifications(self):
        self.client.force_login(self.member)
        self.assertEqual(self.client.get(reverse("notifications:list")).status_code, 302)
        res = self.client.get(reverse("blog:index"))
        self.assertNotIn("notif_unread_count", res.context)

    def test_read_all_and_clear(self):
        GuestbookEntry.objects.create(author=self.member, author_name="member", message="안녕")
        self.client.force_login(self.admin)
        self.client.post(reverse("notifications:read_all"))
        self.assertFalse(Notification.objects.filter(is_read=False).exists())
        self.client.post(reverse("notifications:clear_read"))
        self.assertFalse(Notification.objects.exists())

    @override_settings(NTFY_TOPIC_URL="https://ntfy.example/topic", SITE_URL="https://smjgallery.kr")
    def test_ntfy_push(self):
        with mock.patch("notifications.service.urllib.request.urlopen") as urlopen, \
                mock.patch("notifications.service.threading.Thread") as thread:
            thread.side_effect = lambda target, daemon: mock.Mock(start=target)
            GuestbookEntry.objects.create(author=self.member, author_name="member", message="안녕")
        req = urlopen.call_args[0][0]
        self.assertEqual(req.full_url, "https://ntfy.example/topic")
        self.assertEqual(req.data, "안녕".encode())
        self.assertTrue(req.headers["Click"].startswith("https://smjgallery.kr/studio/community/"))
