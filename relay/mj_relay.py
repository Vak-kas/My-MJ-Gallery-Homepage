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

IQ 방은 WebSocket 으로도 보내고 받을 수 있다 (규격 iq-relay/1 — Wireless Lab 의 docs/relay-protocol.md):
  /relay/ws/<room>/iq/send?token=  보내는 쪽 (방마다 하나). 첫 글 메시지 hello → 그 뒤 바이너리 = I/Q 샘플
  /relay/ws/<room>/iq/recv?token=  받는 쪽. 느리면 그 받는 쪽 것만 버리고 gap 으로 알림
방을 만들 때 "zmq": false 를 주면(IQ 방만) ZMQ 포트를 열지 않고 WebSocket 길만 쓴다 — Wireless Lab 끼리만 쓸 때.
두 길은 같은 방으로 이어진다: WebSocket 으로 온 것은 ZMQ OUT·웹 화면 스냅샷에도, ZMQ IN 으로 온 것은 WebSocket 받는 쪽에도.
받은 I/Q 는 저장하지 않고 내용도 풀지 않는다.
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

try:
	from mj_game import GameHub, add_game_routes  # systemd 에서 relay/ 폴더 기준으로 실행
	from mj_live import LiveHub, add_live_routes
except ImportError:  # 테스트 등에서 패키지로 불러올 때
	from relay.mj_game import GameHub, add_game_routes
	from relay.mj_live import LiveHub, add_live_routes

log = logging.getLogger("mj-relay")

KINDS = {"iq", "file", "raw"}
IQ_FORMATS = {"fc32": 8, "sc16": 4, "sc8": 2}  # 샘플 하나의 바이트 수 (I+Q)
FILE_HEADER = b"MJF1"
FILE_END = b"MJF1-END"
SNAPSHOT_SAMPLES = 1024
STATS_INTERVAL = 0.25
SNAPSHOT_INTERVAL = 0.125
MAX_VIEWERS_PER_ROOM = 5
HANDSHAKE_GRACE = 1.5  # 접속 뒤 이 시간 안에 인사가 안 끝나면 '짝 안 맞음'
JOIN_TTL = 15 * 60  # 링크로 입장한 IP 등록 유지 시간 (페이지가 열려 있으면 계속 갱신)
ROLES = ("sender", "receiver")
IQ_PROTO = 1  # iq-relay/1
IQ_MAX_MESSAGE = 1024 * 1024  # 보내는 쪽 바이너리 메시지 하나의 최대 크기
IQ_HELLO_WAIT = 5.0  # 보내는 쪽이 붙고 hello 를 기다리는 시간
IQ_QUEUE = 64  # 받는 쪽마다 밀려도 되는 샘플 메시지 수 — 넘으면 그 받는 쪽 것만 버림
IQ_SENDER_STATS = 1.0  # 보내는 쪽에 통계를 주는 간격

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


class IqReceiver:
	"""WebSocket 받는 쪽 하나의 줄. 샘플 메시지가 IQ_QUEUE 개 넘게 밀리면 새 것을 버리고,
	버린 만큼을 자리가 났을 때 gap(where=relay)으로 먼저 알린다. 넣는 쪽은 절대 기다리지 않는다."""

	def __init__(self, ws, limit=IQ_QUEUE):
		self.ws = ws
		self.limit = limit
		self.queue = asyncio.Queue()
		self.waiting = 0  # 줄에 있는 샘플 메시지 수
		self.lost_bytes = 0
		self.got_hello = False
		self.task = None

	def offer(self, item, sample_bytes):
		"""item: bytes(샘플) 또는 str(JSON 글)."""
		binary = isinstance(item, (bytes, bytearray, memoryview))
		if binary and self.waiting >= self.limit:
			self.lost_bytes += len(item)
			return
		if self.lost_bytes:
			self.queue.put_nowait(json.dumps({"type": "gap", "where": "relay", "lost_bytes": self.lost_bytes,
											  "lost_samples": self.lost_bytes // max(1, sample_bytes), "filled": False}))
			self.lost_bytes = 0
		if binary:
			self.waiting += 1
		elif self.queue.qsize() > self.limit * 8:
			return  # 글 메시지까지 끝없이 밀린 받는 쪽: 더 쌓지 않음
		self.queue.put_nowait(item)

	async def run(self):
		try:
			while True:
				item = await self.queue.get()
				if isinstance(item, str):
					await self.ws.send_str(item)
				else:
					try:
						await self.ws.send_bytes(item)
					finally:
						self.waiting -= 1
		except asyncio.CancelledError:
			raise
		except Exception:  # noqa: BLE001 - 끊긴 받는 쪽
			pass


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
	# 연결 점검: 역할 → {attempts: 접속 시도 수, ok_at: 마지막 성공, fail: {at, kind, ip}} — 방 화면이 '왜 안 붙는지' 알려 줌
	diag: dict = field(default_factory=lambda: {"sender": {"attempts": 0, "ok_at": 0.0, "fail": None}, "receiver": {"attempts": 0, "ok_at": 0.0, "fail": None}})
	misaligned: int = 0  # IQ 샘플 크기로 나눠떨어지지 않는 메시지 수 (형식이 다를 때)
	viewers: set = field(default_factory=set)
	web_receivers: set = field(default_factory=set)  # 브라우저로 파일을 받는 쪽 WebSocket
	web_sending: bool = False  # 브라우저에서 파일을 보내는 중
	send_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
	out_sock: object = None
	file_bucket: object = None
	bucket: object = None  # 실시간(IQ·raw) 속도 상한 — ZMQ 와 WebSocket 이 같이 씀
	window: list = field(default_factory=list)  # (시각, 바이트) — 최근 1초 처리량 계산용
	iq_sender: object = None  # WebSocket 보내는 쪽 (방마다 하나, 연결 확인용 probe 도 자리를 차지)
	iq_hello: dict = None  # 그 보내는 쪽의 지금 hello (meta 를 합친 값). probe 면 None
	iq_receivers: set = field(default_factory=set)  # IqReceiver
	zmq: bool = True  # False: ZMQ 포트를 열지 않은 방 (WebSocket I/Q 전용, in_port·out_port 는 None)
	tasks: list = field(default_factory=list)
	sockets: list = field(default_factory=list)

	def receiver_count(self):
		"""ZMQ(GNU Radio·CLI) 수신자 + 브라우저 수신자 + WebSocket I/Q 수신자."""
		return self.receivers + len(self.web_receivers) + len(self.iq_receivers)

	def sender_count(self):
		"""ZMQ 송신자 + WebSocket I/Q 송신자(연결 확인용 probe 는 빼고)."""
		return self.senders + (1 if self.iq_hello is not None else 0)

	def sample_bytes(self):
		return IQ_FORMATS.get(self.meta.get("format"), 8)

	def current_hello(self):
		"""받는 쪽에 줄 hello: WebSocket 보내는 쪽이 있으면 그 값, 없으면(ZMQ 로 들어올 때) 방 설정으로 지음."""
		if self.iq_hello is not None:
			return self.iq_hello
		hello = {"type": "hello", "proto": IQ_PROTO, "format": self.meta.get("format", "fc32")}
		if self.meta.get("sample_rate"):
			hello["sample_rate_hz"] = self.meta["sample_rate"]
		if self.meta.get("center_freq"):
			hello["center_hz"] = self.meta["center_freq"]
		return hello

	def fan_iq(self, item, hello_first=False):
		"""WebSocket 받는 쪽 모두의 줄에 넣음 (기다리지 않음). hello_first: 아직 hello 를 못 받은 쪽엔 먼저 hello."""
		if not self.iq_receivers:
			return
		size = self.sample_bytes()
		hello = None
		for rx in list(self.iq_receivers):
			if hello_first and not rx.got_hello:
				hello = hello or json.dumps(self.current_hello())
				rx.offer(hello, size)
				rx.got_hello = True
			rx.offer(item, size)

	def fan_hello(self):
		text = json.dumps(self.current_hello())
		for rx in list(self.iq_receivers):
			rx.offer(text, self.sample_bytes())
			rx.got_hello = True

	def fan_bye(self, text=None):
		for rx in list(self.iq_receivers):
			if rx.got_hello:
				rx.offer(text or json.dumps({"type": "bye"}), self.sample_bytes())
			rx.got_hello = False

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
			"zmq": self.zmq,
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
			"senders": self.sender_count(),
			"receivers": self.receivers + len(self.iq_receivers),
			"viewers": len(self.viewers),
			"web_receivers": len(self.web_receivers),
			"ws_sender": self.iq_hello is not None,
			"ws_receivers": len(self.iq_receivers),
			"ready": (self.sender_count() > 0 or self.web_sending) and self.receiver_count() > 0,
			"idle_seconds": round(time.time() - self.last_rx, 1) if self.last_rx else None,
			"file": self.file_info or None,
			"closed": self.closed_reason or None,
			"diag": self.diag_public(),
		}

	def diag_public(self):
		now = time.time()
		out = {}
		for role, d in self.diag.items():
			fail = d.get("fail")
			out[role] = {
				"attempts": d["attempts"],
				"ok_ago": round(now - d["ok_at"], 1) if d["ok_at"] else None,
				"fail": {**fail, "ago": round(now - fail["at"], 1)} if fail else None,
			}
		if self.kind == "iq":
			bps = IQ_FORMATS.get(self.meta.get("format"), 8)
			sr = self.meta.get("sample_rate") or 0
			out["expected_bps"] = sr * bps if sr else None  # 방에 적은 샘플레이트·형식이면 초당 들어와야 할 바이트
			out["misaligned"] = self.misaligned
		return out


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
				if room is not None:
					room.diag[role]["fail"] = {"at": time.time(), "kind": "not_joined", "ip": address.decode(errors="ignore")}
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

		use_zmq = payload.get("zmq", True) is not False
		if not use_zmq and kind != "iq":
			raise RoomError("포트 없이(WebSocket 만) 여는 것은 IQ 방만 됩니다.")
		room_id = secrets.token_urlsafe(6).replace("-", "a").replace("_", "b")
		if not use_zmq:
			return self._create_ws_only_room(room_id, meta, allow_ips, payload, now, ttl)
		used = {p for room in self.rooms.values() for p in (room.in_port, room.out_port) if p}
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
		room.out_sock = out
		room.file_bucket = TokenBucket(room.rate_limit)
		room.bucket = TokenBucket(room.rate_limit)
		self.rooms[room_id] = room
		# 감시는 지금 바로 켬: 태스크가 돌기 전에 들어온 연결도 놓치지 않도록
		events = zmq.EVENT_HANDSHAKE_SUCCEEDED | zmq.EVENT_DISCONNECTED | zmq.EVENT_ACCEPTED
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

	def _create_ws_only_room(self, room_id, meta, allow_ips, payload, now, ttl):
		"""ZMQ 소켓·포트 없이 여는 IQ 방: /relay/ws/<방>/iq/send·recv 로만 보내고 받음."""
		cfg = self.config
		room = Room(
			id=room_id,
			token=secrets.token_urlsafe(16),
			sender_token=secrets.token_urlsafe(16),
			receiver_token=secrets.token_urlsafe(16),
			kind="iq",
			meta=meta,
			allow_ips=allow_ips,
			in_port=None,
			out_port=None,
			rate_limit=_clamp(payload.get("rate_limit"), cfg.default_rate, 64 * 1024, cfg.max_rate),
			total_limit=_clamp(payload.get("total_limit"), cfg.default_total, MB, cfg.max_total),
			created_at=now,
			expires_at=now + ttl,
			zmq=False,
		)
		room.bucket = TokenBucket(room.rate_limit)
		self.rooms[room_id] = room
		room.tasks = [asyncio.create_task(self._broadcast(room))]
		log.info("방 생성 %s kind=iq (WebSocket 전용, 포트 없음)", room_id)
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
		iq_rx, room.iq_receivers = list(room.iq_receivers), set()
		for rx in iq_rx:  # 줄을 비우던 태스크를 먼저 멈춰 closed 와 겹쳐 쓰지 않게
			if rx.task:
				rx.task.cancel()
		for ws in list(room.viewers) + [rx.ws for rx in iq_rx] + ([room.iq_sender] if room.iq_sender is not None else []):
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
	def relay_realtime(self, room, frames):
		"""실시간(IQ·raw) 메시지 하나를 방에 흘림 — ZMQ 로 온 것과 WebSocket 으로 온 것이 같이 씀.
		속도 상한(넘으면 버림) → ZMQ OUT → 스냅샷 → 통계 → 총량 한도. 돌려주는 값: "ok" / "dropped" / "quota"(방을 닫는 중)."""
		size = sum(len(f) for f in frames)
		now = time.time()
		room.last_rx = now
		if not room.bucket.try_take(size):
			room.bytes_dropped += size
			return "dropped"
		if room.out_sock is not None:  # 포트 없는 방(WebSocket 전용)은 ZMQ 로 내보낼 곳이 없음
			try:
				room.out_sock.send_multipart(frames, flags=zmq.NOBLOCK)
			except zmq.Again:
				room.bytes_dropped += size
		if room.kind == "iq":
			bytes_per_sample = room.sample_bytes()  # 보내는 쪽 hello/meta 로 바뀔 수 있어 그때그때 봄
			snap_len = SNAPSHOT_SAMPLES * bytes_per_sample
			if size % bytes_per_sample:
				room.misaligned += 1
			last = frames[-1]
			room.snapshot = bytes(last[-snap_len:]) if len(last) >= snap_len else (room.snapshot + last)[-snap_len:]
		room.bytes_in += size
		room.messages += 1
		window = room.window
		window.append((now, size))
		while window and window[0][0] < now - 1:
			window.pop(0)
		room.rate_bps = sum(s for _, s in window)
		if room.bytes_in >= room.total_limit:
			asyncio.create_task(self.close_room(room.id, "총 전송량 한도에 도달했습니다"))
			return "quota"
		return "ok"

	async def _pump(self, room, pull, out):
		while True:
			frames = await pull.recv_multipart()
			size = sum(len(f) for f in frames)
			now = time.time()

			if room.kind != "file":
				result = self.relay_realtime(room, frames)
				if result != "dropped" and room.kind == "iq" and room.iq_receivers:
					# ZMQ 로 들어온 샘플(프레임의 마지막 조각)을 WebSocket 받는 쪽에도 — 샘플이 쪼개진 것은 넘기지 않음
					last, unit = frames[-1], room.sample_bytes()
					if last and len(last) % unit == 0:
						step = IQ_MAX_MESSAGE // unit * unit
						for i in range(0, len(last), step):
							room.fan_iq(last[i:i + step], hello_first=True)
				if result == "quota":
					return
				continue

			room.last_rx = now
			if room.kind == "file":
				head = frames[0]
				if head == FILE_HEADER and len(frames) > 1:
					room.file_info = {**_safe_json(frames[1]), "received": 0, "done": False}
				elif head == FILE_END:
					room.file_info = {**room.file_info, "done": True}
				# 파일은 버리지 않음: 받는 쪽이 생길 때까지 기다리고(→ ZMQ 역압으로 보내는 쪽도 대기), 속도만 늦춤
				while room.receiver_count() == 0:
					await asyncio.sleep(0.2)
				await self._throttle_file(room, size)
				await self._deliver_file_frames(room, frames)
				if head not in (FILE_HEADER, FILE_END) and room.file_info:
					room.file_info["received"] = room.file_info.get("received", 0) + size

			room.bytes_in += size
			room.messages += 1
			window = room.window
			window.append((now, size))
			while window and window[0][0] < now - 1:
				window.pop(0)
			room.rate_bps = sum(s for _, s in window)

			if room.bytes_in >= room.total_limit:
				asyncio.create_task(self.close_room(room.id, "총 전송량 한도에 도달했습니다"))
				return

	async def _throttle_file(self, room, size):
		delay = room.file_bucket.wait_time(size)
		if delay:
			await asyncio.sleep(delay)
		room.file_bucket.take(size)

	async def _deliver_file_frames(self, room, frames):
		"""파일 프레임(MJF1 프로토콜)을 ZMQ 수신자와 브라우저 수신자 모두에게 전달."""
		if room.receivers > 0:
			await room.out_sock.send_multipart(frames)
		if not room.web_receivers:
			return
		head = frames[0]
		if head == FILE_HEADER and len(frames) > 1:
			message, binary = {"type": "file-start", **_safe_json(frames[1])}, None
		elif head == FILE_END:
			message, binary = {"type": "file-end", **(_safe_json(frames[1]) if len(frames) > 1 else {})}, None
		else:
			message, binary = None, b"".join(frames)
		for ws in list(room.web_receivers):
			try:
				# 받는 쪽 전송이 끝나야 다음 조각을 읽음 → 느린 쪽에 속도가 맞춰짐 (손실 없음)
				if binary is None:
					await ws.send_json(message)
				else:
					await ws.send_bytes(binary)
			except Exception:  # noqa: BLE001 - 끊긴 수신자는 빼고 계속
				room.web_receivers.discard(ws)

	def _check_handshake(self, diag, accepted_at):
		"""접속(TCP)은 왔는데 1.5초 안에 인사(handshake)도 성공 못 하고 등록 안 됨(ZAP) 거절도 아니면
		소켓 종류가 짝이 안 맞는 것 (예: 받는 쪽이 ZMQ SUB Source 대신 PULL Source).
		ZAP 이 켜진 소켓은 이때 '인사 실패' 이벤트를 따로 주지 않아서 시간으로 판단함."""
		async def later():
			await asyncio.sleep(HANDSHAKE_GRACE)
			fail = diag.get("fail")
			zap_denied = fail and fail["kind"] == "not_joined" and fail["at"] >= accepted_at - 0.1
			if diag["ok_at"] < accepted_at and not zap_denied:
				diag["fail"] = {"at": time.time(), "kind": "socket_type"}
		asyncio.create_task(later())

	async def _monitor(self, room, mon, attr):
		"""인증(ZAP)까지 통과한 연결만 송신자·수신자 수로 셈 (거절돼 재시도 중인 연결은 제외)."""
		live = set()  # 인사까지 끝난 연결의 fd
		pending = []  # 접속(TCP)은 했지만 아직 인사가 안 끝난 fd (등록 안 된 IP 는 여기 머물다 끊김)
		diag = room.diag["sender" if attr == "senders" else "receiver"]
		try:
			while True:
				event = parse_monitor_message(await mon.recv_multipart())
				ev = event["event"]
				if ev == zmq.EVENT_HANDSHAKE_SUCCEEDED:
					# 이 이벤트는 fd 를 주지 않음(값이 늘 0) → 가장 최근에 접속한 것으로 침:
					# 인사는 접속 직후 끝나고, 오래 머무는 것은 거절돼 재시도 중인 연결이라서
					if pending:
						live.add(pending.pop())
					diag["ok_at"] = time.time()
				elif ev == zmq.EVENT_DISCONNECTED:
					fd = event["value"]
					if fd in live:
						live.discard(fd)
					elif fd in pending:
						pending.remove(fd)
				elif ev == zmq.EVENT_ACCEPTED:
					pending.append(event["value"])
					diag["attempts"] += 1
					self._check_handshake(diag, time.time())
				was = getattr(room, attr)
				setattr(room, attr, len(live))
				if attr == "senders" and was and not live and room.iq_hello is None:
					room.fan_bye()  # ZMQ 보내는 쪽이 다 나감 → WebSocket 받는 쪽에 끝을 알림 (다시 오면 hello 부터)
		finally:
			mon.close(0)

	# ── WebSocket I/Q (iq-relay/1) ──────────────
	async def serve_iq_sender(self, room, ws):
		"""보내는 쪽 연결 하나를 끝까지 돌봄. room.iq_sender 는 부른 쪽이 잡고 놓는다."""
		async def refuse(code, message):
			try:
				await ws.send_json({"type": "error", "error": code, "message": message})
			except Exception:  # noqa: BLE001
				pass
			await ws.close()

		try:
			first = await asyncio.wait_for(ws.receive(), IQ_HELLO_WAIT)
		except asyncio.TimeoutError:
			return await refuse("bad-hello", "hello 가 오지 않았습니다.")
		hello = _safe_json(first.data.encode()) if first.type == WSMsgType.TEXT else {}
		if hello.get("type") != "hello":
			if first.type in (WSMsgType.CLOSE, WSMsgType.CLOSING, WSMsgType.CLOSED, WSMsgType.ERROR):
				return None
			return await refuse("bad-hello", "첫 메시지는 hello 여야 합니다.")
		if hello.get("proto") != IQ_PROTO or isinstance(hello.get("proto"), bool):
			return await refuse("proto", "모르는 규격 번호입니다.")
		problem = _iq_meta_problem(hello, need=True)
		if problem:
			return await refuse("bad-hello", problem)
		probe = bool(hello.get("probe"))
		if not probe and hello["sample_rate_hz"] * IQ_FORMATS[hello["format"]] > room.rate_limit:
			return await refuse("too-fast", "샘플레이트 × 샘플 크기가 이 방의 속도 상한을 넘습니다.")

		async def stats_loop():
			while True:
				await asyncio.sleep(IQ_SENDER_STATS)
				await ws.send_json({"type": "stats", "bytes_in": room.bytes_in, "bytes_dropped": room.bytes_dropped,
									"receivers": len(room.iq_receivers), "expires_in": max(0, int(room.expires_at - time.time()))})

		stats_task = None
		said_bye = False
		try:
			if not probe:
				room.iq_hello = hello
				_apply_iq_meta(room, hello)
			await ws.send_json({"type": "ready", "proto": IQ_PROTO, "room": room.id, "rate_limit": room.rate_limit, "total_limit": room.total_limit,
								"expires_in": max(0, int(room.expires_at - time.time())), "max_message": IQ_MAX_MESSAGE, "receivers": len(room.iq_receivers)})
			if not probe:
				room.fan_hello()
				log.info("IQ WebSocket 보내는 쪽 room=%s format=%s rate=%s", room.id, hello["format"], hello["sample_rate_hz"])
			stats_task = asyncio.create_task(stats_loop())
			async for msg in ws:
				if probe:
					continue  # 연결 확인용: 아무것도 받지 않음
				if msg.type == WSMsgType.BINARY:
					data = msg.data
					if len(data) % room.sample_bytes():
						return await refuse("misaligned", "샘플이 쪼개진 메시지입니다(길이가 샘플 크기의 배수가 아님).")
					if len(data) > IQ_MAX_MESSAGE:
						return await refuse("too-big", "메시지가 너무 큽니다.")
					result = self.relay_realtime(room, [data])
					if result == "dropped":
						continue
					room.fan_iq(data)
					if result == "quota":
						return await refuse("quota", "총 전송량 한도에 도달했습니다.")
				elif msg.type == WSMsgType.TEXT:
					data = _safe_json(msg.data.encode())
					kind = data.get("type")
					if kind == "meta":
						problem = _iq_meta_problem(data, need=False)
						if problem:
							return await refuse("bad-hello", problem)
						merged = {**room.iq_hello, **{k: v for k, v in data.items() if k != "type"}}
						if merged["sample_rate_hz"] * IQ_FORMATS[merged["format"]] > room.rate_limit:
							return await refuse("too-fast", "샘플레이트 × 샘플 크기가 이 방의 속도 상한을 넘습니다.")
						room.iq_hello = merged
						_apply_iq_meta(room, merged)
						room.fan_iq(msg.data)
					elif kind == "gap":
						room.fan_iq(msg.data)
					elif kind == "bye":
						said_bye = True
						room.fan_bye(msg.data)
					# 모르는 type 은 무시
				elif msg.type == WSMsgType.ERROR:
					break
		finally:  # 준비 도중에 끊겨도 보내는 쪽 표시가 남지 않게
			if stats_task:
				stats_task.cancel()
			if not probe:
				room.iq_hello = None
				if not said_bye:
					room.fan_bye()
				for rx in room.iq_receivers:
					rx.got_hello = False
		return None

	async def serve_iq_receiver(self, room, ws):
		rx = IqReceiver(ws)
		sending = room.sender_count() > 0
		await ws.send_json({"type": "ready", "proto": IQ_PROTO, "room": room.id, "sending": sending})
		if sending:
			await ws.send_json(room.current_hello())
			rx.got_hello = True
		room.iq_receivers.add(rx)
		rx.task = asyncio.create_task(rx.run())
		try:
			async for msg in ws:  # 받는 쪽 → 서버 메시지는 쓰지 않음 (연결 유지용)
				if msg.type == WSMsgType.ERROR:
					break
		finally:
			room.iq_receivers.discard(rx)
			rx.task.cancel()

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


def _iq_meta_problem(data, need):
	"""hello(need=True: 꼭 있어야 함)·meta(있으면 검사)의 format·sample_rate_hz 가 틀렸으면 그 이유."""
	if need or "format" in data:
		if data.get("format") not in IQ_FORMATS:
			return "format 은 fc32 / sc16 / sc8 중 하나여야 합니다."
	if need or "sample_rate_hz" in data:
		rate = data.get("sample_rate_hz")
		if isinstance(rate, bool) or not isinstance(rate, (int, float)) or not 0 < rate < float("inf"):
			return "sample_rate_hz 는 0 보다 큰 수여야 합니다."
	return None


def _apply_iq_meta(room, hello):
	"""보내는 쪽이 실어 보낸 값으로 방 설정을 고침 → 방 화면의 주파수 눈금·'들어와야 할 속도'가 맞음."""
	meta = dict(room.meta)
	meta["format"] = hello["format"]
	meta["sample_rate"] = hello["sample_rate_hz"]
	center = hello.get("center_hz")
	if isinstance(center, (int, float)) and not isinstance(center, bool):
		meta["center_freq"] = center
	room.meta = meta


def _safe_json(raw):
	try:
		data = json.loads(raw.decode("utf-8"))
		return data if isinstance(data, dict) else {}
	except (UnicodeDecodeError, json.JSONDecodeError):
		return {}


# ── HTTP: 제어 API + WebSocket ─────────────────────

def build_app(relay: Relay, live_hub=None, game_hub=None):
	app = web.Application(middlewares=[_api_key_middleware(relay.config.api_key)])
	app["relay"] = relay
	if live_hub is not None:
		add_live_routes(app, live_hub)  # 라이브 방송 시그널링 (relay/mj_live.py)
	if game_hub is not None:
		add_game_routes(app, game_hub)  # 실시간 게임 방 (relay/mj_game.py)

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

	async def web_send(request):
		"""브라우저에서 파일 보내기: {"type":"start",name,size,mime} → 바이너리 조각들 → {"type":"end"}.
		조각마다 ack 를 돌려줘서 보내는 쪽이 받는 쪽 속도에 맞춰 보내게 함."""
		room = relay.rooms.get(request.match_info["room_id"])
		token = request.query.get("token", "")
		if room is None or room.kind != "file" or room.token_role(token) not in ("sender", "admin"):
			return web.Response(status=404)
		if room.send_lock.locked():
			return web.Response(status=409, text="another sender is active")
		ws = web.WebSocketResponse(heartbeat=20, max_msg_size=4 * MB)
		await ws.prepare(request)
		async with room.send_lock:
			room.web_sending = True
			info = None
			try:
				async for msg in ws:
					if msg.type == WSMsgType.TEXT:
						data = _safe_json(msg.data.encode())
						if data.get("type") == "start":
							if room.receiver_count() == 0:
								await ws.send_json({"type": "error", "error": "no-receiver"})
								continue
							info = {"name": str(data.get("name") or "file")[:255], "size": int(data.get("size") or 0), "mime": str(data.get("mime") or "")[:120]}
							room.file_info = {**info, "received": 0, "done": False}
							await self_deliver(room, [FILE_HEADER, json.dumps(info).encode()])
							await ws.send_json({"type": "started"})
						elif data.get("type") == "end" and info is not None:
							room.file_info = {**room.file_info, "done": True}
							await self_deliver(room, [FILE_END, json.dumps({"size": room.file_info["received"]}).encode()])
							await ws.send_json({"type": "done", "received": room.file_info["received"]})
							info = None
					elif msg.type == WSMsgType.BINARY and info is not None:
						if room.receiver_count() == 0:
							await ws.send_json({"type": "error", "error": "receiver-left"})
							info = None
							continue
						size = len(msg.data)
						await relay._throttle_file(room, size)
						await self_deliver(room, [msg.data])
						room.file_info["received"] += size
						room.bytes_in += size
						room.messages += 1
						room.last_rx = time.time()
						await ws.send_json({"type": "ack", "received": room.file_info["received"]})
					elif msg.type == WSMsgType.ERROR:
						break
			finally:
				room.web_sending = False
		return ws

	async def self_deliver(room, frames):
		await relay._deliver_file_frames(room, frames)

	async def web_recv(request):
		"""브라우저에서 파일 받기: file-start(JSON) → 바이너리 조각들 → file-end(JSON)."""
		room = relay.rooms.get(request.match_info["room_id"])
		token = request.query.get("token", "")
		if room is None or room.kind != "file" or room.token_role(token) not in ("receiver", "admin"):
			return web.Response(status=404)
		if len(room.web_receivers) >= MAX_VIEWERS_PER_ROOM:
			return web.Response(status=429, text="too many receivers")
		ws = web.WebSocketResponse(heartbeat=20)
		await ws.prepare(request)
		room.web_receivers.add(ws)
		try:
			await ws.send_json({"type": "ready"})
			async for msg in ws:
				if msg.type == WSMsgType.ERROR:
					break
		finally:
			room.web_receivers.discard(ws)
		return ws

	async def iq_send(request):
		"""I/Q 보내는 쪽 (iq-relay/1): hello → 바이너리 샘플. 방마다 하나."""
		room = relay.rooms.get(request.match_info["room_id"])
		token = request.query.get("token", "")
		if room is None or room.kind != "iq" or room.token_role(token) not in ("sender", "admin"):
			return web.Response(status=404)
		if room.iq_sender is not None:
			return web.Response(status=409, text="another sender is active")
		ws = web.WebSocketResponse(heartbeat=20, max_msg_size=2 * MB, compress=False)  # I/Q 는 눌러도 안 줄어듦
		room.iq_sender = ws  # 올리기 전에 자리부터 잡음 (동시에 둘이 붙지 않게)
		try:
			await ws.prepare(request)
			await relay.serve_iq_sender(room, ws)
		finally:
			if room.iq_sender is ws:
				room.iq_sender = None
		return ws

	async def iq_recv(request):
		"""I/Q 받는 쪽 (iq-relay/1): ready → hello → 바이너리 샘플·meta·gap·bye."""
		room = relay.rooms.get(request.match_info["room_id"])
		token = request.query.get("token", "")
		if room is None or room.kind != "iq" or room.token_role(token) not in ("receiver", "admin"):
			return web.Response(status=404)
		if len(room.iq_receivers) >= MAX_VIEWERS_PER_ROOM:
			return web.Response(status=429, text="too many receivers")
		ws = web.WebSocketResponse(heartbeat=20, max_msg_size=2 * MB, compress=False)  # I/Q 는 눌러도 안 줄어듦
		await ws.prepare(request)
		await relay.serve_iq_receiver(room, ws)
		return ws

	async def health(request):
		return web.json_response({"ok": True, "rooms": len(relay.rooms), "live": len(live_hub.rooms) if live_hub else 0,
								  "games": len(game_hub.rooms) if game_hub else 0})

	app.router.add_post("/rooms", create)
	app.router.add_get("/rooms", listing)
	app.router.add_get("/rooms/{room_id}", detail)
	app.router.add_delete("/rooms/{room_id}", delete)
	app.router.add_post("/rooms/{room_id}/join", join)
	app.router.add_get("/relay/ws/{room_id}", viewer)
	app.router.add_get("/relay/ws/{room_id}/send", web_send)
	app.router.add_get("/relay/ws/{room_id}/recv", web_recv)
	app.router.add_get("/relay/ws/{room_id}/iq/send", iq_send)
	app.router.add_get("/relay/ws/{room_id}/iq/recv", iq_recv)
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
	live_hub = LiveHub()
	await live_hub.start()
	game_hub = GameHub()
	await game_hub.start()
	app = build_app(relay, live_hub, game_hub)
	runner = web.AppRunner(app)
	await runner.setup()
	site = web.TCPSite(runner, config.api_host, config.api_port)
	await site.start()
	log.info("mj-relay 시작: API %s:%s, 포트 %s-%s", config.api_host, config.api_port, config.port_min, config.port_max)
	try:
		await asyncio.Event().wait()
	finally:
		await runner.cleanup()
		await game_hub.stop()
		await live_hub.stop()
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
