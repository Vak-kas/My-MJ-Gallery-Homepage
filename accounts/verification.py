"""회원가입 이메일 인증.

가입하면 계정을 비활성(is_active=False)으로 만들고, 이메일로 보낸 링크를 눌러야 활성화된다.
링크 토큰은 Django 기본 토큰 생성기(비밀번호 재설정과 같은 방식)를 써서
PASSWORD_RESET_TIMEOUT(기본 3일, settings 에서 24시간으로 설정) 동안만 유효하다.
"""

import logging

from django.conf import settings
from django.contrib.auth.tokens import default_token_generator
from django.core.cache import cache
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

logger = logging.getLogger(__name__)

RESEND_COOLDOWN_SECONDS = 60


def mask_email(email):
	"""ab***@gmail.com 처럼 일부만 보여줌."""
	local, _, domain = (email or "").partition("@")
	if not domain:
		return email
	visible = local[:2] if len(local) > 2 else local[:1]
	return f"{visible}{'*' * max(3, len(local) - len(visible))}@{domain}"


def verification_url(request, user):
	uid = urlsafe_base64_encode(force_bytes(user.pk))
	token = default_token_generator.make_token(user)
	return request.build_absolute_uri(reverse("accounts:verify_email", args=[uid, token]))


def send_verification_email(request, user):
	"""인증 메일 발송. 실패해도 예외를 올리지 않고 False 를 돌려줌."""
	context = {
		"user": user,
		"verify_url": verification_url(request, user),
		"site_name": "MJ Gallery",
		"valid_hours": settings.PASSWORD_RESET_TIMEOUT // 3600,
	}
	try:
		send_mail(
			subject="[MJ Gallery] 이메일 인증을 완료해 주세요",
			message=render_to_string("accounts/email/verify_email.txt", context),
			from_email=settings.DEFAULT_FROM_EMAIL,
			recipient_list=[user.email],
			html_message=render_to_string("accounts/email/verify_email.html", context),
		)
		return True
	except Exception:  # noqa: BLE001 - 메일 서버 오류로 가입 자체가 500 이 되지 않도록
		logger.exception("인증 메일 발송 실패 (user_id=%s)", user.pk)
		return False


def can_resend(user):
	"""같은 계정에 1분에 한 번만 재발송."""
	key = f"accounts:verify-resend:{user.pk}"
	if cache.get(key):
		return False
	cache.set(key, True, RESEND_COOLDOWN_SECONDS)
	return True
