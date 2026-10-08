import ipaddress
import time

from django.core.cache import cache
from django.utils import timezone

BLOCKS_CACHE_KEY = "security:blocks"
LOCK_WINDOW = 15 * 60
IP_FAIL_LIMIT = 10        # 같은 IP 에서 15분에 실패 10번 → 15분 잠금
USERNAME_FAIL_LIMIT = 5   # 같은 아이디로 15분에 실패 5번 → 15분 잠금
RETENTION_DAYS = 90


def client_ip(request):
    # nginx 가 X-Real-IP 를 덮어써서 넘겨줌 (gunicorn 은 유닉스 소켓이라 REMOTE_ADDR 이 비어 있음)
    raw = (request.META.get("HTTP_X_REAL_IP") or request.META.get("REMOTE_ADDR") or "").strip()
    try:
        return str(ipaddress.ip_address(raw))
    except ValueError:
        return None


def user_agent(request):
    return (request.META.get("HTTP_USER_AGENT") or "")[:300]


# ── IP 차단 ─────────────────────────────

def active_blocks():
    """[(pk, network)] — 캐시해 두고 차단 목록이 바뀌면 지움."""
    blocks = cache.get(BLOCKS_CACHE_KEY)
    if blocks is None:
        from .models import IPBlock
        blocks = []
        for b in IPBlock.objects.all():
            if b.is_active:
                try:
                    blocks.append((b.pk, b.as_network()))
                except ValueError:
                    continue
        cache.set(BLOCKS_CACHE_KEY, blocks, 60)
    return blocks


def clear_block_cache():
    cache.delete(BLOCKS_CACHE_KEY)


def matching_block(ip):
    if not ip:
        return None
    addr = ipaddress.ip_address(ip)
    for pk, net in active_blocks():
        if addr.version == net.version and addr in net:
            return pk
    return None


# ── 로그인 반복 실패 잠금 ─────────────────────────────

def _bucket(key):
    now = time.time()
    data = cache.get(key)
    if not data or now - data["start"] >= LOCK_WINDOW:
        data = {"start": now, "count": 0}
    return data


def is_locked(ip, username):
    ip_data = _bucket(f"security:fail:ip:{ip}") if ip else {"count": 0}
    user_data = _bucket(f"security:fail:user:{(username or '').lower()}") if username else {"count": 0}
    return ip_data["count"] >= IP_FAIL_LIMIT or user_data["count"] >= USERNAME_FAIL_LIMIT


def record_failure(ip, username):
    for key in ([f"security:fail:ip:{ip}"] if ip else []) + ([f"security:fail:user:{username.lower()}"] if username else []):
        data = _bucket(key)
        data["count"] += 1
        cache.set(key, data, max(1, int(data["start"] + LOCK_WINDOW - time.time())))


def clear_failures(ip, username):
    if ip:
        cache.delete(f"security:fail:ip:{ip}")
    if username:
        cache.delete(f"security:fail:user:{username.lower()}")


# ── 보관 기간 정리 ─────────────────────────────

def cleanup_old_records():
    """90일 지난 로그인 기록 삭제, 글·댓글·방명록의 작성자 IP·브라우저 정보 비우기."""
    from blog.models import Comment, GuestbookEntry, Post

    from .models import IPBlock, LoginEvent

    cutoff = timezone.now() - timezone.timedelta(days=RETENTION_DAYS)
    deleted = LoginEvent.objects.filter(created_at__lt=cutoff).delete()[0]
    cleared = 0
    for model in (Comment, GuestbookEntry, Post):
        cleared += model.objects.filter(created_at__lt=cutoff).exclude(author_ip=None).update(author_ip=None, author_agent="")
    expired = IPBlock.objects.filter(expires_at__lt=timezone.now() - timezone.timedelta(days=7)).delete()[0]
    if expired:
        clear_block_cache()
    return {"login_events": deleted, "content_ip_cleared": cleared, "expired_blocks": expired}
