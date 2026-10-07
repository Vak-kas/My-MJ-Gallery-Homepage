import hmac
from urllib.parse import urlencode

from django.conf import settings
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from . import relay_client
from .permissions import can_manage_streams
from .registry import TOOLS


def index(request):
	tools = [
		{**tool, "url": reverse(tool["url_name"])}
		for tool in TOOLS
		if not tool.get("admin_only") or can_manage_streams(request.user)
	]
	return render(request, "tools/index.html", {"tools": tools})


def duplex(request):
	return render(request, "tools/duplex.html")


def subnet(request):
	return render(request, "tools/subnet.html")


def speedtest(request):
	return render(request, "tools/speedtest.html")


# ── 실시간 데이터 스트림 ─────────────────────────────

MB = 1024 * 1024
GB = 1024 * MB


def _require_stream_admin(request):
	"""권한이 없으면 응답(로그인 이동/403)을, 있으면 None 을 돌려줌."""
	if not request.user.is_authenticated:
		return redirect(f"{reverse('accounts:login')}?{urlencode({'next': request.get_full_path()})}")
	if not can_manage_streams(request.user):
		raise PermissionDenied("스트림 방은 관리자만 만들 수 있습니다.")
	return None


def _float_or_none(value):
	try:
		return float(value) if str(value).strip() else None
	except (TypeError, ValueError):
		return None


def _room_payload(post):
	kind = post.get("kind", "iq")
	meta = {}
	if kind == "iq":
		meta["format"] = post.get("format", "fc32")
		for key in ("sample_rate", "center_freq"):
			value = _float_or_none(post.get(key))
			if value is not None:
				meta[key] = value
	elif kind == "file":
		meta["filename"] = (post.get("filename") or "").strip()[:200]
	label = (post.get("label") or "").strip()[:80]
	if label:
		meta["label"] = label
	allow_ips = [ip for ip in (post.get("allow_ips") or "").replace(",", "\n").splitlines() if ip.strip()]
	payload = {"kind": kind, "meta": meta, "allow_ips": allow_ips}
	for field, scale, key in (("ttl_minutes", 60, "ttl"), ("rate_mb", MB, "rate_limit"), ("total_gb", GB, "total_limit")):
		value = _float_or_none(post.get(field))
		if value is not None:
			payload[key] = int(value * scale)
	return payload


def stream_list(request):
	denied = _require_stream_admin(request)
	if denied:
		return denied
	if request.method == "POST":
		try:
			room = relay_client.create_room(_room_payload(request.POST))
		except relay_client.RelayError as exc:
			messages.error(request, str(exc))
			return redirect("tools:stream")
		return redirect(f"{reverse('tools:stream_room', args=[room['id']])}?token={room['token']}")

	error_message = None
	try:
		rooms = relay_client.list_rooms()
	except relay_client.RelayError as exc:
		rooms, error_message = [], str(exc)
	return render(request, "tools/stream_list.html", {
		"rooms": rooms,
		"relay_error": error_message,
		"public_host": settings.RELAY_PUBLIC_HOST,
	})


def stream_room(request, room_id):
	"""방 화면. 방 토큰이 있는 링크면 누구나(받는 사람) 볼 수 있고, 닫기는 관리자만."""
	try:
		room = relay_client.get_room(room_id)
	except relay_client.RelayError as exc:
		return render(request, "tools/stream_room.html", {"relay_error": str(exc)}, status=503)
	token = request.GET.get("token", "")
	if room is None or not hmac.compare_digest(token, room.get("token", "")):
		raise Http404("방이 없거나 링크가 올바르지 않습니다.")

	ws_base = settings.RELAY_WS_URL or f"{'wss' if request.is_secure() else 'ws'}://{request.get_host()}"
	room_view = {k: v for k, v in room.items() if k != "token"}
	return render(request, "tools/stream_room.html", {
		"room": room_view,
		"room_json": room_view,
		"share_url": request.build_absolute_uri(),
		"ws_url": f"{ws_base.rstrip('/')}/relay/ws/{room_id}?token={token}",
		"public_host": settings.RELAY_PUBLIC_HOST,
		"can_manage": can_manage_streams(request.user),
		"token": token,
	})


@require_POST
def stream_close(request, room_id):
	denied = _require_stream_admin(request)
	if denied:
		return denied
	try:
		relay_client.close_room(room_id)
		messages.success(request, "방을 닫았습니다.")
	except relay_client.RelayError as exc:
		messages.error(request, str(exc))
	return redirect("tools:stream")
