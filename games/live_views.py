"""실시간 대전 게임 (오목 등) — 방은 mj-relay 데몬(relay/mj_game.py)이 들고 있음.

방 만들기는 로그인 회원, 링크를 받은 사람은 로그인 없이 닉네임만으로 참여.
"""

import hmac

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from main import og_cards, seo
from tools import relay_client

MAX_ROOMS_PER_USER = 3
KINDS = {"omok": {"title": "오목", "icon": "⚫"}}


def _ws_base(request):
	return settings.RELAY_WS_URL or f"{'wss' if request.is_secure() or request.META.get('HTTP_X_FORWARDED_PROTO') == 'https' else 'ws'}://{request.get_host()}"


def _link(request, room):
	path = reverse("games:omok_room", args=[room["id"]]) + f"?t={room['token']}"
	if request.get_host().split(":")[0] in {"127.0.0.1", "localhost"}:
		return request.build_absolute_uri(path)
	return settings.SITE_URL.rstrip("/") + path


def omok_lobby(request):
	relay_error = None
	try:
		rooms = [r for r in relay_client.list_games() if r.get("kind") == "omok"]
	except relay_client.RelayError as exc:
		rooms, relay_error = [], str(exc)
	user = request.user
	mine = [r for r in rooms if user.is_authenticated and r.get("owner_id") == user.id]
	open_rooms = [r for r in rooms if r.get("public") and r not in mine]
	for r in mine + open_rooms:
		r["url"] = reverse("games:omok_room", args=[r["id"]]) + f"?t={r['token']}"
	return render(request, "games/omok.html", {"mine": mine, "open_rooms": open_rooms, "relay_error": relay_error, "max_rooms": MAX_ROOMS_PER_USER})


@login_required
@require_POST
def omok_create(request):
	try:
		mine = [r for r in relay_client.list_games() if r.get("owner_id") == request.user.id]
		if len(mine) >= MAX_ROOMS_PER_USER and not request.user.is_superuser:
			messages.error(request, f"방은 {MAX_ROOMS_PER_USER}개까지 열 수 있어요. 안 쓰는 방을 닫아 주세요.")
			return redirect("games:omok")
		room = relay_client.create_game({
			"kind": "omok",
			"title": request.POST.get("title", ""),
			"owner_id": request.user.id,
			"owner": request.user.username,
			"public": request.POST.get("public") == "on",
		})
	except relay_client.RelayError as exc:
		messages.error(request, str(exc))
		return redirect("games:omok")
	return redirect(reverse("games:omok_room", args=[room["id"]]) + f"?t={room['token']}")


def omok_room(request, room_id):
	try:
		room = relay_client.get_game(room_id)
	except relay_client.RelayError as exc:
		return render(request, "games/omok_room.html", {"relay_error": str(exc)}, status=503)
	token = request.GET.get("t", "")
	if not room or room.get("kind") != "omok" or not token or not hmac.compare_digest(token, room["token"]):
		raise Http404("방이 없거나 닫혔어요.")
	user = request.user
	return render(request, "games/omok_room.html", {
		"room": {k: v for k, v in room.items() if k != "token"},
		"ws_url": f"{_ws_base(request).rstrip('/')}/relay/ws/game/{room_id}?token={token}",
		"share_url": _link(request, room),
		"default_name": user.username if user.is_authenticated else "",
		"is_owner": user.is_authenticated and (room.get("owner_id") == user.id or user.is_superuser),
		"meta": seo.build(f"⚫ {room.get('title') or '오목'} · 오목 한 판", f"{room.get('owner') or '누군가'} 님이 오목 한 판 하자고 해요. 링크를 열고 닉네임만 넣으면 바로 같이 둘 수 있어요.",
						  og_cards.image_url("game", "omok"), path=request.path, noindex=True),  # 초대 링크는 검색에 안 나오게
	})


@login_required
@require_POST
def omok_close(request, room_id):
	try:
		room = relay_client.get_game(room_id)
		if room and (room.get("owner_id") == request.user.id or request.user.is_superuser):
			relay_client.close_game(room_id)
			messages.success(request, "방을 닫았어요.")
	except relay_client.RelayError as exc:
		messages.error(request, str(exc))
	return redirect("games:omok")
