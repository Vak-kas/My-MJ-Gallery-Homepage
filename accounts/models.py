from django.conf import settings
from django.db import models


class SignupRequest(models.Model):
    """회원가입 승인 요청. 승인 전에는 계정이 비활성(is_active=False)이라 로그인할 수 없음."""

    STATUS_PENDING = "pending"
    STATUS_APPROVED = "approved"
    STATUS_REJECTED = "rejected"
    STATUS_CHOICES = [
        (STATUS_PENDING, "승인 대기"),
        (STATUS_APPROVED, "승인됨"),
        (STATUS_REJECTED, "거절됨"),
    ]

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="signup_request")
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=STATUS_PENDING, db_index=True)
    message = models.CharField("가입 인사", max_length=300, blank=True)
    privacy_agreed_at = models.DateTimeField("개인정보 수집·이용 동의 시각", null=True, blank=True)
    # 가입한 곳 (봇 확인·차단용, 90일 지나면 비움)
    ip = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=300, blank=True)
    flags = models.CharField("의심 이유", max_length=200, blank=True)  # "무작위 이름 · 일회용 메일" 처럼
    created_at = models.DateTimeField(auto_now_add=True)
    decided_at = models.DateTimeField(null=True, blank=True)
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
    )
    # 이메일 인증: 메일이 켜져 있으면 가입 직후 링크를 보내고, 링크를 눌러야 승인 대기(회원 후보)가 됨
    email_verified_at = models.DateTimeField(null=True, blank=True)
    verify_token = models.CharField(max_length=64, blank=True, db_index=True)
    verify_sent_at = models.DateTimeField(null=True, blank=True)

    VERIFY_HOURS = 48          # 링크 유효 시간
    UNVERIFIED_KEEP_DAYS = 7   # 이 기간 안에 인증 안 하면 임시 계정 삭제

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.user} ({self.get_status_display()})"

    @property
    def flag_list(self):
        return [f for f in self.flags.split(" · ") if f]

    @property
    def needs_verification(self) -> bool:
        return self.status == self.STATUS_PENDING and bool(self.verify_token) and self.email_verified_at is None

    def issue_verify_token(self) -> str:
        import secrets
        from django.utils import timezone

        self.verify_token = secrets.token_urlsafe(32)
        self.verify_sent_at = timezone.now()
        self.save(update_fields=["verify_token", "verify_sent_at"])
        return self.verify_token

    def verify_link_valid(self, token: str) -> bool:
        from django.utils import timezone

        return bool(
            token and self.verify_token and secrets_equal(token, self.verify_token)
            and self.verify_sent_at and timezone.now() - self.verify_sent_at <= timezone.timedelta(hours=self.VERIFY_HOURS)
        )

    def mark_verified(self):
        from django.utils import timezone

        self.email_verified_at = timezone.now()
        self.verify_token = ""
        self.save(update_fields=["email_verified_at", "verify_token"])


def secrets_equal(a: str, b: str) -> bool:
    import hmac

    return hmac.compare_digest(a.encode(), b.encode())


def cleanup_unverified():
    """인증 메일을 받고도 기한 안에 누르지 않은 임시 계정 삭제 (하루 한 번)."""
    from django.utils import timezone

    limit = timezone.now() - timezone.timedelta(days=SignupRequest.UNVERIFIED_KEEP_DAYS)
    stale = SignupRequest.objects.filter(
        status=SignupRequest.STATUS_PENDING, email_verified_at__isnull=True, verify_sent_at__lt=limit,
    ).exclude(verify_token="")
    users = [sr.user for sr in stale.select_related("user")]
    n = len(users)
    for u in users:
        u.delete()
    return n


class MustChangePassword(models.Model):
    """관리자가 임시 비밀번호를 발급한 회원 — 다음 로그인 때 비밀번호를 바꿀 때까지 다른 화면을 못 씀."""

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="must_change_password")
    issued_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user} 임시 비밀번호 ({self.created_at:%Y-%m-%d})"


class TwoFactor(models.Model):
	"""2단계 인증(TOTP). 비밀번호 뒤에 인증 앱의 6자리 코드(또는 백업 코드)까지 맞아야 로그인."""

	METHOD_APP, METHOD_EMAIL = "app", "email"
	METHOD_CHOICES = [(METHOD_APP, "인증 앱 (TOTP)"), (METHOD_EMAIL, "메일 코드")]

	user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="two_factor")
	method = models.CharField(max_length=10, choices=METHOD_CHOICES, default=METHOD_APP)
	secret = models.CharField(max_length=64, blank=True)  # 인증 앱 방식만
	enabled = models.BooleanField(default=False, db_index=True)
	trust_version = models.PositiveIntegerField(default=0)  # "30일 기억" 쿠키 무효화용 (모든 기기에서 로그아웃하면 +1)
	confirmed_at = models.DateTimeField(null=True, blank=True)
	backup_codes = models.JSONField(default=list, blank=True)  # make_password 해시 목록, 쓰면 지움
	last_counter = models.BigIntegerField(default=0)  # 같은 코드 재사용 방지
	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)

	def __str__(self):
		return f"{self.user} 2단계 인증 {'켜짐' if self.enabled else '설정 중'}"

	def verify_code(self, code: str) -> bool:
		"""인증 앱 코드 → 맞으면 counter 갱신. 아니면 백업 코드 → 맞으면 그 코드 삭제."""
		from django.contrib.auth.hashers import check_password

		from . import totp

		counter = totp.verify(self.secret, code, min_counter=self.last_counter) if self.method == self.METHOD_APP and self.secret else None
		if counter is not None:
			self.last_counter = counter
			self.save(update_fields=["last_counter", "updated_at"])
			return True
		digits = "".join(ch for ch in (code or "") if ch.isdigit())
		if len(digits) == 8:
			for i, hashed in enumerate(self.backup_codes):
				if check_password(digits, hashed):
					self.backup_codes = self.backup_codes[:i] + self.backup_codes[i + 1:]
					self.save(update_fields=["backup_codes", "updated_at"])
					return True
		return False

	def issue_backup_codes(self):
		from django.contrib.auth.hashers import make_password

		from . import totp

		codes = totp.generate_backup_codes()
		self.backup_codes = [make_password(c) for c in codes]
		self.save(update_fields=["backup_codes", "updated_at"])
		return codes


def two_factor_enabled(user) -> bool:
	return bool(user and user.is_authenticated and TwoFactor.objects.filter(user=user, enabled=True).exists())


def logout_everywhere(user, keep_session_key=None) -> int:
	"""이 계정의 모든 로그인 세션을 끊음(지금 브라우저는 keep_session_key 로 남길 수 있음) + '30일 기억' 쿠키 무효화. 끊은 세션 수 반환."""
	from django.contrib.sessions.models import Session
	from django.utils import timezone

	n = 0
	for sess in Session.objects.filter(expire_date__gte=timezone.now()):
		if sess.session_key == keep_session_key:
			continue
		if sess.get_decoded().get("_auth_user_id") == str(user.id):
			sess.delete()
			n += 1
	TwoFactor.objects.filter(user=user).update(trust_version=models.F("trust_version") + 1)
	return n
