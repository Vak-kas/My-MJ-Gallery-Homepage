import ipaddress

from django.conf import settings
from django.db import models
from django.utils import timezone


class LoginEvent(models.Model):
    """로그인 시도 기록 (성공·실패·잠금). 90일 보관."""

    RESULT_SUCCESS = "success"
    RESULT_FAILED = "failed"
    RESULT_LOCKED = "locked"
    RESULT_BLOCKED = "blocked"
    RESULT_CHOICES = [
        (RESULT_SUCCESS, "성공"),
        (RESULT_FAILED, "실패"),
        (RESULT_LOCKED, "잠김(반복 실패)"),
        (RESULT_BLOCKED, "차단된 IP"),
    ]

    username = models.CharField(max_length=150, blank=True, db_index=True)  # 시도한 아이디
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    ip = models.GenericIPAddressField(null=True, blank=True, db_index=True)
    user_agent = models.CharField(max_length=300, blank=True)
    result = models.CharField(max_length=10, choices=RESULT_CHOICES, db_index=True)
    is_admin = models.BooleanField(default=False)
    new_location = models.BooleanField(default=False)  # 이 계정이 처음 쓰는 IP 로 성공
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"{self.username}@{self.ip} {self.result}"


class IPBlock(models.Model):
    """접속 차단할 IP 또는 대역(CIDR)."""

    network = models.CharField(max_length=64)  # 1.2.3.4 또는 1.2.3.0/24
    reason = models.CharField(max_length=200, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    hit_count = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return self.network

    @property
    def is_active(self):
        return not self.expires_at or self.expires_at > timezone.now()

    def as_network(self):
        return ipaddress.ip_network(self.network, strict=False)
