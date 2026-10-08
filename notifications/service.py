import logging
import threading
import urllib.request

from django.conf import settings
from django.db import connection

from .models import Notification

logger = logging.getLogger(__name__)


def notify(kind, title, body="", url=""):
    """사이트 알림을 남기고, 설정돼 있으면 휴대폰 푸시(ntfy)·카카오톡으로도 보냄."""
    item = Notification.objects.create(kind=kind, title=title[:200], body=body[:300], url=url[:300])
    if getattr(settings, "NTFY_TOPIC_URL", ""):
        _run_background(lambda: _push_ntfy(item))
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


def _push_ntfy(item):
    topic_url = getattr(settings, "NTFY_TOPIC_URL", "")
    if not topic_url:
        return
    site = getattr(settings, "SITE_URL", "").rstrip("/")
    headers = {"Title": item.title.encode("utf-8"), "Tags": item.kind}
    if site and item.url:
        headers["Click"] = f"{site}{item.url}"
    token = getattr(settings, "NTFY_TOKEN", "")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = (item.body or item.title).encode("utf-8")

    req = urllib.request.Request(topic_url, data=data, headers=headers, method="POST")
    urllib.request.urlopen(req, timeout=5).close()
