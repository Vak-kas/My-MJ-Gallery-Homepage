"""실시간 게임 방 — mj-relay 데몬 안에서 함께 돈다.

방 하나 = 링크(token)를 가진 사람들. 처음 앉은 사람이 플레이어, 나머지는 구경꾼.
판은 서버가 들고 규칙도 서버가 판단한다 (차례·빈 칸·승패) → 브라우저는 보여 주기만.
게임 종류마다 규칙 클래스(OmokLogic 등)를 두고, 방·연결·채팅·다시 접속은 공통.

제어 API (127.0.0.1 + X-Relay-Key, Django 가 호출)
  POST   /games            방 만들기 {kind, title, owner_id, owner, public}
  GET    /games            목록
  GET    /games/{id}       상세
  DELETE /games/{id}       닫기
WebSocket
  /relay/ws/game/{id}?token=<방 토큰>&pid=<브라우저가 만든 내 열쇠>&name=<닉네임>
  pid 가 같으면 잠깐 끊겼다 다시 들어와도 자리를 그대로 돌려받음
"""

import asyncio
import hmac
import json
import logging
import secrets
import time
from dataclasses import dataclass, field

from aiohttp import WSMsgType, web

log = logging.getLogger("mj-relay.game")

MAX_ROOMS = 30
ROOM_TTL = 6 * 60 * 60        # 방 최대 수명
IDLE_CLOSE = 30 * 60          # 아무도 없이 이만큼 지나면 닫음
SEAT_GRACE = 90               # 끊긴 플레이어 자리를 이만큼 기다려 줌
MAX_PEERS = 30
MAX_MSG = 16 * 1024
CHAT_MAX_CHARS = 200
CHAT_HISTORY = 40
CHAT_MIN_INTERVAL = 0.6


def _clean_name(raw, fallback):
	name = " ".join(str(raw or "").split())[:16]
	return name or fallback


@dataclass
class Peer:
	pid: str
	ws: web.WebSocketResponse
	name: str
	last_chat: float = 0.0


# ── 오목 ──────────────────────────────────

class OmokLogic:
	"""15×15, 흑 먼저, 다섯 개 이상 이으면 승리(자유룰). 판 b[y*15+x] = '.', 'b', 'w'."""

	kind = "omok"
	SIZE = 15
	SEATS = ("black", "white")

	def __init__(self):
		self.seats = {"black": None, "white": None}  # pid
		self.names = {"black": "", "white": ""}
		self.reset()
		self.wins = {"black": 0, "white": 0}

	def reset(self):
		self.board = ["."] * (self.SIZE * self.SIZE)
		self.moves = []  # [(x, y, color)]
		self.turn = "black"
		self.status = "waiting"  # waiting / playing / over
		self.winner = None
		self.win_line = []
		self.reason = ""
		self.undo_from = None

	def seat_of(self, pid):
		return next((s for s, p in self.seats.items() if p == pid), None)

	def _start_if_ready(self):
		if self.status == "waiting" and all(self.seats.values()):
			self.status = "playing"

	def _five(self, x, y, c):
		for dx, dy in ((1, 0), (0, 1), (1, 1), (1, -1)):
			line = [(x, y)]
			for sign in (1, -1):
				nx, ny = x + dx * sign, y + dy * sign
				while 0 <= nx < self.SIZE and 0 <= ny < self.SIZE and self.board[ny * self.SIZE + nx] == c:
					line.append((nx, ny))
					nx, ny = nx + dx * sign, ny + dy * sign
			if len(line) >= 5:
				return sorted(line)
		return None

	def on_message(self, room, peer, data):
		"""처리 결과로 (방 전체에 상태를 다시 보낼지, 이 사람에게만 보낼 오류) 를 돌려줌."""
		kind = data.get("type")
		seat = self.seat_of(peer.pid)
		if kind == "sit":
			want = data.get("seat")
			if seat:
				return False, "이미 앉아 있어요."
			free = [s for s in self.SEATS if not self.seats[s]]
			if want in self.SEATS and want in free:
				target = want
			elif want in (None, "any") and free:
				target = free[0]
			else:
				return False, "그 자리는 이미 찼어요."
			self.seats[target] = peer.pid
			self.names[target] = peer.name
			self._start_if_ready()
			room.notice(f"{peer.name} 님이 {'흑' if target == 'black' else '백'}으로 앉았어요.")
			return True, None
		if kind == "stand":
			if not seat:
				return False, None
			if self.status == "playing" and self.moves:
				return False, "대국 중에는 일어날 수 없어요. 기권하거나 끝난 뒤에 일어나세요."
			self.seats[seat] = None
			self.names[seat] = ""
			if self.status == "playing":
				self.status = "waiting"
			room.notice(f"{peer.name} 님이 자리에서 일어났어요.")
			return True, None
		if kind == "move":
			if self.status != "playing":
				return False, "아직 대국이 시작되지 않았어요."
			if seat != self.turn:
				return False, "내 차례가 아니에요." if seat else "구경 중이에요."
			try:
				x, y = int(data.get("x")), int(data.get("y"))
			except (TypeError, ValueError):
				return False, None
			if not (0 <= x < self.SIZE and 0 <= y < self.SIZE) or self.board[y * self.SIZE + x] != ".":
				return False, "거기에는 둘 수 없어요."
			c = seat[0]
			self.board[y * self.SIZE + x] = c
			self.moves.append((x, y, c))
			self.undo_from = None
			line = self._five(x, y, c)
			if line:
				self._finish(seat, f"{self.names[seat]} 님이 오목을 완성했어요!", line)
			elif "." not in self.board:
				self._finish(None, "판이 가득 찼어요. 무승부!")
			else:
				self.turn = "white" if seat == "black" else "black"
			return True, None
		if kind == "resign":
			if self.status != "playing" or not seat:
				return False, None
			other = "white" if seat == "black" else "black"
			self._finish(other, f"{self.names[seat]} 님이 기권했어요.")
			return True, None
		if kind == "undo-req":
			# 방금 내가 둔 수를 물러 달라고 요청 → 상대가 받아 줘야 함
			if self.status != "playing" or not seat or not self.moves or self.moves[-1][2] != seat[0]:
				return False, "방금 내가 둔 수만 무를 수 있어요."
			self.undo_from = seat
			room.notice(f"{peer.name} 님이 한 수 무르기를 부탁했어요.")
			return True, None
		if kind in ("undo-ok", "undo-no"):
			if not self.undo_from or not seat or seat == self.undo_from:
				return False, None
			if kind == "undo-ok":
				x, y, c = self.moves.pop()
				self.board[y * self.SIZE + x] = "."
				self.turn = self.undo_from
				room.notice("한 수 물렀어요.")
			else:
				room.notice("무르기를 거절했어요.")
			self.undo_from = None
			return True, None
		if kind == "rematch":
			if self.status != "over" or not seat:
				return False, None
			# 흑·백을 바꿔서 새 판
			self.seats = {"black": self.seats["white"], "white": self.seats["black"]}
			self.names = {"black": self.names["white"], "white": self.names["black"]}
			self.wins = {"black": self.wins["white"], "white": self.wins["black"]}
			self.reset()
			self._start_if_ready()
			room.notice("흑·백을 바꿔서 새 판을 시작해요.")
			return True, None
		return False, None

	def _finish(self, winner, reason, line=None):
		self.status = "over"
		self.winner = winner
		self.reason = reason
		self.win_line = line or []
		if winner:
			self.wins[winner] += 1

	def on_leave(self, pid):
		"""플레이어가 너무 오래 안 돌아오면 자리를 비움. 대국 중이면 상대 승."""
		seat = self.seat_of(pid)
		if not seat:
			return None
		name = self.names[seat]
		if self.status == "playing" and self.moves:
			other = "white" if seat == "black" else "black"
			self._finish(other, f"{name} 님이 나가서 대국이 끝났어요.")
		elif self.status == "playing":
			self.status = "waiting"
		self.seats[seat] = None
		self.names[seat] = ""
		return f"{name} 님의 자리가 비었어요."

	def snapshot(self, room):
		return {
			"board": "".join(self.board),
			"size": self.SIZE,
			"turn": self.turn,
			"status": self.status,
			"winner": self.winner,
			"win_line": self.win_line,
			"reason": self.reason,
			"last": list(self.moves[-1][:2]) if self.moves else None,
			"move_count": len(self.moves),
			"undo_from": self.undo_from,
			"wins": self.wins,
			"seats": {s: {"name": self.names[s], "online": bool(p and p in room.peers)} if p else None for s, p in self.seats.items()},
		}


LOGICS = {"omok": OmokLogic}


@dataclass
class GameRoom:
	room_id: str
	kind: str
	token: str
	title: str
	owner_id: int | None
	owner: str
	public: bool
	created_at: float
	logic: object
	peers: dict = field(default_factory=dict)  # pid → Peer
	chat: list = field(default_factory=list)
	last_active: float = 0.0
	away: dict = field(default_factory=dict)  # pid → 끊긴 시각 (자리 지킨 플레이어)
	_notices: list = field(default_factory=list)

	def notice(self, text):
		self._notices.append(text)

	def info(self, with_token=True):
		data = {
			"id": self.room_id,
			"kind": self.kind,
			"title": self.title,
			"owner_id": self.owner_id,
			"owner": self.owner,
			"public": self.public,
			"created_at": self.created_at,
			"peers": len(self.peers),
			"status": getattr(self.logic, "status", ""),
			"seats_open": sum(1 for p in getattr(self.logic, "seats", {}).values() if not p),
		}
		if with_token:
			data["token"] = self.token
		return data


class GameError(Exception):
	def __init__(self, message, status=400):
		super().__init__(message)
		self.status = status


class GameHub:
	def __init__(self, max_rooms=MAX_ROOMS, seat_grace=SEAT_GRACE):
		self.rooms: dict[str, GameRoom] = {}
		self.max_rooms = max_rooms
		self.seat_grace = seat_grace
		self._reaper = None

	async def start(self):
		self._reaper = asyncio.create_task(self._reap_loop())

	async def stop(self):
		if self._reaper:
			self._reaper.cancel()
		for room_id in list(self.rooms):
			await self.close_room(room_id, "서버가 다시 시작돼 방이 닫혔어요.")

	async def _reap_loop(self):
		while True:
			await asyncio.sleep(5)
			await self.reap()

	async def reap(self, now=None):
		now = now or time.time()
		for room in list(self.rooms.values()):
			# 끊긴 플레이어 자리 정리
			for pid, since in list(room.away.items()):
				if pid in room.peers:
					room.away.pop(pid, None)
				elif now - since >= self.seat_grace:
					room.away.pop(pid, None)
					msg = room.logic.on_leave(pid)
					if msg:
						room.notice(msg)
						await self._push_state(room)
			if now - room.created_at >= ROOM_TTL:
				await self.close_room(room.room_id, "방 시간이 끝났어요.")
			elif not room.peers and now - room.last_active >= IDLE_CLOSE:
				await self.close_room(room.room_id, "아무도 없어 방을 닫았어요.")

	def create_room(self, payload):
		kind = payload.get("kind")
		if kind not in LOGICS:
			raise GameError("모르는 게임이에요.")
		if len(self.rooms) >= self.max_rooms:
			raise GameError("지금은 방이 너무 많아요. 잠시 뒤 다시 시도해 주세요.", status=409)
		room_id = secrets.token_hex(4)
		while room_id in self.rooms:
			room_id = secrets.token_hex(4)
		now = time.time()
		room = GameRoom(
			room_id=room_id, kind=kind, token=secrets.token_urlsafe(12),
			title=" ".join(str(payload.get("title") or "").split())[:40] or "한 판 해요",
			owner_id=payload.get("owner_id"), owner=str(payload.get("owner") or "")[:40],
			public=bool(payload.get("public")), created_at=now, logic=LOGICS[kind](), last_active=now,
		)
		self.rooms[room_id] = room
		log.info("게임 방 생성 %s %s (%s)", kind, room_id, room.owner)
		return room

	async def close_room(self, room_id, reason="방이 닫혔어요."):
		room = self.rooms.pop(room_id, None)
		if room is None:
			return False
		for peer in list(room.peers.values()):
			await self._send(peer, {"type": "end", "reason": reason})
			try:
				await peer.ws.close()
			except (ConnectionResetError, RuntimeError):
				pass
		return True

	async def _send(self, peer, data):
		if peer is None or peer.ws.closed:
			return
		try:
			await peer.ws.send_json(data)
		except (ConnectionResetError, RuntimeError):
			pass

	async def _broadcast(self, room, data):
		await asyncio.gather(*(self._send(p, data) for p in list(room.peers.values())))

	async def _push_state(self, room):
		notices, room._notices = room._notices, []
		for text in notices:
			item = {"type": "chat", "system": True, "text": text, "at": int(time.time())}
			room.chat = (room.chat + [item])[-CHAT_HISTORY:]
			await self._broadcast(room, item)
		state, peers = room.logic.snapshot(room), self._peer_list(room)
		# 같은 상태 + 각자 자기 자리(you) 를 알려 줌
		await asyncio.gather(*(self._send(p, {"type": "state", "state": state, "peers": peers, "you": room.logic.seat_of(p.pid)})
							   for p in list(room.peers.values())))

	def _peer_list(self, room):
		return [{"name": p.name, "seat": room.logic.seat_of(p.pid)} for p in room.peers.values()]

	async def handle(self, request):
		room = self.rooms.get(request.match_info["room_id"])
		token = request.query.get("token", "")
		if room is None or not token or not hmac.compare_digest(token, room.token):
			return web.Response(status=404, text="no such room")
		pid = str(request.query.get("pid", ""))[:64]
		if len(pid) < 16:
			return web.Response(status=400, text="bad pid")
		if pid not in room.peers and len(room.peers) >= MAX_PEERS:
			return web.Response(status=429, text="room full")

		ws = web.WebSocketResponse(heartbeat=20, max_msg_size=MAX_MSG)
		await ws.prepare(request)
		peer = Peer(pid=pid, ws=ws, name=_clean_name(request.query.get("name"), f"손님{secrets.randbelow(900) + 100}"))
		old = room.peers.get(pid)
		room.peers[pid] = peer
		room.away.pop(pid, None)
		room.last_active = time.time()
		if old is not None:  # 같은 사람이 새 창으로 들어오면 예전 연결은 닫음
			await self._send(old, {"type": "end", "reason": "다른 창에서 이 방을 열었어요."})
			await old.ws.close()
		seat = room.logic.seat_of(pid)
		if seat:
			room.logic.names[seat] = peer.name
		await ws.send_json({"type": "hello", "room": room.info(with_token=False), "seat": seat, "chat": room.chat})
		if old is None:
			room.notice(f"{peer.name} 님이 들어왔어요.")
		await self._push_state(room)

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
				if not isinstance(data, dict):
					continue
				room.last_active = time.time()
				await self._on_message(room, peer, data)
		finally:
			if room.peers.get(pid) is peer:
				room.peers.pop(pid, None)
				if room.logic.seat_of(pid):
					room.away[pid] = time.time()  # 잠깐 기다려 줌
				room.notice(f"{peer.name} 님이 나갔어요.")
				if room.room_id in self.rooms:
					await self._push_state(room)
		return ws

	async def _on_message(self, room, peer, data):
		if data.get("type") == "chat":
			now = time.time()
			text = " ".join(str(data.get("text") or "").split())[:CHAT_MAX_CHARS]
			if not text or now - peer.last_chat < CHAT_MIN_INTERVAL:
				return
			peer.last_chat = now
			item = {"type": "chat", "name": peer.name, "seat": room.logic.seat_of(peer.pid), "text": text, "at": int(now)}
			room.chat = (room.chat + [item])[-CHAT_HISTORY:]
			await self._broadcast(room, item)
			return
		changed, error = room.logic.on_message(room, peer, data)
		if error:
			await self._send(peer, {"type": "error", "text": error})
		if changed:
			await self._push_state(room)


def add_game_routes(app, hub: GameHub):
	async def create(request):
		try:
			payload = await request.json()
		except json.JSONDecodeError:
			payload = {}
		try:
			room = hub.create_room(payload)
		except GameError as exc:
			return web.json_response({"error": str(exc)}, status=exc.status)
		return web.json_response(room.info(), status=201)

	async def listing(request):
		return web.json_response({"rooms": [r.info() for r in hub.rooms.values()]})

	async def detail(request):
		room = hub.rooms.get(request.match_info["room_id"])
		if room is None:
			return web.json_response({"error": "방이 없습니다."}, status=404)
		return web.json_response(room.info())

	async def delete(request):
		ok = await hub.close_room(request.match_info["room_id"], "방장이 방을 닫았어요.")
		return web.json_response({"closed": ok}, status=200 if ok else 404)

	app.router.add_post("/games", create)
	app.router.add_get("/games", listing)
	app.router.add_get("/games/{room_id}", detail)
	app.router.add_delete("/games/{room_id}", delete)
	app.router.add_get("/relay/ws/game/{room_id}", hub.handle)
