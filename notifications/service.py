import logging
import threading

from django.conf import settings
from django.db import connection

from .models import AlertMail, Notification

logger = logging.getLogger(__name__)


def notify(kind, title, body="", url=""):
    """사이트 알림을 남기고, 카카오톡이 연결돼 있으면 카카오톡으로도 보냄."""
    item = Notification.objects.create(kind=kind, title=title[:200], body=body[:300], url=url[:300])
    if getattr(settings, "KAKAO_REST_API_KEY", ""):
        _run_background(lambda: _push_kakao(item))
    pref = AlertMail.objects.first()
    if pref and pref.wants(kind) and getattr(settings, "MAIL_ENABLED", False):
        _run_background(lambda: _push_mail(item, pref))
    return item


def _run_background(fn):
    # 요청 응답을 늦추지 않도록 백그라운드로 보냄
    def run():
        try:
            fn()
        except Exception:  # 푸시 실패는 사이트 동작에 영향 주지 않음
            logger.warning("알림 푸시 실패", exc_info=True)
        finally:
            if threading.current_thread() is not threading.main_thread():
                connection.close()  # 백그라운드 스레드가 연 DB 연결 정리

    threading.Thread(target=run, daemon=True).start()


def _push_kakao(item):
    from . import kakao

    text = f"{item.icon} {item.title}"
    if item.body:
        text += f"\n\n{item.body}"
    kakao.send_text(text, item.url)


def _push_mail(item, pref):
    """알림을 메일로. 제목에 종류 아이콘, 본문에 내용과 바로가기 링크."""
    from django.core.mail import EmailMessage
    from django.utils import timezone

    link = item.url if not item.url or item.url.startswith("http") else f"{settings.SITE_URL}{item.url}"
    body = f"{item.title}\n\n{item.body}".strip()
    if link:
        body += f"\n\n바로가기: {link}"
    body += f"\n\n— MJ Gallery 알림 ({item.get_kind_display()}) · 설정: {settings.SITE_URL}/notifications/"
    msg = EmailMessage(f"[MJ 알림] {item.icon} {item.title}", body, settings.DEFAULT_FROM_EMAIL, [pref.email], headers={"X-MJ-Kind": "alert"})
    try:
        msg.send(fail_silently=False)
        AlertMail.objects.filter(id=pref.id).update(last_sent_at=timezone.now(), last_error="")
    except Exception as exc:  # noqa: BLE001
        AlertMail.objects.filter(id=pref.id).update(last_error=str(exc)[:300])
        raise
