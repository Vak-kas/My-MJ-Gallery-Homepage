"""2026-11-05 보안 점검 '낮음' 항목 회귀 테스트"""

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse


class LogoutPostOnlyTests(TestCase):
	def test_get_does_not_log_out(self):
		user = get_user_model().objects.create_user("lo", "lo@x.kr", "pw-for-tests-only")
		self.client.force_login(user)
		res = self.client.get(reverse("accounts:logout"))
		self.assertEqual(res.status_code, 200)               # 확인 화면
		self.assertIn("_auth_user_id", self.client.session)   # 아직 로그인 상태
		self.assertContains(self.client.get("/"), 'id="logout-form"')
		self.client.post(reverse("accounts:logout"))
		self.assertNotIn("_auth_user_id", self.client.session)


class VerifyLinkEnumerationTests(TestCase):
	def test_verified_link_does_not_show_username(self):
		from accounts.models import SignupRequest
		from django.utils import timezone
		user = get_user_model().objects.create_user("secretname", "s@x.kr", "pw", is_active=False)
		SignupRequest.objects.create(user=user, email_verified_at=timezone.now())
		res = self.client.get(f"/accounts/verify/{user.id}/wrong-token/")
		self.assertNotContains(res, "secretname")


class LoginLockTests(TestCase):
	def setUp(self):
		cache.clear()

	def tearDown(self):
		cache.clear()

	def test_own_login_does_not_reset_ip_counter(self):
		User = get_user_model()
		User.objects.create_user("victim", "v@x.kr", "pw-victim-1234")
		User.objects.create_user("attacker", "a@x.kr", "pw-attacker-1234")
		for _ in range(9):
			self.client.post(reverse("accounts:login"), {"username": f"victim{_}", "password": "x"})
		self.client.post(reverse("accounts:login"), {"username": "attacker", "password": "pw-attacker-1234"})
		self.client.logout()
		self.client.post(reverse("accounts:login"), {"username": "victimz", "password": "x"})
		res = self.client.post(reverse("accounts:login"), {"username": "victim", "password": "pw-victim-1234"})
		self.assertContains(res, "잠시 잠겼어요")


class CsvAndIpTests(TestCase):
	def test_csv_cell_neutralizes_formulas(self):
		from studio.view_handlers.security import _csv_cell
		self.assertEqual(_csv_cell('=HYPERLINK("x")'), '\'=HYPERLINK("x")')
		self.assertEqual(_csv_cell("@SUM(1)"), "'@SUM(1)")
		self.assertEqual(_csv_cell("보통 댓글"), "보통 댓글")

	def test_ipv6_scope_id_rejected(self):
		from security.iplookup import parse
		self.assertIsNone(parse("2001:4860:4860::8888%x?y=1"))
		self.assertIsNotNone(parse("2001:4860:4860::8888"))


class MessageStorageTests(TestCase):
	def test_messages_not_in_cookie(self):
		from django.conf import settings
		self.assertEqual(settings.MESSAGE_STORAGE, "django.contrib.messages.storage.session.SessionStorage")


class ReplyHeaderTests(TestCase):
	def test_folded_references_are_unfolded(self):
		from webmail.scheduled import build_message
		msg = build_message(["a@example.com"], [], [], "re", "body", in_reply_to="<a@b>\r\n <c@d>", references="<x@y>\r\n\t<z@w>")
		m = msg.message()
		self.assertEqual(m["In-Reply-To"], "<a@b> <c@d>")
		self.assertNotIn("\n", m["References"].replace("\n ", " ").replace("\r", ""))
