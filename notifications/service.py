import logging
import threading

from django.conf import settings
from django.db import connection

from .models import Notification

logger = logging.getLogger(__name__)


def notify(kind, title, body="", url=""):
    """사이트 알림을 남기고, 카카오톡이 연결돼 있으면 카카오톡으로도 보냄."""
    item = Notification.objects.create(kind=kind, title=title[:200], body=body[:300], url=url[:300])
    if getattr(settings, "KAKAO_REST_API_KEY", ""):
        _run_background(lambda: _push_kakao(item))
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
