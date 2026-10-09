from django.db import models


class Notification(models.Model):
    """관리자(슈퍼유저)에게 보여주는 사이트 알림. 관리자 모두가 같은 목록을 봄."""

    KIND_SIGNUP = "signup"
    KIND_COMMENT = "comment"
    KIND_GUESTBOOK = "guestbook"
    KIND_POST = "post"
    KIND_SECURITY = "security"
    KIND_MONITOR = "monitor"
    KIND_CHOICES = [
        (KIND_SIGNUP, "가입 요청"),
        (KIND_COMMENT, "댓글"),
        (KIND_GUESTBOOK, "방명록"),
        (KIND_POST, "글"),
        (KIND_SECURITY, "보안"),
        (KIND_MONITOR, "서버 감시"),
    ]
    ICONS = {KIND_SIGNUP: "🙋", KIND_COMMENT: "💬", KIND_GUESTBOOK: "📝", KIND_POST: "📄", KIND_SECURITY: "🛡", KIND_MONITOR: "🛰"}

    kind = models.CharField(max_length=20, choices=KIND_CHOICES, db_index=True)
    title = models.CharField(max_length=200)
    body = models.CharField(max_length=300, blank=True)
    url = models.CharField(max_length=300, blank=True)
    is_read = models.BooleanField(default=False, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"[{self.kind}] {self.title}"

    @property
    def icon(self):
        return self.ICONS.get(self.kind, "🔔")


class KakaoLink(models.Model):
    """관리자 카카오톡 '나에게 보내기' 연결 (한 개만 사용)."""

    access_token = models.CharField(max_length=300)
    refresh_token = models.CharField(max_length=300)
    expires_at = models.DateTimeField()
    refresh_expires_at = models.DateTimeField(null=True, blank=True)
    connected_by = models.ForeignKey(
        "auth.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
    )
    connected_at = models.DateTimeField(auto_now_add=True)
    last_sent_at = models.DateTimeField(null=True, blank=True)
    last_error = models.CharField(max_length=300, blank=True)

    def __str__(self):
        return f"KakaoLink({self.connected_by})"
