"""라이브 방송 — 방송 만들기는 회원(한도 있음), 시청은 링크만 있으면 누구나.

영상은 WebRTC 로 브라우저끼리 직접 가고, 직접 연결이 안 되면 서버의 TURN(coturn)을 거친다.
연결 정보 교환·채팅은 mj-relay 데몬의 /relay/ws/live/<id> (relay/mj_live.py).
"""

import base64
import hashlib
import hmac
import time
from urllib.parse import urlencode

from django.conf import settings
from django.contrib import messages
from django.core.cache import cache
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from main import og_cards, seo

from . import relay_client
from .permissions import ADMIN_LIVE_LIMITS, MEMBER_LIVE_LIMITS, can_create_streams, can_manage_streams


def ice_servers(room_id, ttl_seconds):
	"""브라우저에 줄 ICE 서버 목록. TURN 은 coturn 의 use-auth-secret(REST API) 방식 임시 계정."""
	host = settings.TURN_HOST
	servers = [{"urls": [f"stun:{host}:{settings.TURN_PORT}", "stun:stun.l.google.com:19302"]}]
	if settings.TURN_SECRET:
		username = f"{int(time.time()) + int(ttl_seconds) + 600}:{room_id}"
		digest = hmac.new(settings.TURN_SECRET.encode(), username.encode(), hashlib.sha1).digest()
		servers.append({
			"urls": [f"turn:{host}:{settings.TURN_PORT}?transport=udp", f"turn:{host}:{settings.TURN_PORT}?transport=tcp"],
			"username": username,
			"credential": base64.b64encode(digest).decode(),
		})
	return servers


def _require_member(request):
	if not request.user.is_authenticated:
		return redirect(f"{reverse('accounts:login')}?{urlencode({'next': request.get_full_path()})}")
	if not can_create_streams(request.user):
		raise Http404
	return None


def _daily_key(user):
	return f"live:rooms:{user.id}:{timezone.localdate().isoformat()}"


def live_list(request):
	denied = _require_member(request)
	if denied:
		return denied
	user = request.user
	is_admin = can_manage_streams(user)
	limits = ADMIN_LIVE_LIMITS if is_admin else MEMBER_LIVE_LIMITS

	if request.method == "POST":
		try:
			ttl_min = min(max(int(request.POST.get("ttl_minutes") or 60), 5), limits["ttl_minutes"])
			max_viewers = min(max(int(request.POST.get("max_viewers") or limits["max_viewers"]), 1), limits["max_viewers"])
		except ValueError:
			messages.error(request, "숫자를 확인해 주세요.")
			return redirect("tools:live")
		try:
			if not is_admin:
				mine = [r for r in relay_client.list_live() if r.get("owner_id") == user.id]
				if len(mine) >= MEMBER_LIVE_LIMITS["max_open_rooms"]:
					messages.error(request, "방송은 동시에 1개만 열 수 있어요. 쓰던 방송을 끝내고 다시 만들어 주세요.")
					return redirect("tools:live")
				if cache.get(_daily_key(user), 0) >= MEMBER_LIVE_LIMITS["rooms_per_day"]:
					messages.error(request, f"방송은 하루에 {MEMBER_LIVE_LIMITS['rooms_per_day']}번까지 열 수 있어요.")
					return redirect("tools:live")
			room = relay_client.create_live({
				"title": (request.POST.get("title") or "").strip()[:80],
				"owner_id": user.id,
				"owner": user.first_name or user.username,
				"ttl": ttl_min * 60,
				"max_viewers": max_viewers,
				"chat": request.POST.get("chat") == "on",
			})
		except relay_client.RelayError as exc:
			messages.error(request, str(exc))
			return redirect("tools:live")
		if not is_admin:
			key = _daily_key(user)
			cache.set(key, cache.get(key, 0) + 1, 24 * 60 * 60)
		return redirect(f"{reverse('tools:live_room', args=[room['id']])}?token={room['token']}")

	relay_error = None
	try:
		rooms = relay_client.list_live()
	except relay_client.RelayError as exc:
		rooms, relay_error = [], str(exc)
	if not is_admin:
		rooms = [r for r in rooms if r.get("owner_id") == user.id]
	return render(request, "tools/live_list.html", {
		"rooms": rooms, "relay_error": relay_error, "is_admin": is_admin, "limits": limits,
		"member_limits": MEMBER_LIVE_LIMITS, "turn_enabled": bool(settings.TURN_SECRET),
	})


def live_room(request, room_id):
	"""host 링크면 방송 화면, 시청 링크면 시청 화면 (시청은 로그인 불필요)."""
	token = request.GET.get("token", "")
	try:
		room = relay_client.get_live(room_id)
	except relay_client.RelayError as exc:
		return render(request, "tools/live_room.html", {"relay_error": str(exc)}, status=503)
	if not room:
		return render(request, "tools/link_gone.html", {"what": "방송"}, status=404)
	if token and hmac.compare_digest(token, room["token"]):
		role = "host"
	elif token and hmac.compare_digest(token, room["viewer_token"]):
		role = "viewer"
	else:
		return render(request, "tools/link_gone.html", {"what": "방송"}, status=404)

	ws_base = settings.RELAY_WS_URL or f"{'wss' if request.is_secure() or request.META.get('HTTP_X_FORWARDED_PROTO') == 'https' else 'ws'}://{request.get_host()}"
	public = {k: v for k, v in room.items() if k not in ("token", "viewer_token")}
	context = {
		"meta": seo.build(f"📺 {room.get('title') or '라이브 방송'}", f"{room.get('owner') or '서민재 갤러리'} 님의 라이브 방송 — 링크를 열면 로그인 없이 바로 볼 수 있어요.", og_cards.image_url("tool", "live"), path=request.path),
		"room": public,
		"role": role,
		"ws_url": f"{ws_base.rstrip('/')}/relay/ws/live/{room_id}?token={token}",
		"ice_servers": ice_servers(room_id, room.get("expires_in", 3600)),
		"turn_enabled": bool(settings.TURN_SECRET),
		"default_name": (request.user.first_name or request.user.username) if request.user.is_authenticated else "",
	}
	if role == "host":
		base = request.build_absolute_uri(reverse("tools:live_room", args=[room_id]))
		if request.get_host().split(":")[0] not in {"127.0.0.1", "localhost"}:
			base = settings.SITE_URL.rstrip("/") + reverse("tools:live_room", args=[room_id])
		context["viewer_link"] = f"{base}?token={room['viewer_token']}"
	return render(request, "tools/live_room.html", context)


@require_POST
def live_close(request, room_id):
	denied = _require_member(request)
	if denied:
		return denied
	try:
		room = relay_client.get_live(room_id)
		if not room:
			raise Http404
		if not (can_manage_streams(request.user) or room.get("owner_id") == request.user.id):
			raise Http404
		relay_client.close_live(room_id)
		messages.success(request, "방송을 끝냈어요.")
	except relay_client.RelayError as exc:
		messages.error(request, str(exc))
	return redirect("tools:live")
