"""MJ Gallery 실시간 데이터 스트림 중계 데몬 (mj-relay).

방(room) 하나 = 외부에 여는 포트 2개.
  IN  (PULL, bind) : 보내는 쪽이 접속 (GNU Radio "ZMQ PUSH Sink" Bind=No, 또는 mj_stream.py send)
  OUT (PUB/PUSH, bind) : 받는 쪽이 접속 (GNU Radio "ZMQ SUB Source", 또는 mj_stream.py recv)
받은 ZMQ 메시지(멀티파트 포함)는 내용을 건드리지 않고 그대로 OUT 으로 넘긴다.

  - IQ 실시간 / 일반 바이트 → OUT 은 PUB: 여러 명이 받을 수 있고, 느린 수신자는 버려짐(실시간 우선),
    속도 상한을 넘는 데이터는 버림
  - 파일 → OUT 은 PUSH: 받는 쪽이 없거나 느리면 기다림(데이터 손실 없음), 속도 상한은 늦춰서 지킴

접속 허용 (고정 IP 가 없어도 되도록):
  방마다 보내는 쪽·받는 쪽 링크(역할 토큰)가 있고, 그 링크를 연 네트워크의 공인 IP 가
  해당 역할로 "입장" 등록된다. 등록된 IP(또는 방을 만들 때 적은 고정 IP)만 포트에 접속할 수 있다.
  등록은 JOIN_TTL 동안 유지되고, 링크 페이지가 열려 있는 동안 주기적으로 갱신된다.

제어 API 는 127.0.0.1 에서만 열고 공유 비밀키(X-Relay-Key)로 보호한다 (Django 가 호출).
웹 화면은 /relay/ws/<room>?token= WebSocket 으로 통계와 IQ 스냅샷(저대역)만 받는다.
"""

import argparse
import asyncio
import hmac
import ipaddress
import json
import logging
import os
import secrets
import time
from dataclasses import dataclass, field

import zmq
import zmq.asyncio
from aiohttp import WSMsgType, web
from zmq.utils.monitor import parse_monitor_message

log = logging.getLogger("mj-relay")

KINDS = {"iq", "file", "raw"}
IQ_FORMATS = {"fc32": 8, "sc16": 4, "sc8": 2}  # 샘플 하나의 바이트 수 (I+Q)
FILE_HEADER = b"MJF1"
FILE_END = b"MJF1-END"
SNAPSHOT_SAMPLES = 1024
STATS_INTERVAL = 0.25
SNAPSHOT_INTERVAL = 0.125
MAX_VIEWERS_PER_ROOM = 5
JOIN_TTL = 15 * 60  # 링크로 입장한 IP 등록 유지 시간 (페이지가 열려 있으면 계속 갱신)
ROLES = ("sender", "receiver")

MB = 1024 * 1024
GB = 1024 * MB


@dataclass
class Config:
	api_host: str = "127.0.0.1"
	api_port: int = 8090
	api_key: str = ""
	bind_host: str = "0.0.0.0"
	port_min: int = 5550
	port_max: int = 5599
	max_rooms: int = 5
	default_ttl: int = 3600
	max_ttl: int = 6 * 3600
	default_rate: int = 16 * MB
	max_rate: int = 64 * MB
	default_total: int = 20 * GB
	max_total: int = 200 * GB

	@classmethod
	def from_env(cls):
		env = os.environ.get
		return cls(
			api_host=env("RELAY_API_HOST", "127.0.0.1"),
			api_port=int(env("RELAY_API_PORT", "8090")),
			api_key=env("RELAY_API_KEY", ""),
			bind_host=env("RELAY_BIND_HOST", "0.0.0.0"),
			port_min=int(env("RELAY_PORT_MIN", "5550")),
			port_max=int(env("RELAY_PORT_MAX", "5599")),
			max_rooms=int(env("RELAY_MAX_ROOMS", "5")),
		)


class RoomError(Exception):
	def __init__(self, message, status=400):
		super().__init__(message)
		self.status = status


class TokenBucket:
	"""초당 rate 바이트, 1초 분량까지 몰아서 허용."""

	def __init__(self, rate):
		self.rate = rate
		self.tokens = float(rate)
		self.updated = time.monotonic()

	def _refill(self):
		now = time.monotonic()
		self.tokens = min(self.rate, self.tokens + (now - self.updated) * self.rate)
		self.updated = now

	def try_take(self, amount):
		self._refill()
		if amount <= self.tokens:
			self.tokens -= amount
			return True
		return False

	def wait_time(self, amount):
		"""amount 를 보내려면 기다려야 하는 초 (한 번에 rate 보다 크면 나눠서 기다린 것으로 침)."""
		self._refill()
		need = min(amount, self.rate) - self.tokens
		return max(0.0, need / self.rate)

	def take(self, amount):
		self._refill()
		self.tokens -= min(amount, self.rate)


@dataclass
class Room:
	id: str
	token: str  # 관리자 화면용
	sender_token: str
	receiver_token: str
	kind: str
	meta: dict
	allow_ips: list
	in_port: int
	out_port: int
	rate_limit: int
	total_limit: int
	created_at: float
	expires_at: float
	bytes_in: int = 0
	bytes_dropped: int = 0
	messages: int = 0
	last_rx: float = 0.0
	senders: int = 0
	receivers: int = 0
	rate_bps: float = 0.0
	closed_reason: str = ""
	file_info: dict = field(default_factory=dict)
	snapshot: bytes = b""
	joined: dict = field(default_factory=lambda: {"sender": {}, "receiver": {}})  # 역할 → {ip: 마지막 갱신 시각}
	viewers: set = field(default_factory=set)
	tasks: list = field(default_factory=list)
	sockets: list = field(default_factory=list)

	def joined_ips(self, role):
		now = time.time()
		return [ip for ip, seen in self.joined[role].items() if now - seen < JOIN_TTL]

	def allows(self, role, address):
		"""role 쪽 포트에 address 가 접속해도 되는지 (고정 IP 는 보내는 쪽에만 적용)."""
		allowed = list(self.joined_ips(role))
		if role == "sender":
			allowed += self.allow_ips
		return _ip_allowed(address, allowed)

	def token_role(self, token):
		for role, value in (("admin", self.token), ("sender", self.sender_token), ("receiver", self.receiver_token)):
			if token and hmac.compare_digest(token, value):
				return role
		return None

	def public(self, with_tokens=True):
		now = time.time()
		data = {
			"id": self.id,
			"kind": self.kind,
			"meta": self.meta,
			"allow_ips": self.allow_ips,
			"in_port": self.in_port,
			"out_port": self.out_port,
			"out_socket": "PUSH" if self.kind == "file" else "PUB",
			"rate_limit": self.rate_limit,
			"total_limit": self.total_limit,
			"created_at": self.created_at,
			"expires_at": self.expires_at,
			"expires_in": max(0, int(self.expires_at - now)),
			"joined": {role: self.joined_ips(role) for role in ROLES},
			"stats": self.stats(),
		}
		if with_tokens:
			data.update(token=self.token, sender_token=self.sender_token, receiver_token=self.receiver_token)
		return data

	def stats(self):
		return {
			"bytes_in": self.bytes_in,
			"bytes_dropped": self.bytes_dropped,
			"messages": self.messages,
			# 1초 넘게 안 들어오면 처리량 0 (마지막 값이 남아 보이지 않게)
			"rate_bps": round(self.rate_bps, 1) if self.last_rx and time.time() - self.last_rx < 1.5 else 0,
			"senders": self.senders,
			"receivers": self.receivers,
			"viewers": len(self.viewers),
			"ready": self.senders > 0 and self.receivers > 0,
			"idle_seconds": round(time.time() - self.last_rx, 1) if self.last_rx else None,
			"file": self.file_info or None,
			"closed": self.closed_reason or None,
		}


def _clamp(value, default, low, high):
	try:
		value = int(value)
	except (TypeError, ValueError):
		return default
	return max(low, min(high, value))


def _parse_allow_ips(raw):
	ips = []
	for item in raw or []:
		item = str(item).strip()
		if not item:
			continue
		try:
			ips.append(str(ipaddress.ip_network(item, strict=False)))
		except ValueError as exc:
			raise RoomError(f"IP 형식이 올바르지 않습니다: {item}") from exc
	return ips


def _ip_allowed(address, allow_ips):
	try:
		ip = ipaddress.ip_address(address)
	except ValueError:
		return False
	return any(ip in ipaddress.ip_network(net) for net in allow_ips)


class Relay:
	def __init__(self, config: Config):
		self.config = config
		self.ctx = zmq.asyncio.Context()
		self.rooms: dict[str, Room] = {}
		self._background = []

	# ── 시작 / 종료 ─────────────────────────────
	async def start(self):
		self._zap = self.ctx.socket(zmq.REP)
		self._zap.linger = 0
		self._zap.bind("inproc://zeromq.zap.01")
		self._background.append(asyncio.create_task(self._zap_loop()))
		self._background.append(asyncio.create_task(self._expiry_loop()))

	async def stop(self):
		for room_id in list(self.rooms):
			await self.close_room(room_id, "서버 종료")
		for task in self._background:
			task.cancel()
		await asyncio.gather(*self._background, return_exceptions=True)
		self._zap.close(0)
		self.ctx.term()

	# ── ZAP: 방별 보내는 쪽 IP 허용 목록 ───────────
	async def _zap_loop(self):
		while True:
			frames = await self._zap.recv_multipart()
			version, request_id, domain, address = frames[0], frames[1], frames[2], frames[3]
			room_id, _, side = domain.decode(errors="ignore").partition(":")
			room = self.rooms.get(room_id)
			role = "sender" if side == "in" else "receiver"
			if room is None:
				status, text = b"400", b"no such room"
			elif room.allows(role, address.decode(errors="ignore")):
				status, text = b"200", b"OK"
			else:
				# 300(일시적 거절) + handshake_ivl: 2초마다 끊고 다시 확인 → GNU Radio 를 먼저 켜 두고
				# 나중에 링크로 입장해도 자동으로 붙음. 400 이면 클라이언트가 재접속을 포기함.
				status, text = b"300", b"not joined yet"
			if status != b"200":
				log.info("ZAP 거부(%s): room=%s ip=%s", status.decode(), domain, address)
			await self._zap.send_multipart([version, request_id, status, text, b"", b""])

	# ── 방 만들기 / 닫기 ─────────────────────────
	def _bind_free_port(self, sock, used):
		for port in range(self.config.port_min, self.config.port_max + 1):
			if port in used:
				continue
			try:
				sock.bind(f"tcp://{self.config.bind_host}:{port}")
			except zmq.ZMQError:
				continue
			used.add(port)
			return port
		raise RoomError("사용할 수 있는 포트가 없습니다.", status=503)

	async def create_room(self, payload):
		if len(self.rooms) >= self.config.max_rooms:
			raise RoomError(f"동시에 열 수 있는 방은 최대 {self.config.max_rooms}개입니다.", status=409)
		kind = payload.get("kind", "iq")
		if kind not in KINDS:
			raise RoomError("종류는 iq / file / raw 중 하나여야 합니다.")
		meta = payload.get("meta") or {}
		if not isinstance(meta, dict):
			raise RoomError("meta 는 객체여야 합니다.")
		if kind == "iq" and meta.get("format", "fc32") not in IQ_FORMATS:
			raise RoomError("IQ 형식은 fc32 / sc16 / sc8 중 하나여야 합니다.")
		if kind == "iq":
			meta.setdefault("format", "fc32")
		cfg = self.config
		now = time.time()
		ttl = _clamp(payload.get("ttl"), cfg.default_ttl, 60, cfg.max_ttl)
		allow_ips = _parse_allow_ips(payload.get("allow_ips"))  # 포트를 열기 전에 입력 검증

		used = {p for room in self.rooms.values() for p in (room.in_port, room.out_port)}
		room_id = secrets.token_urlsafe(6).replace("-", "a").replace("_", "b")
		pull = self.ctx.socket(zmq.PULL)
		out = self.ctx.socket(zmq.PUSH if kind == "file" else zmq.PUB)
		for sock in (pull, out):
			sock.linger = 0
			sock.rcvhwm = sock.sndhwm = 1000
			# 입장 전 연결은 ZAP 300 으로 붙잡혀 있다가 2초 뒤 끊김 → 클라이언트가 재접속하며 다시 확인받음
			# (400 으로 거절하면 GNU Radio 등 ZMQ 클라이언트가 재접속을 영영 포기함)
			sock.handshake_ivl = 2000
		# 연결할 때마다 ZAP 으로 IP 확인 (보내는 쪽 / 받는 쪽 따로)
		pull.zap_domain = f"{room_id}:in".encode()
		out.zap_domain = f"{room_id}:out".encode()
		try:
			in_port = self._bind_free_port(pull, used)
			out_port = self._bind_free_port(out, used)
		except RoomError:
			pull.close(0)
			out.close(0)
			raise

		room = Room(
			id=room_id,
			token=secrets.token_urlsafe(16),
			sender_token=secrets.token_urlsafe(16),
			receiver_token=secrets.token_urlsafe(16),
			kind=kind,
			meta=meta,
			allow_ips=allow_ips,
			in_port=in_port,
			out_port=out_port,
			rate_limit=_clamp(payload.get("rate_limit"), cfg.default_rate, 64 * 1024, cfg.max_rate),
			total_limit=_clamp(payload.get("total_limit"), cfg.default_total, MB, cfg.max_total),
			created_at=now,
			expires_at=now + ttl,
			sockets=[pull, out],
		)
		self.rooms[room_id] = room
		# 감시는 지금 바로 켬: 태스크가 돌기 전에 들어온 연결도 놓치지 않도록
		events = zmq.EVENT_HANDSHAKE_SUCCEEDED | zmq.EVENT_DISCONNECTED
		in_mon = pull.get_monitor_socket(events)
		out_mon = out.get_monitor_socket(events)
		room.tasks = [
			asyncio.create_task(self._pump(room, pull, out)),
			asyncio.create_task(self._monitor(room, in_mon, "senders")),
			asyncio.create_task(self._monitor(room, out_mon, "receivers")),
			asyncio.create_task(self._broadcast(room)),
		]
		log.info("방 생성 %s kind=%s in=%s out=%s", room_id, kind, in_port, out_port)
		return room

	def join(self, room_id, role, token, ip):
		"""역할 링크를 연 네트워크의 IP 를 등록 (같은 IP 면 시각만 갱신)."""
		room = self.rooms.get(room_id)
		if room is None:
			raise RoomError("방이 없습니다.", status=404)
		if role not in ROLES or room.token_role(token) not in (role, "admin"):
			raise RoomError("링크가 올바르지 않습니다.", status=403)
		try:
			ipaddress.ip_address(ip)
		except ValueError as exc:
			raise RoomError("IP 를 확인할 수 없습니다.") from exc
		room.joined[role][ip] = time.time()
		# 오래된 등록 정리
		room.joined[role] = {k: v for k, v in room.joined[role].items() if time.time() - v < JOIN_TTL}
		log.info("입장 room=%s role=%s ip=%s", room_id, role, ip)
		return room

	async def close_room(self, room_id, reason="닫힘"):
		room = self.rooms.pop(room_id, None)
		if room is None:
			return False
		room.closed_reason = reason
		for ws in list(room.viewers):
			try:
				await ws.send_json({"type": "closed", "reason": reason})
				await ws.close()
			except Exception:  # noqa: BLE001
				pass
		for task in room.tasks:
			task.cancel()
		await asyncio.gather(*room.tasks, return_exceptions=True)
		for sock in room.sockets:
			try:
				sock.disable_monitor()
			except zmq.ZMQError:
				pass
			sock.close(0)
		log.info("방 닫힘 %s (%s)", room_id, reason)
		return True

	async def _expiry_loop(self):
		while True:
			await asyncio.sleep(1)
			now = time.time()
			for room in list(self.rooms.values()):
				if now >= room.expires_at:
					await self.close_room(room.id, "유효 시간이 끝났습니다")

	# ── 데이터 중계 ─────────────────────────────
	async def _pump(self, room, pull, out):
		bucket = TokenBucket(room.rate_limit)
		window = []  # (시각, 바이트) — 최근 1초 처리량 계산용
		bytes_per_sample = IQ_FORMATS.get(room.meta.get("format"), 8)
		snap_len = SNAPSHOT_SAMPLES * bytes_per_sample
		while True:
			frames = await pull.recv_multipart()
			size = sum(len(f) for f in frames)
			now = time.time()
			room.last_rx = now

			if room.kind == "file":
				head = frames[0]
				if head == FILE_HEADER and len(frames) > 1:
					room.file_info = {**_safe_json(frames[1]), "received": 0, "done": False}
				elif head == FILE_END:
					room.file_info = {**room.file_info, "done": True}
				# 파일은 버리지 않고 속도만 늦춤
				delay = bucket.wait_time(size)
				if delay:
					await asyncio.sleep(delay)
				bucket.take(size)
				await out.send_multipart(frames)
				if head not in (FILE_HEADER, FILE_END) and room.file_info:
					room.file_info["received"] = room.file_info.get("received", 0) + size
			else:
				if not bucket.try_take(size):
					room.bytes_dropped += size
					continue
				try:
					out.send_multipart(frames, flags=zmq.NOBLOCK)
				except zmq.Again:
					room.bytes_dropped += size
				if room.kind == "iq":
					last = frames[-1]
					room.snapshot = last[-snap_len:] if len(last) >= snap_len else (room.snapshot + last)[-snap_len:]

			room.bytes_in += size
			room.messages += 1
			window.append((now, size))
			while window and window[0][0] < now - 1:
				window.pop(0)
			room.rate_bps = sum(s for _, s in window)

			if room.bytes_in >= room.total_limit:
				asyncio.create_task(self.close_room(room.id, "총 전송량 한도에 도달했습니다"))
				return

	async def _monitor(self, room, mon, attr):
		"""인증(ZAP)까지 통과한 연결만 송신자·수신자 수로 셈 (거절돼 재시도 중인 연결은 제외)."""
		live = set()  # 연결별 fd
		try:
			while True:
				event = parse_monitor_message(await mon.recv_multipart())
				if event["event"] == zmq.EVENT_HANDSHAKE_SUCCEEDED:
					live.add(event["value"])
				elif event["event"] == zmq.EVENT_DISCONNECTED:
					live.discard(event["value"])
				setattr(room, attr, len(live))
		finally:
			mon.close(0)

	async def _broadcast(self, room):
		"""웹 화면에 통계(0.25초)와 IQ 스냅샷(0.125초) 전송."""
		last_stats = 0.0
		while True:
			await asyncio.sleep(SNAPSHOT_INTERVAL)
			if not room.viewers:
				continue
			now = time.monotonic()
			stats = None
			if now - last_stats >= STATS_INTERVAL:
				last_stats = now
				stats = {"type": "stats", **room.public(with_tokens=False)}
			snap = room.snapshot if room.kind == "iq" else b""
			for ws in list(room.viewers):
				try:
					if stats:
						await ws.send_json(stats)
					if snap:
						await ws.send_bytes(snap)
				except Exception:  # noqa: BLE001 - 끊긴 화면은 정리
					room.viewers.discard(ws)


def _safe_json(raw):
	try:
		data = json.loads(raw.decode("utf-8"))
		return data if isinstance(data, dict) else {}
	except (UnicodeDecodeError, json.JSONDecodeError):
		return {}


# ── HTTP: 제어 API + WebSocket ─────────────────────

def build_app(relay: Relay):
	app = web.Application(middlewares=[_api_key_middleware(relay.config.api_key)])
	app["relay"] = relay

	async def create(request):
		try:
			payload = await request.json()
		except json.JSONDecodeError:
			payload = {}
		try:
			room = await relay.create_room(payload)
		except RoomError as exc:
			return web.json_response({"error": str(exc)}, status=exc.status)
		return web.json_response(room.public(), status=201)

	async def listing(request):
		return web.json_response({"rooms": [r.public() for r in relay.rooms.values()]})

	async def detail(request):
		room = relay.rooms.get(request.match_info["room_id"])
		if room is None:
			return web.json_response({"error": "방이 없습니다."}, status=404)
		return web.json_response(room.public())

	async def join(request):
		try:
			payload = await request.json()
		except json.JSONDecodeError:
			payload = {}
		try:
			room = relay.join(request.match_info["room_id"], payload.get("role"), payload.get("token", ""), payload.get("ip", ""))
		except RoomError as exc:
			return web.json_response({"error": str(exc)}, status=exc.status)
		return web.json_response(room.public())

	async def delete(request):
		ok = await relay.close_room(request.match_info["room_id"], "관리자가 닫았습니다")
		return web.json_response({"closed": ok}, status=200 if ok else 404)

	async def viewer(request):
		room = relay.rooms.get(request.match_info["room_id"])
		token = request.query.get("token", "")
		if room is None or room.token_role(token) is None:
			return web.Response(status=404)
		if len(room.viewers) >= MAX_VIEWERS_PER_ROOM:
			return web.Response(status=429, text="too many viewers")
		ws = web.WebSocketResponse(heartbeat=20)
		await ws.prepare(request)
		room.viewers.add(ws)
		try:
			await ws.send_json({"type": "hello", **room.public(with_tokens=False)})
			async for msg in ws:  # 화면 → 서버 메시지는 쓰지 않음 (연결 유지용)
				if msg.type == WSMsgType.ERROR:
					break
		finally:
			room.viewers.discard(ws)
		return ws

	async def health(request):
		return web.json_response({"ok": True, "rooms": len(relay.rooms)})

	app.router.add_post("/rooms", create)
	app.router.add_get("/rooms", listing)
	app.router.add_get("/rooms/{room_id}", detail)
	app.router.add_delete("/rooms/{room_id}", delete)
	app.router.add_post("/rooms/{room_id}/join", join)
	app.router.add_get("/relay/ws/{room_id}", viewer)
	app.router.add_get("/health", health)
	return app


def _api_key_middleware(api_key):
	@web.middleware
	async def middleware(request, handler):
		# WebSocket(방 토큰으로 보호)과 health 를 뺀 제어 API 는 공유 비밀키 필요
		if request.path.startswith("/relay/ws/") or request.path == "/health":
			return await handler(request)
		given = request.headers.get("X-Relay-Key", "")
		if not api_key or not hmac.compare_digest(given, api_key):
			return web.json_response({"error": "unauthorized"}, status=401)
		return await handler(request)

	return middleware


async def _main(config):
	relay = Relay(config)
	await relay.start()
	app = build_app(relay)
	runner = web.AppRunner(app)
	await runner.setup()
	site = web.TCPSite(runner, config.api_host, config.api_port)
	await site.start()
	log.info("mj-relay 시작: API %s:%s, 포트 %s-%s", config.api_host, config.api_port, config.port_min, config.port_max)
	try:
		await asyncio.Event().wait()
	finally:
		await runner.cleanup()
		await relay.stop()


def main():
	parser = argparse.ArgumentParser(description="MJ Gallery 스트림 중계 데몬")
	parser.add_argument("--env-file", help="KEY=VALUE 형식 설정 파일 (예: 프로젝트 .env)")
	args = parser.parse_args()
	if args.env_file and os.path.exists(args.env_file):
		with open(args.env_file, encoding="utf-8") as fh:
			for line in fh:
				line = line.strip()
				if line and not line.startswith("#") and "=" in line:
					key, value = line.split("=", 1)
					os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
	logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
	config = Config.from_env()
	if not config.api_key:
		raise SystemExit("RELAY_API_KEY 가 설정되지 않았습니다.")
	asyncio.run(_main(config))


if __name__ == "__main__":
	main()
