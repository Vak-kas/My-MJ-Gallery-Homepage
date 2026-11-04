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
