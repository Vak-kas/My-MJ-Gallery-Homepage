"""카카오톡 '나에게 보내기'로 관리자 알림 전송.

필요한 설정(.env): KAKAO_REST_API_KEY, KAKAO_CLIENT_SECRET(클라이언트 시크릿을 켠 경우)
카카오 개발자 콘솔: 카카오 로그인 ON, 리다이렉트 URI <SITE_URL>/notifications/kakao/callback/,
동의항목 talk_message(카카오톡 메시지 전송) 선택 동의
"""
import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from .models import KakaoLink

logger = logging.getLogger(__name__)

AUTH_URL = "https://kauth.kakao.com/oauth/authorize"
TOKEN_URL = "https://kauth.kakao.com/oauth/token"
MEMO_URL = "https://kapi.kakao.com/v2/api/talk/memo/default/send"


class KakaoError(Exception):
    pass


def is_configured():
    return bool(getattr(settings, "KAKAO_REST_API_KEY", ""))


def authorize_url(redirect_uri, state):
    return AUTH_URL + "?" + urllib.parse.urlencode({
        "client_id": settings.KAKAO_REST_API_KEY,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "talk_message",
        "state": state,
    })


def _post(url, data, token=None):
    headers = {"Content-Type": "application/x-www-form-urlencoded;charset=utf-8"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=urllib.parse.urlencode(data).encode(), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=8) as res:
            return json.loads(res.read().decode() or "{}")
    except urllib.error.HTTPError as exc:
        try:
            body = json.loads(exc.read().decode() or "{}")
        except ValueError:
            body = {}
        raise KakaoError(body.get("error_description") or body.get("msg") or f"HTTP {exc.code}") from exc


def _token_request(data):
    data = {"client_id": settings.KAKAO_REST_API_KEY, **data}
    secret = getattr(settings, "KAKAO_CLIENT_SECRET", "")
    if secret:
        data["client_secret"] = secret
    return _post(TOKEN_URL, data)


def _apply_tokens(link, tok):
    now = timezone.now()
    link.access_token = tok["access_token"]
    link.expires_at = now + timedelta(seconds=int(tok.get("expires_in", 21599)))
    if tok.get("refresh_token"):  # 만료 1개월 이내일 때만 새로 내려옴
        link.refresh_token = tok["refresh_token"]
        link.refresh_expires_at = now + timedelta(seconds=int(tok.get("refresh_token_expires_in", 5184000)))


def connect(code, redirect_uri, user):
    tok = _token_request({"grant_type": "authorization_code", "redirect_uri": redirect_uri, "code": code})
    if "talk_message" not in (tok.get("scope") or "talk_message"):
        raise KakaoError("'카카오톡 메시지 전송' 동의가 필요합니다.")
    KakaoLink.objects.all().delete()
    link = KakaoLink(connected_by=user)
    _apply_tokens(link, tok)
    link.save()
    return link


def _fresh_token(link, force=False):
    if not force and link.expires_at > timezone.now() + timedelta(minutes=5):
        return link.access_token
    tok = _token_request({"grant_type": "refresh_token", "refresh_token": link.refresh_token})
    _apply_tokens(link, tok)
    link.save(update_fields=["access_token", "refresh_token", "expires_at", "refresh_expires_at"])
    return link.access_token


def send_text(text, url=""):
    """연결돼 있으면 나와의 채팅으로 보냄. 보냈으면 True."""
    link = KakaoLink.objects.first()
    if not link or not is_configured():
        return False
    site = getattr(settings, "SITE_URL", "").rstrip("/")
    full_url = f"{site}{url}" if url.startswith("/") else (url or site)
    template = {
        "object_type": "text",
        "text": text[:200],
        "link": {"web_url": full_url, "mobile_web_url": full_url},
        "button_title": "열기",
    }
    data = {"template_object": json.dumps(template, ensure_ascii=False)}
    try:
        try:
            _post(MEMO_URL, data, token=_fresh_token(link))
        except KakaoError:
            _post(MEMO_URL, data, token=_fresh_token(link, force=True))  # 토큰 문제면 한 번 갱신 후 재시도
    except KakaoError as exc:
        link.last_error = str(exc)[:300]
        link.save(update_fields=["last_error"])
        logger.warning("카카오톡 알림 실패: %s", exc)
        return False
    link.last_sent_at = timezone.now()
    link.last_error = ""
    link.save(update_fields=["last_sent_at", "last_error"])
    return True
