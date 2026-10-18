"""⚾ 1:1 숫자 야구 + 스킬.

규칙
- 둘 다 비밀 숫자(3자리 또는 4자리, 같은 숫자 없음, 0 가능)를 정하고 번갈아 맞힘
- 숫자와 자리가 맞으면 S(스트라이크), 숫자만 맞으면 B(볼), 하나도 없으면 OUT
- 선공이 먼저 다 맞히면 후공에게 마지막 기회 1번 (같은 횟수) → 둘 다 맞히면 무승부
- 한 턴 TURN_LIMIT 초 — 넘기면 그 턴은 그냥 지나감
- 스킬(켜면): 판마다 종류별로 1번, 한 턴에 하나, 쓰고도 추측은 그대로 함
"""

import itertools
import random
import time

TURN_LIMIT = 60
MAX_TURNS = 25          # 둘 다 이만큼 던지면 무승부 (바꿔치기로 끝없이 가는 걸 막음)
BOT_DELAY = 3.0          # 사람이 결과 연출을 읽을 시간
BOT_SKILL_DELAY = 3.8   # 컴퓨터가 스킬을 쓴 뒤엔 읽을 시간을 주고 추측
BOT_NAME = "🤖 컴퓨터"
# 컴퓨터 난이도: 쉬움 = 최근 결과 3개만 기억·스킬 없음 / 보통 = 다 기억·방패만 / 어려움 = 다 기억·스킬 모두
BOT_LEVELS = ("easy", "normal", "hard")
BOT_SKILLS = {"easy": set(), "normal": {"shield"}, "hard": None}
BOT_MEMORY = {"easy": 3, "normal": None, "hard": None}

# id: (아이콘, 이름, 설명, 상대에게 거는 방해인지 — 방패로 막힘)
SKILLS = {
	"scout": ("🔍", "정찰", "상대 숫자에 들어 있는 숫자 하나를 알려 줘요 (자리는 비밀)", True),
	"exclude": ("❌", "지우개", "상대 숫자에 없는 숫자 3개를 알려 줘요", True),
	"pos": ("🎯", "위치 탐지", "이번 턴 추측은 자리마다 S·B 를 따로 보여 줘요", False),
	"double": ("✌️", "더블 찬스", "이번 턴에 두 번 추측해요", False),
	"swap": ("🔀", "바꿔치기", "내 숫자 한 자리를 다른 숫자로 바꿔요 — 상대가 모은 결과가 헷갈려져요", False),
	"fog": ("🌫", "안개", "상대의 다음 추측 결과를 상대에게 가려요", True),
	"shield": ("🛡", "방패", "상대가 다음에 거는 방해 스킬(정찰·지우개·안개) 하나를 막아요", False),
}


def judge(secret, guess):
	s = sum(a == b for a, b in zip(secret, guess))
	b = len(set(secret) & set(guess)) - s
	return s, b


def marks(secret, guess):
	"""자리마다 'S' / 'B' / '-'."""
	return ["S" if g == secret[i] else "B" if g in secret else "-" for i, g in enumerate(guess)]


def valid_number(value, n):
	return isinstance(value, str) and len(value) == n and value.isdigit() and len(set(value)) == n


class BaseballLogic:
	kind = "baseball"
	SEATS = ("p1", "p2")

	def __init__(self, rng=None):
		self.rng = rng or random.Random()
		self.seats = {s: None for s in self.SEATS}
		self.names = {s: "" for s in self.SEATS}
		self.bots = set()
		self.wins = {s: 0 for s in self.SEATS}
		self.draws = 0
		self.digits = 3
		self.skills_on = True
		self.bot_level = "normal"
		self.starter = "p1"
		self.reset()

	def reset(self):
		self.status = "waiting"          # waiting / setup / playing / over
		self.secret = {s: None for s in self.SEATS}
		self.history = {s: [] for s in self.SEATS}   # s 가 던진 추측 (상대 숫자 기준) + 바꿔치기 표시
		self.turn = None
		self.first = None
		self.turn_started = 0.0
		self.turns = {s: 0 for s in self.SEATS}
		self.hit = {s: False for s in self.SEATS}
		self.used = {s: [] for s in self.SEATS}
		self.skill_this_turn = False
		self.pos_now = {s: False for s in self.SEATS}
		self.guesses_left = 1
		self.fog = {s: False for s in self.SEATS}    # s 의 다음 결과가 s 에게 가려짐
		self.shield = {s: False for s in self.SEATS}
		self.known = {s: {"in": [], "out": []} for s in self.SEATS}
		self.swaps = {s: 0 for s in self.SEATS}
		self.winner = None
		self.reason = ""
		self.bot_due = 0.0

	# ── 공통 ──
	def seat_of(self, pid):
		return next((s for s, p in self.seats.items() if p == pid and s not in self.bots), None)

	def other(self, s):
		return "p2" if s == "p1" else "p1"

	def _finish(self, room, winner, reason):
		self.status = "over"
		self.turn = None
		self.winner = winner
		self.reason = reason
		if winner:
			self.wins[winner] += 1
		else:
			self.draws += 1
		room.notice(f"🏁 {reason}")
		room.emit({"type": "over", "winner": winner, "reason": reason, "secret": self.secret})

	def _begin_play(self, room):
		self.status = "playing"
		self.first = self.starter
		self.starter = self.other(self.starter)
		self._start_turn(self.first)
		room.notice(f"⚾ 플레이볼! {self.names[self.first]} 님 선공. 상대 숫자 {self.digits}자리를 맞혀요.")

	def _start_turn(self, s):
		self.turn = s
		self.turn_started = time.time()
		self.skill_this_turn = False
		self.guesses_left = 1
		self.pos_now = {x: False for x in self.SEATS}
		if s in self.bots:
			self.bot_due = time.time() + BOT_DELAY

	def _end_turn(self, room):
		s, o = self.turn, self.other(self.turn)
		self.turns[s] += 1
		if self.hit[s]:
			if self.turns[o] < self.turns[s]:
				room.notice(f"🔥 {self.names[s]} 님이 다 맞혔어요! {self.names[o]} 님에게 마지막 기회!")
				room.emit({"type": "last-chance", "seat": o})
				self._start_turn(o)
				return
			if self.hit[o]:
				self._finish(room, None, "둘 다 맞혔어요. 무승부!")
			else:
				self._finish(room, s, f"{self.names[s]} 님이 {self.turns[s]}번 만에 맞혔어요! 🎉")
			return
		if self.hit[o]:  # 마지막 기회를 놓침
			self._finish(room, o, f"{self.names[o]} 님 승리! ({self.names[s]} 님이 마지막 기회를 놓쳤어요)")
			return
		if self.turns[s] >= MAX_TURNS and self.turns[o] >= MAX_TURNS:
			self._finish(room, None, f"{MAX_TURNS}번씩 던져도 아무도 못 맞혔어요. 무승부!")
			return
		self._start_turn(o)

	# ── 행동 (사람·컴퓨터 같이 씀) ──
	def _act_guess(self, room, s, value):
		if not valid_number(value, self.digits):
			return False, f"서로 다른 숫자 {self.digits}개를 넣어 주세요."
		o = self.other(s)
		sc, bc = judge(self.secret[o], value)
		entry = {"guess": value, "s": sc, "b": bc, "hidden": self.fog[s], "pos": marks(self.secret[o], value) if self.pos_now[s] else None}
		self.fog[s] = False
		self.history[s].append(entry)
		ev = {"type": "result", "seat": s, "guess": value, "s": sc, "b": bc, "n": self.digits, "pos": entry["pos"]}
		hide = entry["hidden"] and sc < self.digits
		if hide:  # 안개: 던진 사람에게만 결과를 가림 (다 맞힌 건 가리지 않음)
			entry["hidden"] = True
			room.emit(ev, exclude=self.seats[s])
			room.emit({**ev, "s": None, "b": None, "pos": None, "hidden": True}, to=self.seats[s])
		else:
			entry["hidden"] = False
			room.emit(ev)
		text = "가려짐 🌫" if hide else ("홈런! 다 맞혔어요" if sc == self.digits else "OUT" if sc + bc == 0 else f"{sc}S {bc}B")
		if not hide:
			room.notice(f"⚾ {self.names[s]}: {value} → {text}")
		else:
			room.notice(f"⚾ {self.names[s]}: {value} → 🌫 안개 속 결과")
		if sc == self.digits:
			self.hit[s] = True
			self._end_turn(room)
			return True, None
		self.guesses_left -= 1
		if self.guesses_left > 0:
			return True, None
		self._end_turn(room)
		return True, None

	def _act_skill(self, room, s, sid, data=None):
		if not self.skills_on:
			return False, "이 판은 스킬 없이 해요."
		if sid not in SKILLS:
			return False, None
		if sid in self.used[s]:
			return False, "이미 쓴 스킬이에요. (종류별로 한 판에 한 번)"
		if self.skill_this_turn:
			return False, "스킬은 한 턴에 하나만 써요."
		o = self.other(s)
		icon, name, _, hostile = SKILLS[sid]
		private = None
		if sid == "swap":
			try:
				i, d = int((data or {}).get("pos")), str((data or {}).get("digit"))
			except (TypeError, ValueError):
				return False, "바꿀 자리와 새 숫자를 골라 주세요."
			sec = self.secret[s]
			if not (0 <= i < self.digits) or not (len(d) == 1 and d.isdigit()) or d in sec:
				return False, "내 숫자에 없는 숫자로, 자리를 골라 바꿔요."
			self.secret[s] = sec[:i] + d + sec[i + 1:]
			self.swaps[s] += 1
			self.history[o].append({"swap": True})
		self.used[s].append(sid)
		self.skill_this_turn = True
		if hostile and self.shield[o]:
			self.shield[o] = False
			room.notice(f"🛡 {self.names[o]} 님의 방패가 {self.names[s]} 님의 {icon} {name} 을(를) 막았어요!")
			room.emit({"type": "skill", "seat": s, "id": sid, "icon": icon, "name": name, "blocked": True})
			return True, None
		if sid == "scout":
			pool = [d for d in self.secret[o] if d not in self.known[s]["in"]]
			if pool:
				d = self.rng.choice(pool)
				self.known[s]["in"].append(d)
				private = f"🔍 상대 숫자에 {d} 가 들어 있어요!"
			else:
				private = "🔍 이미 다 알고 있어요."
		elif sid == "exclude":
			pool = [d for d in "0123456789" if d not in self.secret[o] and d not in self.known[s]["out"]]
			got = sorted(self.rng.sample(pool, min(3, len(pool))))
			self.known[s]["out"] += got
			private = f"❌ 상대 숫자에 없는 숫자: {', '.join(got)}"
		elif sid == "pos":
			self.pos_now[s] = True
		elif sid == "double":
			self.guesses_left += 1
		elif sid == "fog":
			self.fog[o] = True
		elif sid == "shield":
			self.shield[s] = True
		room.notice(f"{icon} {self.names[s]} 님이 '{name}' 스킬을 썼어요!")
		room.emit({"type": "skill", "seat": s, "id": sid, "icon": icon, "name": name, "private": None})
		if private:
			room.emit({"type": "intel", "text": private}, to=self.seats[s])
		return True, None

	# ── 메시지 ──
	def on_message(self, room, peer, data):
		kind = data.get("type")
		seat = self.seat_of(peer.pid)
		busy = self.status in ("setup", "playing")
		if kind == "sit":
			if seat:
				return False, "이미 앉아 있어요."
			if busy:
				return False, "판이 진행 중이에요. 끝나면 앉을 수 있어요."
			free = [s for s in self.SEATS if not self.seats[s]]
			want = data.get("seat")
			target = want if want in free else (free[0] if free and want in (None, "any") else None)
			if not target:
				return False, "빈 자리가 없어요."
			self.seats[target], self.names[target] = peer.pid, peer.name
			room.notice(f"{peer.name} 님이 앉았어요.")
			return True, None
		if kind == "stand":
			if not seat or busy:
				return False, "판이 진행 중이에요. 그만하려면 기권하세요." if seat else None
			self.seats[seat], self.names[seat] = None, ""
			room.notice(f"{peer.name} 님이 자리에서 일어났어요.")
			return True, None
		if kind == "add-bot":
			free = [s for s in self.SEATS if not self.seats[s]]
			if not seat or busy or not free:
				return False, "먼저 자리에 앉으세요." if not seat else None
			s = free[0]
			self.seats[s], self.names[s] = f"bot:{s}", BOT_NAME
			self.bots.add(s)
			room.notice("🤖 컴퓨터가 들어왔어요.")
			return True, None
		if kind == "remove-bot":
			s = data.get("seat")
			if not seat or s not in self.bots or busy:
				return False, None
			self.bots.discard(s)
			self.seats[s], self.names[s] = None, ""
			return True, None
		if kind == "options":
			if not seat or busy:
				return False, None
			if data.get("digits") in (3, 4):
				self.digits = data["digits"]
			if isinstance(data.get("skills"), bool):
				self.skills_on = data["skills"]
			if data.get("bot_level") in BOT_LEVELS:
				self.bot_level = data["bot_level"]
			self.reset()
			return True, None
		if kind in ("start", "rematch"):
			if not seat or busy:
				return False, None
			if not all(self.seats.values()):
				return False, "상대가 있어야 시작해요. 컴퓨터를 넣어도 돼요."
			self.reset()
			self.status = "setup"
			for s in self.bots:
				self.secret[s] = "".join(self.rng.sample("0123456789", self.digits))
			room.notice(f"⚾ 각자 비밀 숫자 {self.digits}자리를 정하세요. (서로 다른 숫자, 0 도 돼요)")
			return True, None
		if kind == "secret":
			if self.status != "setup" or not seat:
				return False, None
			value = str(data.get("value") or "")
			if not valid_number(value, self.digits):
				return False, f"서로 다른 숫자 {self.digits}개로 정해 주세요."
			first_time = self.secret[seat] is None
			self.secret[seat] = value
			if first_time:
				room.notice(f"🔒 {peer.name} 님이 숫자를 정했어요.")
			if all(self.secret.values()):
				self._begin_play(room)
			return True, None
		if kind == "resign":
			if not busy or not seat:
				return False, None
			self._finish(room, self.other(seat), f"{self.names[seat]} 님이 기권했어요.")
			return True, None
		if kind in ("guess", "skill"):
			if self.status != "playing":
				return False, "아직 판이 시작되지 않았어요."
			if seat != self.turn:
				return False, "내 차례가 아니에요." if seat else "구경 중이에요."
			if kind == "guess":
				return self._act_guess(room, seat, str(data.get("value") or ""))
			return self._act_skill(room, seat, data.get("id"), data)
		return False, None

	def on_join(self, room, peer):
		seat = self.seat_of(peer.pid)
		if seat:
			self.names[seat] = peer.name

	def on_leave(self, room, pid):
		seat = self.seat_of(pid)
		if not seat:
			return None
		name = self.names[seat]
		if self.status in ("setup", "playing"):
			self._finish(room, self.other(seat), f"{name} 님이 나가서 판이 끝났어요.")
		self.seats[seat], self.names[seat] = None, ""
		return f"{name} 님의 자리가 비었어요."

	# ── 시간·컴퓨터 ──
	def tick(self, room, now):
		if self.status != "playing":
			return False
		if self.turn in self.bots:
			if now < self.bot_due:
				return False
			self.bot_act(room)
			return True
		if now - self.turn_started >= TURN_LIMIT:
			s = self.turn
			room.notice(f"⏰ {self.names[s]} 님 시간 초과! 이번 턴은 지나가요.")
			self._end_turn(room)
			return True
		return False

	def candidates(self, s, use_known=True, memory=None):
		"""s 가 아는 것만으로 남은 후보 (상대가 마지막으로 바꿔치기한 뒤의 결과만 믿음)."""
		entries = []
		for e in self.history[s]:
			if e.get("swap"):
				entries = []  # 바꾼 뒤부터 다시
			elif not e["hidden"]:
				entries.append(e)
		if memory:
			entries = entries[-memory:]
		ins, outs = (set(self.known[s]["in"]), set(self.known[s]["out"])) if use_known else (set(), set())
		res = []
		for p in itertools.permutations("0123456789", self.digits):
			c = "".join(p)
			if outs & set(c) or not ins <= set(c):
				continue
			if all(judge(c, e["guess"]) == (e["s"], e["b"]) and (e["pos"] is None or marks(c, e["guess"]) == e["pos"]) for e in entries):
				res.append(c)
		return res

	def bot_act(self, room):
		s, o = self.turn, self.other(self.turn)
		cands = self.candidates(s, memory=BOT_MEMORY[self.bot_level])
		if not cands:  # 바꿔치기로 정찰·지우개 정보가 틀어졌을 수 있음 → 결과만으로, 그래도 없으면 처음부터
			cands = self.candidates(s, use_known=False) or ["".join(p) for p in itertools.permutations("0123456789", self.digits)]
		if self.skills_on and not self.skill_this_turn:
			pick, extra = self._bot_skill(s, o, cands)
			if pick and self._act_skill(room, s, pick, extra)[0]:
				self.bot_due = time.time() + BOT_SKILL_DELAY
				return
		self._act_guess(room, s, self.rng.choice(cands))
		if self.status == "playing" and self.turn == s:  # 더블 찬스: 한 번 더
			self.bot_due = time.time() + BOT_DELAY

	def _bot_skill(self, s, o, cands):
		allowed = BOT_SKILLS[self.bot_level]
		free = [k for k in SKILLS if k not in self.used[s] and (allowed is None or k in allowed)]
		opp_close = any(not e.get("swap") and e["s"] >= self.digits - 1 for e in self.history[o][-2:])
		if "swap" in free and opp_close:  # 상대가 거의 다 맞혔으면 한 자리 바꿔치기
			i = self.rng.randrange(self.digits)
			d = self.rng.choice([x for x in "0123456789" if x not in self.secret[s]])
			return "swap", {"pos": i, "digit": d}
		if "fog" in free and opp_close:
			return "fog", None
		if "double" in free and 2 <= len(cands) <= 6:
			return "double", None
		if "exclude" in free and self.turns[s] == 0:
			return "exclude", None
		if "scout" in free and self.turns[s] == 1:
			return "scout", None
		if "shield" in free and self.turns[s] == 2:
			return "shield", None
		if "pos" in free and len(cands) > 12 and self.turns[s] >= 2:
			return "pos", None
		return None, None

	# ── 보여 주기 ──
	def snapshot(self, room, pid=None):
		me = next((s for s, p in self.seats.items() if p == pid), None)
		over = self.status == "over"

		def view(s):
			out = []
			for e in self.history[s]:
				if e.get("swap"):
					out.append({"swap": True})
				elif e["hidden"] and me == s and not over:
					out.append({"guess": e["guess"], "s": None, "b": None, "pos": None, "hidden": True})
				else:
					out.append({**e, "pos": e["pos"] if (me in (s, self.other(s)) or over) else None})
			return out

		return {
			"status": self.status, "digits": self.digits, "skills_on": self.skills_on,
			"turn": self.turn, "first": self.first, "bot_level": self.bot_level, "winner": self.winner, "reason": self.reason,
			"elapsed": round(time.time() - self.turn_started, 2) if self.turn else None, "turn_limit": TURN_LIMIT,
			"guesses_left": self.guesses_left if self.turn == me else None,
			"skill_this_turn": self.skill_this_turn,
			"last_chance": bool(self.turn and self.hit[self.other(self.turn)]),
			"my_secret": self.secret[me] if me else None,
			"secrets": self.secret if over else None,
			"ready": {s: self.secret[s] is not None for s in self.SEATS},
			"history": {s: view(s) for s in self.SEATS},
			"turns": self.turns,
			"used": self.used,
			"known": self.known[me] if me else None,
			"pos_now": bool(me and self.pos_now[me]), "my_shield": bool(me and self.shield[me]),
			"fogged": bool(me and self.fog[me]),
			"skills": [{"id": k, "icon": v[0], "name": v[1], "desc": v[2]} for k, v in SKILLS.items()],
			"draws": self.draws,
			"seats": {s: ({"name": self.names[s], "bot": s in self.bots, "online": s in self.bots or p in room.peers, "wins": self.wins[s]} if p else None)
					  for s, p in self.seats.items()},
		}
