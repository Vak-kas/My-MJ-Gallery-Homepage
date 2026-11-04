from django.conf import settings
from django.db import models


class PageView(models.Model):
    """페이지 조회 한 번. IP 는 저장하지 않고, 날짜별로 바뀌는 해시(visitor)로 그날의 순방문자만 셈. 90일 보관."""

    SOURCE_CHOICES = [
        ("direct", "직접 방문"),
        ("search", "검색"),
        ("kakao", "카카오톡"),
        ("github", "GitHub"),
        ("social", "SNS·메신저"),
        ("internal", "사이트 안 이동"),
        ("other", "다른 사이트"),
    ]
    DEVICE_CHOICES = [("desktop", "PC"), ("mobile", "모바일"), ("tablet", "태블릿")]

    day = models.DateField(db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    path = models.CharField(max_length=300, db_index=True)
    section = models.CharField(max_length=20, db_index=True)  # home / blog / post / tool / gallery / other
    visitor = models.CharField(max_length=16, db_index=True)
    source = models.CharField(max_length=10, choices=SOURCE_CHOICES, db_index=True)
    referrer_host = models.CharField(max_length=120, blank=True)
    device = models.CharField(max_length=10, choices=DEVICE_CHOICES)
    is_member = models.BooleanField(default=False)
    # 회원이면 누구인지 (실시간 현황·회원 상세용). 비회원은 비어 있고 visitor 해시만 남음
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="page_views")

    class Meta:
        indexes = [models.Index(fields=["day", "section"])]

    def __str__(self):
        return f"{self.day} {self.path}"
