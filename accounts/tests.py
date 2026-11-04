from unittest import mock

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from accounts import antibot
from accounts.models import SignupRequest
from notifications.tests import human_fields
from security.models import IPBlock, LoginEvent

User = get_user_model()

BOT_UA = "Mozilla/4.0 (compatible; MSIE 7.0; Windows NT 6.1; Trident/6.0)"
HUMAN_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"


class SignupAntibotTests(TestCase):
    def setUp(self):
        cache.delete(antibot._key("127.0.0.1"))
        push = mock.patch("notifications.service._run_background")  # 카카오 푸시는 보내지 않음
        push.start()
        self.addCleanup(push.stop)
        self.admin = User.objects.create_superuser("admin", "a@example.com", "pw")

    def post(self, username="newbie", ua=HUMAN_UA, extra=None, **over):
        data = {
            "username": username, "email": f"{username}@example.com", "real_name": "김 철수",
            "password1": "Very-strong-pw-123", "password2": "Very-strong-pw-123", "message": "안녕하세요",
            "privacy_agree": "on", **human_fields(), **(extra or {}),
        }
        data.update(over)
        return self.client.post(reverse("accounts:signup"), data, HTTP_USER_AGENT=ua)

    def test_form_has_hidden_fields(self):
        res = self.client.get(reverse("accounts:signup"))
        self.assertContains(res, 'name="website"')
        self.assertContains(res, 'name="form_token"')
        self.assertContains(res, 'id="js_check"')

    def test_human_signup_saves_ip_and_agent(self):
        self.post()
        sr = User.objects.get(username="newbie").signup_request
        self.assertEqual(sr.ip, "127.0.0.1")
        self.assertIn("Safari", sr.user_agent)
        self.assertEqual(sr.flags, "")

    def test_bots_get_fake_success_and_nothing_is_saved(self):
        cases = {
            "honeypot": {"website": "http://spam.example"},
            "no_js": {"js_check": ""},
            "too_fast": human_fields(age=0),
            "bad_token": {"form_token": "forged", "js_check": "degrof"},
        }
        for i, (name, extra) in enumerate(cases.items()):
            with self.subTest(name):
                res = self.post(username=f"bot{i}", extra=extra)
                self.assertContains(res, "가입 신청이 접수됐어요")  # 봇에겐 가입된 척
                self.assertFalse(User.objects.filter(username=f"bot{i}").exists())
        self.assertEqual(LoginEvent.objects.filter(result=LoginEvent.RESULT_BOT).count(), 4)

    def test_same_ip_rate_limit(self):
        for i in range(antibot.RATE_LIMIT):
            self.post(username=f"user{i}")
        res = self.post(username="onemore")
        self.assertContains(res, "1시간 뒤에")
        self.assertFalse(User.objects.filter(username="onemore").exists())
        self.assertEqual(User.objects.filter(username__startswith="user").count(), antibot.RATE_LIMIT)

    def test_suspicion_flags_like_the_real_bot(self):
        self.post(username="vpymengwil", ua=BOT_UA, email="klykweuy@formtests.info",
                  real_name="wyehmknqud", message="hhylkoisndqslxlumxgmssslpjwfmo")
        sr = User.objects.get(username="vpymengwil").signup_request
        self.assertEqual(sr.flag_list, ["무작위 이름", "무작위 인사", "일회용 메일", "이상한 브라우저"])
        # 사람 이름·한글은 의심하지 않음
        self.assertEqual(antibot.suspicion("minjae", "서민재", "잘 부탁드려요", "a@gmail.com", HUMAN_UA), [])
        self.assertEqual(antibot.suspicion("jschmidt", "John Schmidt", "hello there", "j@naver.com", HUMAN_UA), [])

    def test_studio_shows_flags_and_blocks_ip(self):
        self.post(username="vpymengwil", ua=BOT_UA, real_name="wyehmknqud")
        sr = SignupRequest.objects.get(user__username="vpymengwil")
        SignupRequest.objects.filter(pk=sr.pk).update(ip="198.46.1.2")
        self.client.force_login(self.admin)
        res = self.client.get(reverse("studio:users"), {"state": "pending"})
        self.assertContains(res, "🤖 무작위 이름")
        self.assertContains(res, "198.46.1.2")
        self.assertContains(res, "이 IP 차단")
        self.client.post(reverse("studio:users"), {"action": "block_ip", "ip": "198.46.1.2", "username": "vpymengwil"})
        block = IPBlock.objects.get()
        self.assertEqual(block.network, "198.46.1.2")
        self.assertIn("vpymengwil", block.reason)
        self.assertIsNotNone(block.expires_at)  # 30일


from django.core import mail
from django.test import override_settings

from accounts.models import MustChangePassword
from accounts.views import mask_username


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend", MAIL_ENABLED=True)
class RecoveryTests(TestCase):
    def setUp(self):
        cache.clear()
        self.u = User.objects.create_user("minjae", "m@example.com", "Old-pw-12345", first_name="서민재")

    def test_mask(self):
        self.assertEqual(mask_username("minjae"), "mi***e")
        self.assertEqual(mask_username("abcd"), "a**d")
        self.assertEqual(mask_username("ab"), "a*")

    def test_find_id_masks_and_mails(self):
        res = self.client.post(reverse("accounts:find_id"), {"real_name": "서민재", "email": "M@example.com"})
        self.assertContains(res, "mi***e")
        self.assertNotContains(res, ">minjae<")
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("minjae", mail.outbox[0].body)
        res = self.client.post(reverse("accounts:find_id"), {"real_name": "다른이름", "email": "m@example.com"})
        self.assertContains(res, "같은 계정이 없어요")
        self.assertEqual(len(mail.outbox), 1)

    def test_find_id_rate_limited(self):
        for _ in range(10):
            self.client.post(reverse("accounts:find_id"), {"real_name": "x", "email": "x@example.com"})
        res = self.client.post(reverse("accounts:find_id"), {"real_name": "서민재", "email": "m@example.com"})
        self.assertContains(res, "시도가 너무 많아요")
        self.assertNotContains(res, "mi***e")

    def test_password_reset_by_mail_link(self):
        res = self.client.post(reverse("accounts:password_reset"), {"email": "m@example.com"})
        self.assertRedirects(res, reverse("accounts:password_reset_done"))
        self.assertEqual(len(mail.outbox), 1)
        link = [w for w in mail.outbox[0].body.split() if "/accounts/password/reset/" in w][0]
        path = link.replace("https://smjgallery.kr", "")
        res = self.client.get(path, follow=True)   # 토큰 → 세션으로 바꿔 주는 리다이렉트
        self.assertContains(res, "새 비밀번호")
        res = self.client.post(res.request["PATH_INFO"], {"new_password1": "Brand-new-pw-987", "new_password2": "Brand-new-pw-987"})
        self.assertRedirects(res, reverse("accounts:password_reset_complete"))
        self.u.refresh_from_db()
        self.assertTrue(self.u.check_password("Brand-new-pw-987"))
        self.assertTrue(self.client.login(username="minjae", password="Brand-new-pw-987"))

    @override_settings(MAIL_ENABLED=False)
    def test_password_reset_unavailable_without_mail(self):
        res = self.client.get(reverse("accounts:password_reset"))
        self.assertContains(res, "관리자에게 비밀번호 초기화를 부탁")
        res = self.client.post(reverse("accounts:password_reset"), {"email": "m@example.com"}, follow=True)
        self.assertEqual(len(mail.outbox), 0)
        self.assertContains(res, "메일을 보낼 수 없어서")

    def test_change_password_needs_current(self):
        self.client.login(username="minjae", password="Old-pw-12345")
        res = self.client.post(reverse("accounts:password_change"), {"old_password": "wrong", "new_password1": "Brand-new-pw-987", "new_password2": "Brand-new-pw-987"})
        self.assertEqual(res.status_code, 200)
        res = self.client.post(reverse("accounts:password_change"), {"old_password": "Old-pw-12345", "new_password1": "Brand-new-pw-987", "new_password2": "Brand-new-pw-987"})
        self.assertRedirects(res, reverse("accounts:index"))
        self.u.refresh_from_db()
        self.assertTrue(self.u.check_password("Brand-new-pw-987"))
        self.assertEqual(self.client.get(reverse("accounts:index")).status_code, 200)   # 로그인 유지

    def test_delete_account_removes_user_and_content(self):
        from blog.models import Post
        Post.objects.create(title="내 글", slug="my-post", category="board", author=self.u, content="x")
        self.client.login(username="minjae", password="Old-pw-12345")
        res = self.client.get(reverse("accounts:delete"))
        self.assertContains(res, "<b>1</b>")
        res = self.client.post(reverse("accounts:delete"), {"password": "wrong", "agree": "on"})
        self.assertContains(res, "비밀번호가 맞지 않아요")
        res = self.client.post(reverse("accounts:delete"), {"password": "Old-pw-12345", "agree": "on"})
        self.assertContains(res, "탈퇴했어요")
        self.assertFalse(User.objects.filter(username="minjae").exists())
        self.assertFalse(Post.objects.filter(slug="my-post").exists())
        self.assertEqual(self.client.get(reverse("accounts:index")).status_code, 302)   # 로그아웃됨

    def test_superuser_cannot_self_delete(self):
        User.objects.create_superuser("boss", "b@example.com", "pw")
        self.client.login(username="boss", password="pw")
        self.assertRedirects(self.client.get(reverse("accounts:delete")), reverse("accounts:index"))
        self.assertTrue(User.objects.filter(username="boss").exists())

    def test_admin_temp_password_forces_change(self):
        admin = User.objects.create_superuser("boss", "b@example.com", "pw")
        self.client.login(username="boss", password="pw")
        res = self.client.post(reverse("studio:users"), {"action": "reset_password", "ids": str(self.u.id)}, follow=True)
        msg = [str(m) for m in res.context["messages"] if "임시 비밀번호" in str(m)][0]
        temp = msg.split("임시 비밀번호: ")[1].split()[0]
        self.assertTrue(MustChangePassword.objects.filter(user=self.u, issued_by=admin).exists())
        self.client.logout()
        # 임시 비밀번호로 로그인 → 바로 변경 화면, 다른 화면은 막힘
        res = self.client.post(reverse("accounts:login"), {"username": "minjae", "password": temp})
        self.assertRedirects(res, reverse("accounts:password_change"))
        self.assertRedirects(self.client.get(reverse("tools:index")), reverse("accounts:password_change"))
        res = self.client.post(reverse("accounts:password_change"), {"old_password": temp, "new_password1": "Brand-new-pw-987", "new_password2": "Brand-new-pw-987"})
        self.assertRedirects(res, reverse("accounts:index"))
        self.assertFalse(MustChangePassword.objects.filter(user=self.u).exists())
        self.assertEqual(self.client.get(reverse("tools:index")).status_code, 200)
        # 관리자 자신·다른 관리자는 초기화 불가
        self.client.login(username="boss", password="pw")
        res = self.client.post(reverse("studio:users"), {"action": "reset_password", "ids": str(admin.id)}, follow=True)
        self.assertTrue(any("초기화할 수 없어요" in str(m) for m in res.context["messages"]))
