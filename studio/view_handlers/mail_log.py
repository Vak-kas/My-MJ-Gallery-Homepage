"""Studio › Mail: 사이트가 보낸 메일 기록 (가입 인증·비밀번호 재설정·아이디 찾기 등). 메일함 관리는 /mail/ 에서."""

from datetime import timedelta

from django.conf import settings
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.shortcuts import render
from django.utils import timezone

from webmail.models import SentMail

from .common import admin_view

RETENTION_DAYS = 180


@admin_view
def mail_log(request):
    now = timezone.now()
    SentMail.objects.filter(created_at__lt=now - timedelta(days=RETENTION_DAYS)).delete()

    kind = (request.GET.get("kind") or "").strip()
    q = (request.GET.get("q") or "").strip()
    only_failed = request.GET.get("failed") == "1"
    qs = SentMail.objects.all()
    if kind in dict(SentMail.KIND_CHOICES):
        qs = qs.filter(kind=kind)
    if q:
        qs = qs.filter(Q(to__icontains=q) | Q(subject__icontains=q))
    if only_failed:
        qs = qs.filter(ok=False)
    page_obj = Paginator(qs, 50).get_page(request.GET.get("page"))

    week = SentMail.objects.filter(created_at__gte=now - timedelta(days=7))
    by_kind = {row["kind"]: row["n"] for row in week.values("kind").annotate(n=Count("id"))}
    query = request.GET.copy()
    query.pop("page", None)
    return render(request, "studio/mail.html", {
        "page_obj": page_obj, "rows": list(page_obj.object_list),
        "filters": {"kind": kind, "q": q, "failed": only_failed},
        "kinds": SentMail.KIND_CHOICES,
        "stats": {
            "today": SentMail.objects.filter(created_at__date=timezone.localdate()).count(),
            "week": week.count(),
            "week_failed": week.filter(ok=False).count(),
            "by_kind": [(label, by_kind.get(key, 0)) for key, label in SentMail.KIND_CHOICES],
        },
        "mail_enabled": settings.MAIL_ENABLED, "webmail_enabled": settings.WEBMAIL_ENABLED,
        "email_host": settings.EMAIL_HOST or "(없음)", "from_email": settings.DEFAULT_FROM_EMAIL,
        "retention_days": RETENTION_DAYS, "current_query_string": query.urlencode(),
    })
