"""화면 송출(라이브 방송) 시그널링 — mj-relay 데몬 안에서 함께 돈다.

영상·소리는 WebRTC 로 방송하는 브라우저 → 시청자 브라우저로 직접(또는 TURN 서버를 거쳐) 간다.
이 모듈은 연결 정보(SDP/ICE)를 서로 전달하고, 시청자 목록·채팅만 다룬다.

방 하나 = 방송하는 사람(host) 1명 + 시청자 여러 명.
  - host 링크(token)와 시청 링크(viewer_token)가 따로 있음
  - host 가 시청자마다 WebRTC 연결을 하나씩 만든다 (offer 는 항상 host 가 보냄 → 충돌 없음)

제어 API (127.0.0.1 + X-Relay-Key, Django 가 호출)
  POST   /live            방 만들기 {title, owner_id, owner, ttl, max_viewers, chat}
  GET    /live            목록
  GET    /live/{id}       상세
  DELETE /live/{id}       닫기
WebSocket
  /relay/ws/live/{id}?token=<host 또는 viewer 토큰>&name=<닉네임>
"""

import asyncio
import hmac
import json
import logging
import secrets
import time
from dataclasses import dataclass, field

from aiohttp import WSMsgType, web

log = logging.getLogger("mj-relay.live")

MAX_ROOMS = 5
DEFAULT_TTL = 60 * 60
MAX_TTL = 6 * 60 * 60
DEFAULT_MAX_VIEWERS = 10
HARD_MAX_VIEWERS = 20
MAX_SIGNAL_BYTES = 64 * 1024
CHAT_MAX_CHARS = 300
CHAT_HISTORY = 50
CHAT_MIN_INTERVAL = 0.7  # 한 사람이 채팅을 보낼 수 있는 최소 간격 (초)


def _clamp(value, default, low, high):
	try:
		value = int(value)
	except (TypeError, ValueError):
		return default
	return max(low, min(high, value))


def _clean_name(raw, fallback):
	name = " ".join(str(raw or "").split())[:20]
	return name or fallback


@dataclass
class Peer:
	peer_id: str
	ws: web.WebSocketResponse
	name: str
	role: str  # host / viewer
	last_chat: float = 0.0


@dataclass
class LiveRoom:
	room_id: str
	token: str
	viewer_token: str
	title: str
	owner_id: int | None
	owner: str
	max_viewers: int
	chat_enabled: bool
	created_at: float
	expires_at: float
	host: Peer | None = None
	viewers: dict = field(default_factory=dict)
	chat: list = field(default_factory=list)
	peak_viewers: int = 0
	host_seen: bool = False

	def role_of(self, token):
		if token and hmac.compare_digest(token, self.token):
			return "host"
		if token and hmac.compare_digest(token, self.viewer_token):
			return "viewer"
		return None

	def public(self, with_tokens=True):
		data = {
			"id": self.room_id,
			"kind": "live",
			"title": self.title,
			"owner_id": self.owner_id,
			"owner": self.owner,
			"max_viewers": self.max_viewers,
			"chat": self.chat_enabled,
			"created_at": self.created_at,
			"expires_at": self.expires_at,
			"expires_in": max(0, int(self.expires_at - time.time())),
			"host_online": self.host is not None,
			"viewers": len(self.viewers),
			"peak_viewers": self.peak_viewers,
		}
		if with_tokens:
			data["token"] = self.token
			data["viewer_token"] = self.viewer_token
		return data


class LiveError(Exception):
	def __init__(self, message, status=400):
		super().__init__(message)
		self.status = status


class LiveHub:
	def __init__(self, max_rooms=MAX_ROOMS):
		self.rooms: dict[str, LiveRoom] = {}
		self.max_rooms = max_rooms
		self._reaper = None

	async def start(self):
		self._reaper = asyncio.create_task(self._reap_loop())

	async def stop(self):
		if self._reaper:
			self._reaper.cancel()
		for room_id in list(self.rooms):
			await self.close_room(room_id, "서버가 다시 시작돼 방송이 종료됐어요.")

	async def _reap_loop(self):
		while True:
			await asyncio.sleep(5)
			now = time.time()
			for room in list(self.rooms.values()):
				if room.expires_at <= now:
					await self.close_room(room.room_id, "방송 시간이 끝났어요.")

	def create_room(self, payload):
		if len(self.rooms) >= self.max_rooms:
			raise LiveError(f"동시에 열 수 있는 방송은 최대 {self.max_rooms}개예요. 잠시 뒤 다시 시도해 주세요.", status=409)
		now = time.time()
		room_id = secrets.token_hex(4)
		while room_id in self.rooms:
			room_id = secrets.token_hex(4)
		room = LiveRoom(
			room_id=room_id,
			token=secrets.token_urlsafe(24),
			viewer_token=secrets.token_urlsafe(16),
			title=str(payload.get("title") or "").strip()[:80] or "화면 송출",
			owner_id=payload.get("owner_id"),
			owner=str(payload.get("owner") or "")[:40],
			max_viewers=_clamp(payload.get("max_viewers"), DEFAULT_MAX_VIEWERS, 1, HARD_MAX_VIEWERS),
			chat_enabled=bool(payload.get("chat", True)),
			created_at=now,
			expires_at=now + _clamp(payload.get("ttl"), DEFAULT_TTL, 60, MAX_TTL),
		)
		self.rooms[room_id] = room
		log.info("라이브 방 생성 %s (%s)", room_id, room.owner)
		return room

	async def close_room(self, room_id, reason="방송이 종료됐어요."):
		room = self.rooms.pop(room_id, None)
		if room is None:
			return False
		peers = list(room.viewers.values()) + ([room.host] if room.host else [])
		for peer in peers:
			try:
				await peer.ws.send_json({"type": "end", "reason": reason})
				await peer.ws.close()
			except (ConnectionResetError, RuntimeError):
				pass
		log.info("라이브 방 종료 %s: %s", room_id, reason)
		return True

	# ── 메시지 전달 ─────────────────────────────

	async def _send(self, peer, data):
		if peer is None or peer.ws.closed:
			return
		try:
			await peer.ws.send_json(data)
		except (ConnectionResetError, RuntimeError):
			pass

	async def _broadcast(self, room, data, include_host=True):
		targets = list(room.viewers.values()) + ([room.host] if include_host and room.host else [])
		await asyncio.gather(*(self._send(p, data) for p in targets))

	async def _push_count(self, room):
		await self._broadcast(room, {"type": "count", "viewers": len(room.viewers), "host_online": room.host is not None})

	def _viewer_list(self, room):
		return [{"id": p.peer_id, "name": p.name} for p in room.viewers.values()]

	async def handle(self, request):
		room = self.rooms.get(request.match_info["room_id"])
		role = room.role_of(request.query.get("token", "")) if room else None
		if room is None or role is None:
			return web.Response(status=404, text="no such room")
		if role == "viewer" and len(room.viewers) >= room.max_viewers:
			return web.Response(status=429, text="room full")

		ws = web.WebSocketResponse(heartbeat=20, max_msg_size=MAX_SIGNAL_BYTES)
		await ws.prepare(request)
		peer_id = "host" if role == "host" else secrets.token_hex(4)
		fallback = (room.owner or "방송자") if role == "host" else f"시청자{secrets.randbelow(900) + 100}"
		peer = Peer(peer_id=peer_id, ws=ws, name=_clean_name(request.query.get("name"), fallback), role=role)

		if role == "host":
			old = room.host
			room.host = peer
			room.host_seen = True
			if old is not None:  # 새 창에서 다시 열면 예전 연결은 닫음
				await self._send(old, {"type": "end", "reason": "다른 창에서 방송 화면을 열었어요."})
				await old.ws.close()
			await ws.send_json({"type": "hello", "role": "host", "id": peer_id, "room": room.public(with_tokens=False),
								"viewers": self._viewer_list(room), "chat": room.chat})
			await self._broadcast(room, {"type": "host", "online": True}, include_host=False)
		else:
			room.viewers[peer_id] = peer
			room.peak_viewers = max(room.peak_viewers, len(room.viewers))
			await ws.send_json({"type": "hello", "role": "viewer", "id": peer_id, "name": peer.name,
								"room": room.public(with_tokens=False), "chat": room.chat})
			await self._send(room.host, {"type": "viewer-join", "id": peer_id, "name": peer.name})
		await self._push_count(room)

		try:
			async for msg in ws:
				if msg.type == WSMsgType.ERROR:
					break
				if msg.type != WSMsgType.TEXT:
					continue
				try:
					data = json.loads(msg.data)
				except ValueError:
					continue
				await self._on_message(room, peer, data)
		finally:
			if role == "host":
				if room.host is peer:
					room.host = None
					await self._broadcast(room, {"type": "host", "online": False}, include_host=False)
			else:
				room.viewers.pop(peer_id, None)
				await self._send(room.host, {"type": "viewer-leave", "id": peer_id})
			if room.room_id in self.rooms:
				await self._push_count(room)
		return ws

	async def _on_message(self, room, peer, data):
		kind = data.get("type")
		if kind == "signal":
			# host → 특정 시청자 / 시청자 → host 로만 전달
			if peer.role == "host":
				target = room.viewers.get(str(data.get("to")))
				await self._send(target, {"type": "signal", "from": "host", "data": data.get("data")})
			else:
				await self._send(room.host, {"type": "signal", "from": peer.peer_id, "data": data.get("data")})
		elif kind == "meta" and peer.role == "host":
			# 어떤 스트림이 화면/웹캠/마이크인지 시청자에게 알려줌
			await self._broadcast(room, {"type": "meta", "data": data.get("data")}, include_host=False)
		elif kind == "chat" and room.chat_enabled:
			now = time.time()
			text = " ".join(str(data.get("text") or "").split())[:CHAT_MAX_CHARS]
			if not text or now - peer.last_chat < CHAT_MIN_INTERVAL:
				return
			peer.last_chat = now
			item = {"type": "chat", "name": peer.name, "host": peer.role == "host", "text": text, "at": int(now)}
			room.chat = (room.chat + [item])[-CHAT_HISTORY:]
			await self._broadcast(room, item)
		elif kind == "kick" and peer.role == "host":
			target = room.viewers.get(str(data.get("id")))
			if target:
				await self._send(target, {"type": "end", "reason": "방송자가 내보냈어요."})
				await target.ws.close()
		elif kind == "end" and peer.role == "host":
			await self.close_room(room.room_id, "방송자가 방송을 끝냈어요.")


def add_live_routes(app, hub: LiveHub):
	async def create(request):
		try:
			payload = await request.json()
		except json.JSONDecodeError:
			payload = {}
		try:
			room = hub.create_room(payload)
		except LiveError as exc:
			return web.json_response({"error": str(exc)}, status=exc.status)
		return web.json_response(room.public(), status=201)

	async def listing(request):
		return web.json_response({"rooms": [r.public() for r in hub.rooms.values()]})

	async def detail(request):
		room = hub.rooms.get(request.match_info["room_id"])
		if room is None:
			return web.json_response({"error": "방이 없습니다."}, status=404)
		return web.json_response(room.public())

	async def delete(request):
		ok = await hub.close_room(request.match_info["room_id"], "방송이 종료됐어요.")
		return web.json_response({"closed": ok}, status=200 if ok else 404)

	app.router.add_post("/live", create)
	app.router.add_get("/live", listing)
	app.router.add_get("/live/{room_id}", detail)
	app.router.add_delete("/live/{room_id}", delete)
	app.router.add_get("/relay/ws/live/{room_id}", hub.handle)
