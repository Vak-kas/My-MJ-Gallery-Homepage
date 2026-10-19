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
