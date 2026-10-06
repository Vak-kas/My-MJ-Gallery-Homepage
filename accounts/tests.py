import re

from django.contrib.auth.models import User
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.verification import mask_email

SIGNUP = {
	"username": "newbie",
	"email": "newbie@example.com",
	"password1": "Str0ng-pass-for-tests",
	"password2": "Str0ng-pass-for-tests",
}


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class EmailVerificationTests(TestCase):
	def _signup(self, **overrides):
		return self.client.post(reverse("accounts:signup"), {**SIGNUP, **overrides})

	def _link_from_mail(self):
		self.assertEqual(len(mail.outbox), 1)
		return re.search(r"https?://\S+/accounts/verify/\S+/\S+/", mail.outbox[0].body).group(0)

	def test_signup_creates_inactive_user_and_sends_mail(self):
		resp = self._signup()
		self.assertRedirects(resp, reverse("accounts:verify_sent"))
		user = User.objects.get(username="newbie")
		self.assertFalse(user.is_active)
		self.assertEqual(mail.outbox[0].to, ["newbie@example.com"])
		self.assertNotIn("_auth_user_id", self.client.session)

	def test_link_activates_and_logs_in(self):
		self._signup()
		link = self._link_from_mail()
		resp = self.client.get(link)
		self.assertContains(resp, "인증 완료")
		self.assertTrue(User.objects.get(username="newbie").is_active)
		self.assertIn("_auth_user_id", self.client.session)

	def test_bad_token_is_rejected(self):
		self._signup()
		link = self._link_from_mail()
		resp = self.client.get(link.rstrip("/")[:-3] + "xyz/")
		self.assertEqual(resp.status_code, 400)
		self.assertFalse(User.objects.get(username="newbie").is_active)

	def test_unverified_login_goes_to_verify_page(self):
		self._signup()
		self.client.logout()
		resp = self.client.post(reverse("accounts:login"), {"username": "newbie", "password": SIGNUP["password1"]})
		self.assertRedirects(resp, reverse("accounts:verify_sent"))
		self.assertNotIn("_auth_user_id", self.client.session)

	def test_unverified_wrong_password_shows_generic_error(self):
		self._signup()
		resp = self.client.post(reverse("accounts:login"), {"username": "newbie", "password": "wrong"})
		self.assertContains(resp, "아이디 또는 비밀번호가 올바르지 않습니다")

	def test_resend_has_cooldown(self):
		self._signup()
		self.client.post(reverse("accounts:verify_resend"))
		self.client.post(reverse("accounts:verify_resend"))
		self.assertEqual(len(mail.outbox), 2)  # 가입 1 + 재발송 1 (두 번째는 1분 제한)

	def test_existing_active_users_still_log_in(self):
		User.objects.create_user("old", "old@example.com", "Str0ng-pass-for-tests")
		resp = self.client.post(reverse("accounts:login"), {"username": "old", "password": "Str0ng-pass-for-tests"})
		self.assertEqual(resp.status_code, 302)
		self.assertIn("_auth_user_id", self.client.session)

	def test_email_must_be_unique_case_insensitive(self):
		User.objects.create_user("other", "Newbie@Example.com", "x")
		resp = self._signup()
		self.assertContains(resp, "이미 사용 중인 이메일입니다")

	def test_mail_failure_does_not_crash_signup(self):
		with override_settings(EMAIL_BACKEND="django.core.mail.backends.smtp.EmailBackend", EMAIL_HOST="127.0.0.1", EMAIL_PORT=1, EMAIL_TIMEOUT=1):
			resp = self._signup()
		self.assertRedirects(resp, f"{reverse('accounts:verify_sent')}?failed=1", fetch_redirect_response=False)

	def test_verify_sent_without_pending_user_redirects_to_login(self):
		self.assertRedirects(self.client.get(reverse("accounts:verify_sent")), reverse("accounts:login"))

	def test_mask_email(self):
		self.assertEqual(mask_email("newbie@example.com"), "ne****@example.com")
