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

try:
	from catch_words import ALL as CATCH_WORDS  # systemd 에서 relay/ 폴더 기준으로 실행
except ImportError:
	from relay.catch_words import ALL as CATCH_WORDS

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

	def on_join(self, room, peer):
		seat = self.seat_of(peer.pid)
		if seat:
			self.names[seat] = peer.name

	def on_leave(self, room, pid):
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

	def snapshot(self, room, pid=None):
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


class OthelloLogic(OmokLogic):
	"""8×8 오셀로(리버시). 자리·기권·무르기·다시 하기는 오목과 같고, 두는 규칙만 다름.

	상대 돌을 내 돌 사이에 끼우는 곳에만 둘 수 있고, 끼운 돌은 모두 뒤집힘.
	둘 곳이 없으면 자동으로 넘어가고, 둘 다 둘 곳이 없으면 끝나서 돌이 많은 쪽이 이김.
	"""

	kind = "othello"
	SIZE = 8
	DIRS = ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1))

	def reset(self):
		super().reset()
		n = self.SIZE
		for x, y, c in ((3, 3, "w"), (4, 4, "w"), (3, 4, "b"), (4, 3, "b")):
			self.board[y * n + x] = c
		self.history = []  # 수마다 두기 전 (판, 차례) — 무르기용
		self.flipped = []
		self.passed = ""  # 방금 넘어간 쪽

	def flips(self, x, y, c, board=None):
		board = board or self.board
		n = self.SIZE
		if board[y * n + x] != ".":
			return []
		other = "w" if c == "b" else "b"
		out = []
		for dx, dy in self.DIRS:
			run = []
			nx, ny = x + dx, y + dy
			while 0 <= nx < n and 0 <= ny < n and board[ny * n + nx] == other:
				run.append((nx, ny))
				nx, ny = nx + dx, ny + dy
			if run and 0 <= nx < n and 0 <= ny < n and board[ny * n + nx] == c:
				out += run
		return out

	def legal(self, c):
		n = self.SIZE
		return [(x, y) for y in range(n) for x in range(n) if self.flips(x, y, c)]

	def counts(self):
		return {"black": self.board.count("b"), "white": self.board.count("w")}

	def on_message(self, room, peer, data):
		kind = data.get("type")
		seat = self.seat_of(peer.pid)
		if kind == "move":
			if self.status != "playing":
				return False, "아직 대국이 시작되지 않았어요."
			if seat != self.turn:
				return False, "내 차례가 아니에요." if seat else "구경 중이에요."
			try:
				x, y = int(data.get("x")), int(data.get("y"))
			except (TypeError, ValueError):
				return False, None
			n = self.SIZE
			c = seat[0]
			got = self.flips(x, y, c) if 0 <= x < n and 0 <= y < n else []
			if not got:
				return False, "상대 돌을 끼워서 뒤집을 수 있는 곳에만 둘 수 있어요."
			self.history.append((self.board[:], self.turn))
			self.board[y * n + x] = c
			for fx, fy in got:
				self.board[fy * n + fx] = c
			self.moves.append((x, y, c))
			self.flipped = [list(p) for p in got]
			self.undo_from = None
			self.passed = ""
			other = "white" if seat == "black" else "black"
			if self.legal(other[0]):
				self.turn = other
			elif self.legal(c):
				self.passed = other
				room.notice(f"{self.names[other]} 님은 둘 곳이 없어서 한 번 쉬어요.")
			else:
				cnt = self.counts()
				if cnt["black"] == cnt["white"]:
					self._finish(None, f"{cnt['black']} 대 {cnt['white']}, 무승부!")
				else:
					win = "black" if cnt["black"] > cnt["white"] else "white"
					lose = "white" if win == "black" else "black"
					self._finish(win, f"{self.names[win]} 님 승리! {cnt[win]} 대 {cnt[lose]}")
			return True, None
		if kind == "undo-ok":
			if not self.undo_from or not seat or seat == self.undo_from or not self.history:
				return False, None
			self.board, _ = self.history.pop()
			self.moves.pop()
			self.turn = self.undo_from
			self.flipped = []
			self.passed = ""
			self.undo_from = None
			room.notice("한 수 물렀어요.")
			return True, None
		return super().on_message(room, peer, data)

	def snapshot(self, room, pid=None):
		data = super().snapshot(room, pid)
		data["counts"] = self.counts()
		data["flipped"] = self.flipped
		data["passed"] = self.passed
		data["legal"] = [list(p) for p in self.legal(self.turn[0])] if self.status == "playing" else []
		return data


# ── 그림 맞추기 ─────────────────────────────

def _norm(text):
	return "".join(str(text).split()).lower()


def _edit1(a, b):
	"""두 글자열이 한 글자만 다른지 (바꾸기·넣기·빼기)."""
	if a == b or abs(len(a) - len(b)) > 1:
		return False
	if len(a) == len(b):
		return sum(x != y for x, y in zip(a, b)) == 1
	if len(a) > len(b):
		a, b = b, a
	return any(a == b[:i] + b[i + 1:] for i in range(len(b)))


class CatchLogic:
	"""한 명이 제시어를 그리고 나머지가 채팅으로 맞히는 게임. 판·점수·시간은 서버가 관리."""

	kind = "catchmind"
	MAX_PLAYERS = 10
	CHOOSE_SECONDS = 12
	REVEAL_SECONDS = 5
	TURN_CHOICES = (40, 60, 80, 100, 120)
	COLORS = ("#111111", "#ffffff", "#ef4444", "#f97316", "#facc15", "#22c55e", "#3b82f6", "#8b5cf6", "#ec4899", "#8b5a2b", "#9ca3af")
	WIDTHS = (3, 7, 14, 28)
	MAX_POINTS = 40_000  # 한 차례에 그릴 수 있는 점 수 (서버 메모리·전송 보호)

	def __init__(self, words=None, rng=None):
		import random as _random
		self.rng = rng or _random.Random()
		self.words = list(words or CATCH_WORDS)
		self.players = {}  # pid → {name, score, guessed, gained}
		self.order = []
		self.host = None
		self.rounds = 2
		self.turn_time = 80
		self.status = "lobby"  # lobby / choosing / drawing / reveal / end
		self.round = 0
		self.drawer_idx = -1
		self.drawer = None
		self.options = []
		self.word = None
		self.deadline = 0.0
		self.started = 0.0
		self.strokes = []
		self.points = 0
		self.hints = []
		self.used = set()
		self.last_word = None
		self.seats = {}  # 방 목록의 '빈 자리' 계산용 (그림 맞추기는 자리 개념 없음)

	# 공통 훅
	def seat_of(self, pid):
		if pid not in self.players:
			return None
		return "drawer" if pid == self.drawer else "player"

	def on_join(self, room, peer):
		p = self.players.get(peer.pid)
		if p:
			p["name"] = peer.name
		elif len(self.players) < self.MAX_PLAYERS:
			self.players[peer.pid] = {"name": peer.name, "score": 0, "guessed": False, "gained": 0}
			self.order.append(peer.pid)
			if not self.host:
				self.host = peer.pid
		# 지금까지 그린 그림을 새로 들어온 사람에게
		room.emit({"type": "sync", "strokes": self.strokes}, to=peer.pid)

	def on_leave(self, room, pid):
		p = self.players.pop(pid, None)
		if not p:
			return None
		idx = self.order.index(pid)
		self.order.remove(pid)
		if idx <= self.drawer_idx:
			self.drawer_idx -= 1  # 순서가 앞으로 당겨짐
		if self.host == pid:
			self.host = self.order[0] if self.order else None
		if len(self.players) < 2 and self.status in ("choosing", "drawing", "reveal"):
			self.status = "lobby"
			self.drawer = None
			room.notice("사람이 부족해서 게임을 멈췄어요.")
		elif pid == self.drawer and self.status in ("choosing", "drawing"):
			self._reveal(room, time.time(), f"그리던 {p['name']} 님이 나갔어요.")
		return f"{p['name']} 님이 게임에서 빠졌어요."

	# 진행
	def _start(self, room, now):
		for p in self.players.values():
			p.update(score=0, guessed=False, gained=0)
		self.round, self.drawer_idx, self.used = 1, -1, set()
		room.notice(f"게임 시작! {self.rounds}바퀴, 한 사람 {self.turn_time}초.")
		self._next_turn(room, now)

	def _next_turn(self, room, now):
		self.drawer_idx += 1
		if self.drawer_idx >= len(self.order):
			self.round += 1
			self.drawer_idx = 0
		if self.round > self.rounds or not self.order:
			self.status = "end"
			self.drawer = None
			ranking = sorted(self.players.values(), key=lambda p: -p["score"])
			if ranking:
				room.notice(f"🏆 게임 끝! 1등은 {ranking[0]['name']} 님 ({ranking[0]['score']}점)")
			return
		self.drawer = self.order[self.drawer_idx]
		pool = [w for w in self.words if w not in self.used] or self.words
		self.options = self.rng.sample(pool, min(3, len(pool)))
		self.word, self.hints, self.strokes, self.points = None, [], [], 0
		for p in self.players.values():
			p.update(guessed=False, gained=0)
		self.status = "choosing"
		self.deadline = now + self.CHOOSE_SECONDS
		room.emit({"type": "clear"})

	def _choose(self, room, now, word):
		self.word = word
		self.used.add(word)
		self.options = []
		self.status = "drawing"
		self.started = now
		self.deadline = now + self.turn_time
		room.notice(f"✏️ {self.players[self.drawer]['name']} 님이 그리기 시작했어요. ({len(word)}글자)")

	def _reveal(self, room, now, reason=""):
		self.status = "reveal"
		self.deadline = now + self.REVEAL_SECONDS
		self.last_word = self.word
		if self.word:
			room.notice(f"{reason + ' ' if reason else ''}정답은 '{self.word}' 였어요.")

	def tick(self, room, now):
		if self.status == "choosing" and now >= self.deadline:
			self._choose(room, now, self.options[0] if self.options else self.rng.choice(self.words))
			return True
		if self.status == "drawing":
			if now >= self.deadline:
				self._reveal(room, now, "⏰ 시간 끝!")
				return True
			# 시간이 반·4분의 3 지나면 글자 하나씩 알려 줌
			passed = (now - self.started) / self.turn_time
			want = (passed >= 0.5) + (passed >= 0.75 and len(self.word) >= 3)
			if len(self.hints) < want:
				hidden = [i for i, ch in enumerate(self.word) if i not in self.hints and not ch.isspace()]
				if len(hidden) > 1:
					self.hints.append(self.rng.choice(hidden))
					return True
			return False
		if self.status == "reveal" and now >= self.deadline:
			self._next_turn(room, now)
			return True
		return False

	def on_chat(self, room, peer, text):
		"""(채팅을 대신 처리했는지, 상태가 바뀌었는지)."""
		if self.status != "drawing" or not self.word:
			return False, False
		guess, answer = _norm(text), _norm(self.word)
		p = self.players.get(peer.pid)
		if peer.pid == self.drawer or (p and p["guessed"]):
			if answer in guess:
				room.emit({"type": "error", "text": "정답이 들어간 말은 보낼 수 없어요."}, to=peer.pid)
				return True, False
			return False, False
		if not p:
			return False, False  # 구경꾼은 그냥 채팅
		if guess == answer:
			now = time.time()
			left = max(0.0, (self.deadline - now) / self.turn_time)
			order = sum(1 for q in self.players.values() if q["guessed"])
			gained = max(20, round(40 + 60 * left) - order * 5)
			p.update(score=p["score"] + gained, guessed=True, gained=gained)
			drawer = self.players.get(self.drawer)
			if drawer:
				drawer["score"] += 20
				drawer["gained"] += 20
			room.notice(f"🎉 {p['name']} 님 정답! (+{gained})")
			if all(q["guessed"] for pid, q in self.players.items() if pid != self.drawer):
				self._reveal(room, now, "모두 맞혔어요!")
			return True, True
		if len(answer) >= 2 and _edit1(guess, answer):
			room.emit({"type": "close", "text": f"'{text}' 거의 맞았어요!"}, to=peer.pid)
		return False, False

	def on_message(self, room, peer, data):
		kind = data.get("type")
		now = time.time()
		is_host = peer.pid == self.host
		if kind == "draw":
			if peer.pid != self.drawer or self.status != "drawing":
				return False, None
			try:
				sid, w = int(data.get("id")), int(data.get("w"))
				pts = [[max(0, min(1000, int(x))), max(0, min(750, int(y)))] for x, y in (data.get("p") or [])[:200]]
			except (TypeError, ValueError):
				return False, None
			color = data.get("c")
			if color not in self.COLORS or w not in self.WIDTHS or not pts or self.points + len(pts) > self.MAX_POINTS:
				return False, None
			self.points += len(pts)
			if self.strokes and self.strokes[-1]["id"] == sid:
				self.strokes[-1]["p"].extend(pts)
			else:
				self.strokes.append({"id": sid, "c": color, "w": w, "p": pts})
			room.emit({"type": "draw", "id": sid, "c": color, "w": w, "p": pts}, exclude=peer.pid)
			return False, None
		if kind in ("undo", "clear"):
			if peer.pid != self.drawer or self.status != "drawing":
				return False, None
			if kind == "undo" and self.strokes:
				self.strokes.pop()
			elif kind == "clear":
				self.strokes = []
			room.emit({"type": kind}, exclude=peer.pid)
			return False, None
		if kind == "choose":
			if peer.pid != self.drawer or self.status != "choosing":
				return False, None
			try:
				word = self.options[int(data.get("i"))]
			except (TypeError, ValueError, IndexError):
				return False, None
			self._choose(room, now, word)
			return True, None
		if kind == "pass":  # 그리는 사람이 포기
			if peer.pid != self.drawer or self.status not in ("choosing", "drawing"):
				return False, None
			self._reveal(room, now, f"{peer.name} 님이 넘겼어요.")
			return True, None
		if kind == "settings":
			if not is_host or self.status not in ("lobby", "end"):
				return False, "방장만, 게임 시작 전에 바꿀 수 있어요."
			try:
				rounds, turn = int(data.get("rounds", self.rounds)), int(data.get("turn_time", self.turn_time))
			except (TypeError, ValueError):
				return False, None
			self.rounds = max(1, min(5, rounds))
			self.turn_time = turn if turn in self.TURN_CHOICES else self.turn_time
			return True, None
		if kind == "start":
			if not is_host:
				return False, "방장만 시작할 수 있어요."
			if self.status not in ("lobby", "end"):
				return False, None
			if len(self.players) < 2:
				return False, "두 명 이상 모여야 시작할 수 있어요."
			self._start(room, now)
			return True, None
		if kind == "skip" and is_host and self.status in ("choosing", "drawing"):
			self._reveal(room, now, "방장이 이번 차례를 넘겼어요.")
			return True, None
		return False, None

	def snapshot(self, room, pid=None):
		show_word = self.status in ("reveal", "end") or pid == self.drawer
		word = self.word if self.status != "reveal" else self.last_word
		mask = None
		if word and not show_word:
			mask = "".join(ch if (i in self.hints or ch.isspace()) else "○" for i, ch in enumerate(word))
		return {
			"status": self.status,
			"round": self.round,
			"rounds": self.rounds,
			"turn_time": self.turn_time,
			"left": max(0, round(self.deadline - time.time())) if self.status in ("choosing", "drawing", "reveal") else None,
			"word": word if show_word else None,
			"mask": mask,
			"options": self.options if pid == self.drawer and self.status == "choosing" else None,
			"drawer": self.players.get(self.drawer, {}).get("name"),
			"is_drawer": pid is not None and pid == self.drawer,
			"is_host": pid is not None and pid == self.host,
			"players": [{"name": self.players[q]["name"], "score": self.players[q]["score"], "guessed": self.players[q]["guessed"],
						 "gained": self.players[q]["gained"], "drawer": q == self.drawer, "host": q == self.host,
						 "online": q in room.peers, "me": q == pid} for q in self.order],
		}


LOGICS = {"omok": OmokLogic, "othello": OthelloLogic, "catchmind": CatchLogic}


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
	_events: list = field(default_factory=list)

	def notice(self, text):
		self._notices.append(text)

	def emit(self, data, to=None, exclude=None):
		"""상태와 따로 바로 보낼 메시지 (그림 선 등). to=pid 면 그 사람만, exclude=pid 면 그 사람 빼고."""
		self._events.append((data, to, exclude))

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
		self._ticker = asyncio.create_task(self._tick_loop())

	async def stop(self):
		if self._reaper:
			self._reaper.cancel()
		if getattr(self, "_ticker", None):
			self._ticker.cancel()
		for room_id in list(self.rooms):
			await self.close_room(room_id, "서버가 다시 시작돼 방이 닫혔어요.")

	async def _reap_loop(self):
		while True:
			await asyncio.sleep(5)
			await self.reap()

	async def _tick_loop(self):
		while True:
			await asyncio.sleep(1)
			await self.tick()

	async def tick(self, now=None):
		"""제한 시간이 있는 게임(그림 맞추기 등) 의 시간 진행."""
		now = now or time.time()
		for room in list(self.rooms.values()):
			tick = getattr(room.logic, "tick", None)
			if tick and tick(room, now):
				await self._flush(room, push=True)

	async def reap(self, now=None):
		now = now or time.time()
		for room in list(self.rooms.values()):
			# 끊긴 플레이어 자리 정리
			for pid, since in list(room.away.items()):
				if pid in room.peers:
					room.away.pop(pid, None)
				elif now - since >= self.seat_grace:
					room.away.pop(pid, None)
					msg = room.logic.on_leave(room, pid)
					if msg:
						room.notice(msg)
						await self._flush(room, push=True)
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
		await self._flush(room, push=True)

	async def _flush(self, room, push=False):
		"""쌓인 알림(채팅 줄)·이벤트를 보내고, push 면 각자에게 상태도 보냄."""
		notices, room._notices = room._notices, []
		for text in notices:
			item = {"type": "chat", "system": True, "text": text, "at": int(time.time())}
			room.chat = (room.chat + [item])[-CHAT_HISTORY:]
			await self._broadcast(room, item)
		events, room._events = room._events, []
		for data, to, exclude in events:
			targets = [room.peers.get(to)] if to else [p for pid, p in room.peers.items() if pid != exclude]
			await asyncio.gather(*(self._send(p, data) for p in targets if p))
		if not push:
			return
		peers = self._peer_list(room)
		# 사람마다 볼 수 있는 게 다를 수 있음 (그림 맞추기의 제시어 등) → 각자 따로
		await asyncio.gather(*(self._send(p, {"type": "state", "state": room.logic.snapshot(room, p.pid), "peers": peers, "you": room.logic.seat_of(p.pid)})
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
		room.logic.on_join(room, peer)
		await ws.send_json({"type": "hello", "room": room.info(with_token=False), "seat": room.logic.seat_of(pid), "chat": room.chat})
		if old is None:
			room.notice(f"{peer.name} 님이 들어왔어요.")
		await self._flush(room, push=True)

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
			on_chat = getattr(room.logic, "on_chat", None)
			if on_chat:  # 그림 맞추기: 정답이면 채팅 대신 '정답!' 으로
				handled, changed = on_chat(room, peer, text)
				await self._flush(room, push=changed)
				if handled:
					return
			item = {"type": "chat", "name": peer.name, "seat": room.logic.seat_of(peer.pid), "text": text, "at": int(now)}
			room.chat = (room.chat + [item])[-CHAT_HISTORY:]
			await self._broadcast(room, item)
			return
		changed, error = room.logic.on_message(room, peer, data)
		if error:
			await self._send(peer, {"type": "error", "text": error})
		await self._flush(room, push=changed)


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
