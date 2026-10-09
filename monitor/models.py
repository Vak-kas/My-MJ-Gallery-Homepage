from django.conf import settings
from django.db import models


class TrafficSnapshot(models.Model):
    """네트워크 누적 송수신 바이트 (1시간마다). 재부팅하면 카운터가 0부터 다시 시작하므로 boot_id 로 구분."""

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    boot_id = models.CharField(max_length=64)
    rx_bytes = models.BigIntegerField()
    tx_bytes = models.BigIntegerField()

    class Meta:
        ordering = ["created_at"]


class UptimeTarget(models.Model):
    KIND_HTTP = "http"
    KIND_TCP = "tcp"
    KIND_CHOICES = [(KIND_HTTP, "웹 주소 (HTTP)"), (KIND_TCP, "포트 (TCP)")]
    STATUS_CHOICES = [("unknown", "확인 전"), ("up", "정상"), ("down", "장애")]
    INTERVALS = [1, 5, 10, 30]

    name = models.CharField(max_length=60)
    kind = models.CharField(max_length=10, choices=KIND_CHOICES, default=KIND_HTTP)
    target = models.CharField(max_length=300)  # https://… 또는 host:port
    interval_min = models.PositiveSmallIntegerField(default=5)
    enabled = models.BooleanField(default=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="unknown")
    last_checked_at = models.DateTimeField(null=True, blank=True)
    last_change_at = models.DateTimeField(null=True, blank=True)
    last_latency_ms = models.PositiveIntegerField(null=True, blank=True)
    last_error = models.CharField(max_length=200, blank=True)
    fail_streak = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["name", "id"]

    def __str__(self):
        return f"{self.name} ({self.target})"


class UptimeCheck(models.Model):
    target = models.ForeignKey(UptimeTarget, on_delete=models.CASCADE, related_name="checks")
    checked_at = models.DateTimeField(auto_now_add=True, db_index=True)
    ok = models.BooleanField()
    latency_ms = models.PositiveIntegerField(null=True, blank=True)
    status_code = models.PositiveSmallIntegerField(null=True, blank=True)
    error = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["-checked_at"]
