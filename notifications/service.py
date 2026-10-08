import logging
import threading
import urllib.request

from django.conf import settings

from .models import Notification

logger = logging.getLogger(__name__)


def notify(kind, title, body="", url=""):
    """사이트 알림을 남기고, 설정돼 있으면 휴대폰 푸시(ntfy)도 보냄."""
    item = Notification.objects.create(kind=kind, title=title[:200], body=body[:300], url=url[:300])
    _push_ntfy(item)
    return item


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

    def send():
        try:
            req = urllib.request.Request(topic_url, data=data, headers=headers, method="POST")
            urllib.request.urlopen(req, timeout=5).close()
        except Exception:  # 푸시 실패는 사이트 동작에 영향 주지 않음
            logger.warning("ntfy 푸시 실패", exc_info=True)

    # 요청 응답을 늦추지 않도록 백그라운드로 보냄
    threading.Thread(target=send, daemon=True).start()
