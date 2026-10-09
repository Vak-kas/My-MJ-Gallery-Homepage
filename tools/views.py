import hmac
from urllib.parse import urlencode

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import ensure_csrf_cookie
from django.core.exceptions import PermissionDenied
from django.http import Http404, JsonResponse
from django.shortcuts import redirect, render
from django.core.cache import cache
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from . import relay_client
from .permissions import can_create_streams, can_manage_streams, owns_room, stream_limits
from .registry import CATEGORIES, TOOLS
from .speedtest import _client_ip


def index(request):
	user = request.user
	tools = [{**t, "url": reverse(t["url_name"])} for t in TOOLS]
	sections = []
	for key, icon, title, note in CATEGORIES:
		items = [t for t in tools if t.get("category") == key and t.get("access", "public") != "admin"]
		if items:  # 도구가 없는 칸은 숨김
			sections.append({"key": key, "icon": icon, "title": title, "note": note, "tools": items})
	admin_tools = [t for t in tools if t.get("access") == "admin"]
	if admin_tools and user.is_superuser:
		sections.append({"key": "admin", "icon": "🛡", "title": "관리자 전용", "note": "사이트 관리자만 보이는 도구", "tools": admin_tools})
	return render(request, "tools/index.html", {
		"sections": sections,
		"tool_count": sum(len(s["tools"]) for s in sections),
		"has_member_tools": any(t.get("access") == "member" for s in sections for t in s["tools"]),
	})


def duplex(request):
	return render(request, "tools/duplex.html")


def units_tool(request):
	return render(request, "tools/units.html")


def time_tool(request):
	return render(request, "tools/time.html")


def linkbudget(request):
	return render(request, "tools/linkbudget.html")


def subnet(request):
	return render(request, "tools/subnet.html")


@login_required  # 서버 트래픽을 실제로 쓰는 도구라 회원만
def speedtest(request):
	return render(request, "tools/speedtest.html")


def keygen(request):
	return render(request, "tools/keygen.html")


def encode(request):
	return render(request, "tools/encode.html")


def charcount(request):
	return render(request, "tools/charcount.html")


def textdiff(request):
	return render(request, "tools/textdiff.html")


def gpa(request):
	return render(request, "tools/gpa.html")


@ensure_csrf_cookie  # 내 논문함 담기(POST)
def papers_page(request):
	return render(request, "tools/papers.html")


def cite_page(request):
	return render(request, "tools/cite.html")


def image_tool(request):
	return render(request, "tools/image.html")


@ensure_csrf_cookie  # 비로그인도 무료 읽기 요청을 보낼 수 있게
def ocr(request):  # 무료 읽기는 누구나, ✨AI 읽기는 회원
	return render(request, "tools/ocr.html")


def pdf_tool(request):
	return render(request, "tools/pdf.html")


def json_tool(request):
	return render(request, "tools/json.html")


def regex(request):
	return render(request, "tools/regex.html")


def qrcode(request):
	return render(request, "tools/qrcode.html", {"ai_enabled": bool(settings.ANTHROPIC_API_KEY)})


# ── 실시간 데이터 스트림 ─────────────────────────────

MB = 1024 * 1024
GB = 1024 * MB


def _require_stream_member(request):
	"""권한이 없으면 응답(로그인 이동/403)을, 있으면 None 을 돌려줌."""
	if not request.user.is_authenticated:
		return redirect(f"{reverse('accounts:login')}?{urlencode({'next': request.get_full_path()})}")
	if not can_create_streams(request.user):
		raise PermissionDenied("데이터 전송 방은 회원만 만들 수 있습니다.")
	return None


def _daily_room_key(user):
	return f"stream:rooms:{user.id}:{timezone.localdate().isoformat()}"


def _apply_member_limits(payload, lim):
	"""회원이 만드는 방은 유효 시간·속도·총량을 한도 안으로 줄임 (VIP 회원은 더 넉넉한 한도)."""
	caps = {"ttl": lim["ttl_minutes"] * 60, "rate_limit": int(lim["rate_mb"] * MB), "total_limit": int(lim["total_gb"] * GB)}
	for key, cap in caps.items():
		payload[key] = min(payload.get(key, cap), cap)
	return payload


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
	denied = _require_stream_member(request)
	if denied:
		return denied
	user = request.user
	is_admin = can_manage_streams(user)
	lim = stream_limits(user)

	if request.method == "POST":
		payload = _room_payload(request.POST)
		payload["meta"]["owner_id"] = user.id
		payload["meta"]["owner"] = user.username
		try:
			if not is_admin:
				mine = [r for r in relay_client.list_rooms() if owns_room(user, r)]
				if len(mine) >= lim["max_open_rooms"]:
					messages.error(request, f"방은 동시에 {lim['max_open_rooms']}개까지 열 수 있어요. 쓰던 방을 닫고 다시 만들어 주세요.")
					return redirect("tools:stream")
				if cache.get(_daily_room_key(user), 0) >= lim["rooms_per_day"]:
					messages.error(request, f"방은 하루에 {lim['rooms_per_day']}개까지 만들 수 있어요. 내일 다시 시도해 주세요.")
					return redirect("tools:stream")
				_apply_member_limits(payload, lim)
			room = relay_client.create_room(payload)
		except relay_client.RelayError as exc:
			messages.error(request, str(exc))
			return redirect("tools:stream")
		if not is_admin:
			key = _daily_room_key(user)
			cache.set(key, cache.get(key, 0) + 1, 24 * 60 * 60)
		return redirect(f"{reverse('tools:stream_room', args=[room['id']])}?token={room['token']}")

	error_message = None
	try:
		rooms = relay_client.list_rooms()
	except relay_client.RelayError as exc:
		rooms, error_message = [], str(exc)
	if not is_admin:
		rooms = [r for r in rooms if owns_room(user, r)]  # 회원은 자기 방만
	return render(request, "tools/stream_list.html", {
		"rooms": rooms,
		"relay_error": error_message,
		"public_host": settings.RELAY_PUBLIC_HOST,
		"is_admin": is_admin,
		"limits": None if is_admin else lim,
	})


TOKEN_KEYS = ("token", "sender_token", "receiver_token")


def _token_role(room, token):
	for role, key in (("admin", "token"), ("sender", "sender_token"), ("receiver", "receiver_token")):
		if token and hmac.compare_digest(token, room.get(key, "")):
			return role
	return None


def _load_room(room_id, token):
	room = relay_client.get_room(room_id)
	role = _token_role(room, token) if room else None
	if role is None:
		raise Http404("방이 없거나 링크가 올바르지 않습니다.")
	return room, role


def stream_room(request, room_id):
	"""방 화면. 링크 토큰으로 역할을 정함.

	- 관리자 링크: 보내는 쪽·받는 쪽 링크를 나눠 줄 수 있고 방을 닫을 수 있음
	- 보내는 쪽 / 받는 쪽 링크: 연 순간 이 네트워크의 공인 IP 가 그 역할로 등록됨 → 그 IP 에서만 포트 접속 가능
	"""
	token = request.GET.get("token", "")
	try:
		room, role = _load_room(room_id, token)
		my_ip = _client_ip(request)
		if role in ("sender", "receiver"):
			room = relay_client.join_room(room_id, role, token, my_ip) or room
	except relay_client.RelayError as exc:
		return render(request, "tools/stream_room.html", {"relay_error": str(exc)}, status=503)

	ws_base = settings.RELAY_WS_URL or f"{'wss' if request.is_secure() else 'ws'}://{request.get_host()}"
	base_url = request.build_absolute_uri(reverse("tools:stream_room", args=[room_id]))
	room_view = {k: v for k, v in room.items() if k not in TOKEN_KEYS}
	context = {
		"room": room_view,
		"room_json": room_view,
		"role": role,
		"my_ip": my_ip,
		"ws_url": f"{ws_base.rstrip('/')}/relay/ws/{room_id}?token={token}",
		"ws_send_url": f"{ws_base.rstrip('/')}/relay/ws/{room_id}/send?token={token}",
		"ws_recv_url": f"{ws_base.rstrip('/')}/relay/ws/{room_id}/recv?token={token}",
		"join_url": f"{reverse('tools:stream_join', args=[room_id])}?token={token}",
		"public_host": settings.RELAY_PUBLIC_HOST,
		"can_manage": role == "admin" and (can_manage_streams(request.user) or owns_room(request.user, room)),
		"can_share": can_manage_streams(request.user),
	}
	if role == "admin":
		context["sender_link"] = f"{base_url}?token={room['sender_token']}"
		context["receiver_link"] = f"{base_url}?token={room['receiver_token']}"
	return render(request, "tools/stream_room.html", context)


@require_POST
def stream_join(request, room_id):
	"""링크 페이지가 열려 있는 동안 주기적으로 호출: IP 가 바뀌어도 다시 등록."""
	token = request.GET.get("token", "")
	role = request.GET.get("role", "")
	try:
		room, token_role = _load_room(room_id, token)
		if token_role == "admin" and role in ("sender", "receiver"):
			pass  # 관리자는 "이 컴퓨터를 보내는/받는 쪽으로 등록" 가능
		elif token_role in ("sender", "receiver"):
			role = token_role
		else:
			return JsonResponse({"error": "역할을 정할 수 없습니다."}, status=400)
		ip = _client_ip(request)
		relay_client.join_room(room_id, role, token, ip)
	except relay_client.RelayError as exc:
		return JsonResponse({"error": str(exc)}, status=503)
	return JsonResponse({"role": role, "ip": ip})


@require_POST
def stream_close(request, room_id):
	denied = _require_stream_member(request)
	if denied:
		return denied
	try:
		room = relay_client.get_room(room_id)
		if not room:
			raise Http404
		if not (can_manage_streams(request.user) or owns_room(request.user, room)):
			raise PermissionDenied("내가 만든 방만 닫을 수 있습니다.")
		relay_client.close_room(room_id)
		messages.success(request, "방을 닫았습니다.")
	except relay_client.RelayError as exc:
		messages.error(request, str(exc))
	return redirect("tools:stream")
