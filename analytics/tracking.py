"""방문 기록 (middleware).

기록하는 것: 날짜, 경로, 유입 경로 분류, 리퍼러 도메인, 기기 종류, 회원 여부, 그날만 유효한 방문자 해시
기록하지 않는 것: IP, 브라우저 전체 문자열, 쿠키, 관리자 본인 방문, 봇·링크 미리보기
"""

import hashlib
import re
from urllib.parse import urlparse

from django.conf import settings
from django.utils import timezone

from security.utils import client_ip

BOT_RE = re.compile(
    r"bot|crawl|spider|slurp|preview|scrap|facebookexternalhit|embedly|whatsapp|daumoa|yeti|"
    r"headless|python-requests|curl|wget|go-http|uptime|monitor|lighthouse",
    re.I,
)
SKIP_PREFIXES = ("/studio/", "/admin/", "/notifications/", "/static/", "/media/", "/relay/", "/accounts/",
                 "/tools/speedtest/", "/tools/netcheck/run", "/tools/clipboard/api", "/tools/myip/lookup",
                 "/tools/qrcode/ai-style", "/blog/api/", "/blog/feed/", "/sitemap.xml", "/robots.txt", "/favicon",
                 "/sw.js", "/manifest.webmanifest", "/offline/")
SEARCH_HOSTS = ("google.", "naver.", "daum.net", "bing.", "duckduckgo.", "yahoo.", "zum.com", "ecosia.")
SOCIAL_HOSTS = ("facebook.", "instagram.", "t.co", "twitter.", "x.com", "discord", "slack", "linkedin.", "reddit.",
                "threads.", "youtube.", "telegram", "band.us", "everytime.")


def classify(referer, user_agent, own_host):
    ua = user_agent or ""
    host = (urlparse(referer).hostname or "").lower() if referer else ""
    if host.startswith("www."):
        host = host[4:]
    if host and (host == own_host or host.endswith("." + own_host)):
        return "internal", ""
    if "KAKAOTALK" in ua.upper() or "kakao" in host:
        return "kakao", host
    if not host:
        if "Instagram" in ua or "FBAN" in ua or "FB_IAB" in ua:
            return "social", ""
        return "direct", ""
    if "github" in host:
        return "github", host
    if any(s in host for s in SEARCH_HOSTS):
        return "search", host
    if any(s in host for s in SOCIAL_HOSTS):
        return "social", host
    return "other", host[:120]


def device_of(user_agent):
    ua = user_agent or ""
    if re.search(r"iPad|Tablet|(Android(?!.*Mobile))", ua):
        return "tablet"
    if re.search(r"Mobi|iPhone|Android", ua):
        return "mobile"
    return "desktop"


def section_of(path):
    if path == "/":
        return "home"
    if path.startswith("/blog/post/"):
        return "post"
    if path.startswith("/blog/"):
        return "blog"
    if path.startswith("/tools/"):
        return "tool"
    if path.startswith("/photos/"):
        return "gallery"
    if path.startswith("/s/"):
        return "short"
    return "other"


class PageViewMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        try:
            self._record(request, response)
        except Exception:  # 통계 기록 실패가 페이지를 막으면 안 됨
            pass
        return response

    def _record(self, request, response):
        if request.method != "GET" or response.status_code not in (200, 302):
            return
        path = request.path
        if path.startswith(SKIP_PREFIXES):
            return
        is_short = path.startswith("/s/")
        if not is_short and "text/html" not in response.get("Content-Type", ""):
            return
        ua = request.META.get("HTTP_USER_AGENT", "")
        if not ua or BOT_RE.search(ua):
            return
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated and user.is_superuser:
            return  # 관리자 본인 방문은 빼고 셈
        from .models import PageView

        today = timezone.localdate()
        own_host = (urlparse(settings.SITE_URL).hostname or request.get_host().split(":")[0]).lower()
        source, ref_host = classify(request.META.get("HTTP_REFERER", ""), ua, own_host)
        utm = (request.GET.get("utm_source") or "").lower()
        if utm and source in ("direct", "other"):
            source = "kakao" if "kakao" in utm else "github" if "github" in utm else "social"
        raw = f"{today.isoformat()}|{client_ip(request) or ''}|{ua}|{settings.SECRET_KEY}"
        PageView.objects.create(
            day=today,
            path=path[:300],
            section=section_of(path),
            visitor=hashlib.sha256(raw.encode()).hexdigest()[:16],
            source=source,
            referrer_host=ref_host,
            device=device_of(ua),
            is_member=bool(user and user.is_authenticated),
        )
