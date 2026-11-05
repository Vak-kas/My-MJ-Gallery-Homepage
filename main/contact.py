"""관리자 문의 (오른쪽 아래 💬): 비관리자·비로그인 누구나. 관리자 메일로 보내고 사이트 알림(+카톡)도 남김.
나중에 챗봇을 붙일 자리 — 지금은 '메일로 전달' 한 가지 방식."""

import json
import re

from django.conf import settings
from django.core.cache import cache
from django.core.mail import EmailMessage
from django.http import JsonResponse
from django.views.decorators.http import require_POST

from notifications.models import Notification
from notifications.service import notify
from security.utils import client_ip
from main.jsonbody import loads_object

_EMAIL_RE = re.compile(r"^[^@\s<>]+@[^@\s<>]+\.[^@\s<>]+$")
LIMIT_PER_HOUR = 3


@require_POST
def contact_submit(request):
	try:
		payload = loads_object(request.body)
	except ValueError:
		return JsonResponse({"ok": False, "error": "요청이 이상해요"}, status=400)
	if str(payload.get("website") or "").strip():  # 봇용 함정 칸
		return JsonResponse({"ok": True})
	message = str(payload.get("message") or "").strip()
	if len(message) < 5:
		return JsonResponse({"ok": False, "error": "내용을 조금 더 적어 주세요 (5자 이상)"}, status=400)
	if len(message) > 3000:
		return JsonResponse({"ok": False, "error": "내용은 3000자까지예요"}, status=400)
	name = (payload.get("name") or "").strip()[:60]
	email = str(payload.get("email") or "").strip()[:254]
	if email and not _EMAIL_RE.match(email):
		return JsonResponse({"ok": False, "error": "답장 받을 메일 주소가 이상해요"}, status=400)
	user = request.user if request.user.is_authenticated else None
	if user:
		name = name or user.first_name or user.username
		email = email or user.email
	ip = client_ip(request)
	key = f"contact:{ip}"
	if (cache.get(key) or 0) >= LIMIT_PER_HOUR:
		return JsonResponse({"ok": False, "error": "문의는 한 시간에 3번까지예요. 잠시 뒤 다시 보내 주세요"}, status=429)
	cache.set(key, (cache.get(key) or 0) + 1, 3600)

	who = f"{name or '익명'}{' <' + email + '>' if email else ''}{' · @' + user.username if user else ' · 비로그인'}"
	body = f"{message}\n\n--\n보낸 사람: {who}\nIP: {ip}\n페이지: {str(payload.get('page') or '')[:200]}"
	mail = EmailMessage(f"[MJ Gallery 문의] {message[:40]}{'…' if len(message) > 40 else ''}", body, settings.DEFAULT_FROM_EMAIL, [settings.CONTACT_EMAIL],
	                    reply_to=[email] if email else None, headers={"X-MJ-Kind": "contact"})
	try:
		mail.send(fail_silently=False)
	except Exception:  # noqa: BLE001 — 메일이 안 가도 알림은 남김
		pass
	notify(Notification.KIND_GUESTBOOK, f"💬 문의: {name or '익명'}", message[:300], "")
	return JsonResponse({"ok": True})
