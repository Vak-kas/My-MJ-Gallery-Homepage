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
        Post.objects.create(title="내 글", slug="my-post", category="life", author=self.u, content="x")
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

    def test_profile_edit_needs_password_and_unique_email(self):
        User.objects.create_user("other", "taken@example.com", "pw")
        self.client.login(username="minjae", password="Old-pw-12345")
        res = self.client.post(reverse("accounts:profile_edit"), {"real_name": "서 민재", "email": "new@example.com", "password": "wrong"})
        self.assertContains(res, "비밀번호가 맞지 않아요")
        res = self.client.post(reverse("accounts:profile_edit"), {"real_name": "서 민재", "email": "TAKEN@example.com", "password": "Old-pw-12345"})
        self.assertContains(res, "이미 다른 계정이 쓰는 이메일")
        res = self.client.post(reverse("accounts:profile_edit"), {"real_name": "서  민재", "email": "new@example.com", "password": "Old-pw-12345"})
        self.assertRedirects(res, reverse("accounts:index"))
        self.u.refresh_from_db()
        self.assertEqual((self.u.first_name, self.u.email), ("서 민재", "new@example.com"))

    def test_superuser_cannot_self_delete(self):
        User.objects.create_superuser("boss", "b@example.com", "pw")
        self.client.login(username="boss", password="pw")
        self.assertRedirects(self.client.get(reverse("accounts:delete")), reverse("accounts:index"))
        self.assertTrue(User.objects.filter(username="boss").exists())

    def test_admin_temp_password_forces_change(self):
        admin = User.objects.create_superuser("boss", "b@example.com", "pw")
        self.client.login(username="boss", password="pw")
        res = self.client.post(reverse("studio:users"), {"action": "reset_password", "ids": str(self.u.id)}, follow=True)   # 확인 없이 → 거부
        self.assertTrue(any("아이디(minjae)를 똑같이" in str(m) for m in res.context["messages"]))
        self.assertFalse(MustChangePassword.objects.filter(user=self.u).exists())
        res = self.client.post(reverse("studio:users"), {"action": "reset_password", "ids": str(self.u.id), "confirm": "minjae"}, follow=True)
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
        res = self.client.post(reverse("studio:users"), {"action": "reset_password", "ids": str(admin.id), "confirm": "boss"}, follow=True)
        self.assertTrue(any("초기화할 수 없어요" in str(m) for m in res.context["messages"]))


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend", MAIL_ENABLED=True)
class EmailVerificationTests(TestCase):
    def setUp(self):
        cache.clear()
        self.push = mock.patch("notifications.service._run_background")
        self.push.start()
        self.addCleanup(self.push.stop)
        self.admin = User.objects.create_superuser("admin", "a@example.com", "pw")

    def signup(self, username="newbie"):
        data = {
            "username": username, "email": f"{username}@example.com", "real_name": "김 철수",
            "password1": "Very-strong-pw-123", "password2": "Very-strong-pw-123", "message": "안녕하세요", "privacy_agree": "on",
            **human_fields(),
        }
        return self.client.post(reverse("accounts:signup"), data, HTTP_USER_AGENT=HUMAN_UA)

    def test_signup_sends_link_and_only_verified_become_pending(self):
        from notifications.models import Notification
        res = self.signup()
        self.assertContains(res, "이메일을 확인해 주세요")
        sr = User.objects.get(username="newbie").signup_request
        self.assertTrue(sr.needs_verification)
        self.assertEqual(Notification.objects.filter(kind=Notification.KIND_SIGNUP).count(), 0)   # 인증 전엔 관리자 알림 없음
        self.assertEqual(len(mail.outbox), 1)
        link = [w for w in mail.outbox[0].body.split() if "/accounts/verify/" in w][0].replace("https://smjgallery.kr", "")
        # 인증 전 로그인 시도 → 안내 + 다시 보내기 링크
        res = self.client.post(reverse("accounts:login"), {"username": "newbie", "password": "Very-strong-pw-123"})
        self.assertContains(res, "이메일 인증이 아직")
        self.assertContains(res, "인증 메일 다시 받기")
        # Studio: 미인증 칸에 보이고 승인 대기엔 안 셈
        self.client.force_login(self.admin)
        res = self.client.get(reverse("studio:users"))
        self.assertContains(res, "📧 이메일 미인증")
        self.assertEqual(res.context["pending_count"], 0)
        self.client.logout()
        # 링크 → 인증 완료 → 관리자 알림, 승인 대기
        res = self.client.get(link)
        self.assertContains(res, "이메일 인증 완료")
        sr.refresh_from_db()
        self.assertFalse(sr.needs_verification)
        self.assertIsNotNone(sr.email_verified_at)
        self.assertEqual(Notification.objects.filter(kind=Notification.KIND_SIGNUP).count(), 1)
        self.assertContains(self.client.get(link), "이미 인증됐어요")
        res = self.client.post(reverse("accounts:login"), {"username": "newbie", "password": "Very-strong-pw-123"})
        self.assertContains(res, "승인 대기 중")
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse("studio:users")).context["pending_count"], 1)

    def test_bad_or_expired_link_and_resend(self):
        self.signup()
        sr = User.objects.get(username="newbie").signup_request
        res = self.client.get(reverse("accounts:verify_email", args=[sr.user_id, "wrong-token"]))
        self.assertEqual(res.status_code, 400)
        self.assertContains(res, "링크가 맞지 않아요", status_code=400)
        SignupRequest.objects.filter(pk=sr.pk).update(verify_sent_at=timezone_now() - timedelta(hours=49))
        sr.refresh_from_db()
        res = self.client.get(reverse("accounts:verify_email", args=[sr.user_id, sr.verify_token]))
        self.assertEqual(res.status_code, 400)
        # 다시 보내기 → 새 토큰으로 메일
        res = self.client.post(reverse("accounts:verify_resend"), {"email": "NEWBIE@example.com"})
        self.assertContains(res, "몇 분 안에 메일이 가요")
        self.assertEqual(len(mail.outbox), 2)
        new = User.objects.get(username="newbie").signup_request
        self.assertNotEqual(new.verify_token, sr.verify_token)
        self.assertContains(self.client.get(reverse("accounts:verify_email", args=[new.user_id, new.verify_token])), "인증 완료")
        # 없는 이메일도 같은 화면, 메일은 안 감
        res = self.client.post(reverse("accounts:verify_resend"), {"email": "nobody@example.com"})
        self.assertContains(res, "몇 분 안에 메일이 가요")
        self.assertEqual(len(mail.outbox), 2)

    def test_unverified_accounts_are_deleted_after_a_week(self):
        from accounts.models import cleanup_unverified
        self.signup("old")
        self.signup("fresh")
        SignupRequest.objects.filter(user__username="old").update(verify_sent_at=timezone_now() - timedelta(days=8))
        self.assertEqual(cleanup_unverified(), 1)
        self.assertFalse(User.objects.filter(username="old").exists())
        self.assertTrue(User.objects.filter(username="fresh").exists())

    @override_settings(MAIL_ENABLED=False)
    def test_without_mail_signup_goes_straight_to_pending(self):
        from notifications.models import Notification
        res = self.signup()
        self.assertContains(res, "가입 신청이 접수됐어요")
        sr = User.objects.get(username="newbie").signup_request
        self.assertFalse(sr.needs_verification)
        self.assertEqual(Notification.objects.filter(kind=Notification.KIND_SIGNUP).count(), 1)
        self.assertEqual(len(mail.outbox), 0)


from datetime import timedelta
from django.utils.timezone import now as timezone_now


class UsernameNormalizationTests(TestCase):
    def test_login_matches_signup_normalization(self):
        # 가입 폼은 NFKC 로 저장 → 'ㅎㅇ'(U+314E U+3147) 가 'ᄒᄋ'(U+1112 U+110B) 로 바뀜. 로그인도 같은 규칙이어야 함
        stored = unicodedata.normalize("NFKC", "ㅎㅇ")
        self.assertNotEqual(stored, "ㅎㅇ")
        User.objects.create_user(stored, "n@example.com", "Very-strong-pw-123")
        res = self.client.post(reverse("accounts:login"), {"username": "ㅎㅇ", "password": "Very-strong-pw-123"})
        self.assertEqual(res.status_code, 302)
        res = self.client.post(reverse("accounts:login"), {"username": " ㅎㅇ ", "password": "Very-strong-pw-123"})
        self.assertEqual(res.status_code, 302)


import unicodedata


class TwoFactorEmailTests(TestCase):
    """메일 코드 2단계 인증 + 모든 기기에서 로그아웃"""

    def setUp(self):
        from django.core.cache import cache

        cache.clear()
        User = get_user_model()
        self.user = User.objects.create_user("em-user", "em@example.com", "pw-1234-ok")

    def _code_from_mail(self):
        import re

        from django.core import mail

        return re.search(r"인증 코드: (\d{6})", mail.outbox[-1].body).group(1)

    def test_setup_login_resend_backup(self):
        from django.core import mail
        from django.test import override_settings

        from accounts.models import TwoFactor

        with override_settings(MAIL_ENABLED=True, EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend"):
            self.client.force_login(self.user)
            self.assertContains(self.client.get(reverse("accounts:index")), "지금 켜기")
            res = self.client.post(reverse("accounts:two_factor"), {"action": "start"})
            self.assertContains(res, "em***@example.com")
            self.assertEqual(len(mail.outbox), 1)
            res = self.client.post(reverse("accounts:two_factor"), {"action": "confirm", "code": "000000"})
            self.assertContains(res, "코드가 맞지 않아요")
            res = self.client.post(reverse("accounts:two_factor"), {"action": "confirm", "code": self._code_from_mail()})
            self.assertContains(res, "백업 코드를 지금 저장하세요")
            tf = TwoFactor.objects.get(user=self.user)
            self.assertTrue(tf.enabled)
            self.assertEqual(len(tf.backup_codes), 10)
            self.assertIn("mj2fa", res.cookies)
            # 로그인: 코드 화면에 들어가면 메일 자동 발송, 1분 안 재발송 거부
            self.client.logout()
            res = self.client.post(reverse("accounts:login"), {"username": "em-user", "password": "pw-1234-ok"})
            self.assertRedirects(res, reverse("accounts:two_factor_verify"), fetch_redirect_response=False)
            self.assertNotIn("_auth_user_id", self.client.session)
            res = self.client.get(reverse("accounts:two_factor_verify"))
            self.assertContains(res, "em***@example.com")
            self.assertEqual(len(mail.outbox), 2)
            self.assertContains(self.client.post(reverse("accounts:two_factor_verify"), {"action": "resend"}), "1분 뒤에 다시")
            self.assertContains(self.client.post(reverse("accounts:two_factor_verify"), {"code": "111111"}), "코드가 맞지 않아요")
            res = self.client.post(reverse("accounts:two_factor_verify"), {"code": self._code_from_mail(), "remember": "1"})
            self.assertEqual(res.status_code, 302)
            self.assertEqual(str(self.client.session["_auth_user_id"]), str(self.user.id))
            trust = res.cookies["mj2fa"].value
            # 기억한 브라우저는 코드 생략
            self.client.logout()
            self.client.cookies["mj2fa"] = trust
            res = self.client.post(reverse("accounts:login"), {"username": "em-user", "password": "pw-1234-ok"})
            self.assertNotEqual(res["Location"], reverse("accounts:two_factor_verify"))
            # 백업 코드는 한 번만
            from django.contrib.auth.hashers import make_password

            tf.backup_codes = [make_password("12345678")]
            tf.save()
            self.client.logout(); self.client.cookies.clear()
            self.client.post(reverse("accounts:login"), {"username": "em-user", "password": "pw-1234-ok"})
            self.assertEqual(self.client.post(reverse("accounts:two_factor_verify"), {"code": "1234 5678"}).status_code, 302)
            tf.refresh_from_db()
            self.assertEqual(tf.backup_codes, [])
            self.client.logout()
            self.client.post(reverse("accounts:login"), {"username": "em-user", "password": "pw-1234-ok"})
            self.assertContains(self.client.post(reverse("accounts:two_factor_verify"), {"code": "12345678"}), "코드가 맞지 않아요")

    def test_disable_needs_password_and_code(self):
        from django.test import override_settings

        from accounts.models import TwoFactor

        tf = TwoFactor.objects.create(user=self.user, enabled=True)
        tf.issue_backup_codes()
        with override_settings(MAIL_ENABLED=True, EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend"):
            self.client.force_login(self.user)
            self.client.post(reverse("accounts:two_factor"), {"action": "send_code"})
            code = self._code_from_mail()
            self.assertContains(self.client.post(reverse("accounts:two_factor"), {"action": "disable", "password": "wrong", "code": code}), "비밀번호가 맞지 않아요")
            res = self.client.post(reverse("accounts:two_factor"), {"action": "disable", "password": "pw-1234-ok", "code": code})
            self.assertEqual(res.status_code, 302)
            self.assertFalse(TwoFactor.objects.filter(user=self.user).exists())

    def test_setup_requires_email(self):
        from django.test import override_settings

        User = get_user_model()
        u = User.objects.create_user("no-mail", "", "pw-1234-ok")
        self.client.force_login(u)
        with override_settings(MAIL_ENABLED=True):
            res = self.client.get(reverse("accounts:two_factor"))
            self.assertContains(res, "메일 주소를 넣어 주세요")
            self.assertEqual(self.client.post(reverse("accounts:two_factor"), {"action": "start"}).status_code, 302)

    def test_verify_without_pending_redirects(self):
        res = self.client.get(reverse("accounts:two_factor_verify"))
        self.assertRedirects(res, reverse("accounts:login"), fetch_redirect_response=False)

    def test_logout_all_kills_other_sessions_and_trust(self):
        from django.core import signing
        from django.test import Client

        from accounts.models import TwoFactor, logout_everywhere

        tf = TwoFactor.objects.create(user=self.user, enabled=True)
        other = Client()
        other.force_login(self.user)
        self.assertEqual(other.get(reverse("accounts:index")).status_code, 200)
        self.client.force_login(self.user)
        self.client.post(reverse("accounts:logout_all"), {"password": "wrong"})
        self.assertEqual(other.get(reverse("accounts:index")).status_code, 200)
        res = self.client.post(reverse("accounts:logout_all"), {"password": "pw-1234-ok"})
        self.assertEqual(res.status_code, 302)
        self.assertEqual(self.client.get(reverse("accounts:index")).status_code, 200)  # 지금 브라우저는 유지
        self.assertEqual(other.get(reverse("accounts:index")).status_code, 302)  # 다른 기기는 끊김
        tf.refresh_from_db()
        self.assertEqual(tf.trust_version, 1)
        self.client.logout()
        self.client.cookies["mj2fa"] = signing.dumps({"u": self.user.id, "p": self.user.password[-12:], "v": 0}, salt="accounts.2fa.trust")
        res = self.client.post(reverse("accounts:login"), {"username": "em-user", "password": "pw-1234-ok"})
        self.assertEqual(res["Location"], reverse("accounts:two_factor_verify"))
        self.assertEqual(logout_everywhere(self.user), 0)



class AdminLoginRedirectTests(TestCase):
	"""/admin/login/ 은 2단계 인증·잠금이 있는 사이트 로그인으로 (Django 기본 관리자 로그인 우회 방지)"""

	def test_get_and_post_go_to_site_login(self):
		from django.contrib.auth import get_user_model
		get_user_model().objects.create_superuser("boss2", "b@x.kr", "pw-for-tests-only")
		res = self.client.get("/admin/login/?next=/admin/")
		self.assertEqual(res.status_code, 302)
		self.assertTrue(res["Location"].startswith("/accounts/login/?next=%2Fadmin%2F"))
		res = self.client.post("/admin/login/", {"username": "boss2", "password": "pw-for-tests-only"})
		self.assertEqual(res.status_code, 302)
		self.assertNotIn("_auth_user_id", self.client.session)   # 여기서는 로그인되지 않음
		res = self.client.get("/admin/login/?next=https://evil.example/")
		self.assertIn("next=%2Fadmin%2F", res["Location"])
		self.assertEqual(self.client.get("/admin/").status_code, 302)
