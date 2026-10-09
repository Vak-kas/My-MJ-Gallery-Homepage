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

    def signup(self, username="newbie", message="친구 소개로 왔어요", **extra):
        data = {
            "username": username, "email": f"{username}@example.com", "real_name": "김 철수",
            "password1": "Very-strong-pw-123", "password2": "Very-strong-pw-123", "message": message,
            "privacy_agree": "on",
        }
        data.update(extra)
        return self.client.post(reverse("accounts:signup"), {k: v for k, v in data.items() if v is not None})

    def test_real_name_and_consent_required(self):
        res = self.signup(privacy_agree=None)
        self.assertContains(res, "개인정보 수집·이용에 동의해야")
        res = self.signup(real_name=" ")
        self.assertFalse(User.objects.filter(username="newbie").exists())

    def test_real_name_saved_and_shown(self):
        self.signup()
        user = User.objects.get(username="newbie")
        self.assertEqual(user.first_name, "김 철수")
        self.assertIsNotNone(user.signup_request.privacy_agreed_at)
        self.assertIn("김 철수(newbie)", Notification.objects.get().title)
        self.client.force_login(self.admin)
        res = self.client.get(reverse("studio:users"), {"q": "철수"})
        self.assertContains(res, "김 철수")

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

    def test_loaddata_does_not_notify(self):
        import json
        import tempfile

        from django.core.management import call_command

        rows = [
            {"model": "blog.guestbookentry", "pk": 900, "fields": {"author": self.member.pk, "author_name": "member", "message": "옛 방명록", "created_at": "2026-01-01T00:00:00Z"}},
            {"model": "blog.comment", "pk": 900, "fields": {"post": self.post.pk, "author": self.member.pk, "author_name": "member", "content": "옛 댓글", "created_at": "2026-01-01T00:00:00Z", "updated_at": "2026-01-01T00:00:00Z"}},
        ]
        with tempfile.NamedTemporaryFile("w", suffix=".json") as f:
            json.dump(rows, f)
            f.flush()
            with mock.patch("notifications.service._run_background") as push:
                call_command("loaddata", f.name, verbosity=0)
        self.assertEqual(Notification.objects.count(), 0)
        push.assert_not_called()

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


@override_settings(KAKAO_REST_API_KEY="rest-key", KAKAO_CLIENT_SECRET="secret", SITE_URL="https://smjgallery.kr")
class KakaoTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser("admin", "a@example.com", "pw")
        self.member = User.objects.create_user("member", "m@example.com", "pw")
        self.client.force_login(self.admin)
        self.calls = []

    def fake_post(self, url, data, token=None):
        self.calls.append((url, data, token))
        if url.endswith("/oauth/token"):
            if data["grant_type"] == "authorization_code":
                return {"access_token": "A1", "refresh_token": "R1", "expires_in": 21599,
                        "refresh_token_expires_in": 5184000, "scope": "talk_message"}
            return {"access_token": "A2", "expires_in": 21599}
        return {"result_code": 0}

    def connect(self):
        res = self.client.post(reverse("notifications:kakao_connect"))
        self.assertTrue(res["Location"].startswith("https://kauth.kakao.com/oauth/authorize?"))
        self.assertIn("scope=talk_message", res["Location"])
        state = self.client.session["kakao_oauth_state"]
        with mock.patch("notifications.kakao._post", side_effect=self.fake_post):
            return self.client.get(reverse("notifications:kakao_callback"), {"code": "C", "state": state})

    def test_connect_saves_tokens_and_sends_test(self):
        from .models import KakaoLink
        self.connect()
        link = KakaoLink.objects.get()
        self.assertEqual((link.access_token, link.refresh_token, link.connected_by), ("A1", "R1", self.admin))
        token_call = self.calls[0]
        self.assertEqual(token_call[1]["client_secret"], "secret")
        self.assertEqual(token_call[1]["redirect_uri"], "http://testserver/notifications/kakao/callback/".replace("http://testserver", "https://smjgallery.kr"))
        self.assertTrue(self.calls[1][0].endswith("/talk/memo/default/send"))
        self.assertEqual(self.calls[1][2], "A1")

    def test_bad_state_rejected(self):
        self.client.post(reverse("notifications:kakao_connect"))
        with mock.patch("notifications.kakao._post", side_effect=self.fake_post) as post:
            self.client.get(reverse("notifications:kakao_callback"), {"code": "C", "state": "wrong"})
        post.assert_not_called()

    def test_notification_sends_kakao_and_refreshes_expired_token(self):
        from .models import KakaoLink
        self.connect()
        KakaoLink.objects.update(expires_at=timezone.now())  # 만료 → 갱신 후 전송
        self.calls.clear()
        with mock.patch("notifications.kakao._post", side_effect=self.fake_post), \
                mock.patch("notifications.service.threading.Thread") as thread:
            thread.side_effect = lambda target, daemon: mock.Mock(start=target)
            GuestbookEntry.objects.create(author=self.member, author_name="member", message="안녕")
        self.assertEqual(self.calls[0][1]["grant_type"], "refresh_token")
        url, data, token = self.calls[1]
        self.assertEqual(token, "A2")
        self.assertIn("방명록", data["template_object"])
        self.assertIn("https://smjgallery.kr/studio/community/", data["template_object"])
        link = KakaoLink.objects.get()
        self.assertEqual((link.access_token, link.refresh_token), ("A2", "R1"))
        self.assertIsNotNone(link.last_sent_at)

    def test_send_failure_recorded(self):
        from . import kakao
        from .models import KakaoLink
        self.connect()
        with mock.patch("notifications.kakao._post", side_effect=kakao.KakaoError("invalid token")):
            self.assertFalse(kakao.send_text("hi"))
        self.assertEqual(KakaoLink.objects.get().last_error, "invalid token")

    def test_member_cannot_connect(self):
        self.client.force_login(self.member)
        res = self.client.post(reverse("notifications:kakao_connect"))
        self.assertNotIn("kauth.kakao.com", res.get("Location", ""))
