"""🥤 1:1 야바위 — 사기꾼(섞는 사람) 대 맞히는 사람, 라운드마다 역할을 바꿈.

규칙
- 컵 3~5개 중 하나에 구슬. 사기꾼이 구슬을 넣을 컵을 고르면(놓기) 그 자리를 모두에게 잠깐 보여 주고(보여 주기 SHOW_TIME 초)
  → 컵 두 개씩 골라 섞음(섞기). 섞기엔 '힘' POWER 이 있고 속도가 셋: 보통 1·빠르게 2·번개 3. 시간 SHUFFLE_TIME 안에, 최소 MIN_SWAPS 번
- 맞히는 사람은 처음 자리부터 섞는 걸 실시간으로 눈으로 따라가고(빠를수록 애니메이션이 짧음) 다 끝나면 컵 하나를 고름(GUESS_TIME 초)
  섞는 동안 판돈을 1→2 로 올릴 수 있음(더블). 맞히면 맞히는 사람 +판돈, 틀리면 사기꾼 +판돈
- 라운드 수만큼 번갈아 사기꾼을 하고 점수가 높은 쪽이 승리
- 스킬(켜면, 판마다 종류별 1번): 사기꾼 — ✨ 얍! 텔레포트(구슬을 다른 컵으로 순간 이동, 상대는 '얍!' 만 봄)·🌫 연막(다음 섞기를 가림)
  ·⚡ 가속(힘 +8)·🌀 회오리(힘 안 쓰고 번개 속도로 3번 저절로 섞임)
  맞히는 사람 — 🔍 돋보기(빈 컵 하나 공개)·⏪ 되감기(마지막 3번 섞기를 천천히 다시 — 연막도 보임)·✌️ 두 개 고르기(두 컵, 맞히면 +1 만)
  둘 다 — 🛡 방패(상대의 다음 방해·염탐 스킬 하나를 막음)

섞은 뒤의 구슬 위치는 서버만 알고 사기꾼에게만 보냄. 연막 섞기는 맞히는 사람에게 어느 컵인지 안 알려 줌.
"""

import random
import time

CUPS = (3, 4, 5)
ROUNDS = (4, 6, 8)
POWER = 20
MIN_SWAPS = 3
PLACE_TIME = 10
SHOW_TIME = 1.8          # 구슬을 넣은 자리를 모두에게 보여 주는 시간
SHUFFLE_TIME = 25
GUESS_TIME = 12
REVEAL_TIME = 3.2
SWAP_LEN = (0.6, 0.32, 0.18)   # 섞기 애니메이션(초): 보통·빠르게·번개 — 브라우저는 snapshot 의 swap_lens 를 씀
SWAP_COST = (1, 2, 3)          # 속도별로 드는 힘
TURBO_POWER = 8
WHIRL_SWAPS = 3
BOT_NAME = "🤖 컴퓨터"
BOT_LEVELS = ("easy", "normal", "hard")
BOT_SKILLS = {"easy": set(), "normal": {"turbo", "shield", "lens", "whirl"}, "hard": None}

# id: (아이콘, 이름, 설명, 쓸 수 있는 역할, 상대에게 거는 것인지 — 방패로 막힘)
SKILLS = {
	"teleport": ("✨", "얍! 텔레포트", "구슬을 다른 컵으로 순간 이동 — 상대는 '얍!' 만 보고 어디로 갔는지는 몰라요", "dealer", True),
	"smoke": ("🌫", "연막", "다음 섞기를 연막으로 가려요 — 상대는 어느 컵끼리 바뀌었는지 못 봐요", "dealer", True),
	"turbo": ("⚡", "가속", "이번 라운드 힘이 +8 — 더 많이, 더 빨리 섞어요", "dealer", False),
	"whirl": ("🌀", "회오리", "힘을 안 쓰고 번개 속도로 3번 저절로 섞여요", "dealer", False),
	"lens": ("🔍", "돋보기", "구슬이 없는 컵 하나를 알려 줘요", "guesser", True),
	"rewind": ("⏪", "되감기", "마지막 3번 섞기를 천천히 다시 봐요 — 연막 속 섞기도 보여요", "guesser", True),
	"double": ("✌️", "두 개 고르기", "컵 두 개를 골라요. 맞히면 판돈과 상관없이 +1", "guesser", False),
	"shield": ("🛡", "방패", "상대가 다음에 거는 스킬(텔레포트·연막·돋보기·되감기) 하나를 막아요", "both", False),
}


class ShellLogic:
	kind = "shell"
	SEATS = ("p1", "p2")

	def __init__(self, rng=None):
		self.rng = rng or random.Random()
		self.seats = {s: None for s in self.SEATS}
		self.names = {s: "" for s in self.SEATS}
		self.bots = set()
		self.wins = {s: 0 for s in self.SEATS}
		self.draws = 0
		self.skills_on = True
		self.cups = 3
		self.rounds = 6
		self.bot_level = "normal"
		self.starter = "p1"
		self.reset()

	def reset(self):
		self.status = "waiting"      # waiting / playing / over
		self.first = self.starter    # 1라운드 사기꾼
		self.phase = None            # place / show / shuffle / guess / reveal
		self.phase_until = 0.0
		self.round = 0
		self.dealer = None
		self.ball = None
		self.score = {s: 0 for s in self.SEATS}
		self.used = {s: [] for s in self.SEATS}
		self.shield = {s: False for s in self.SEATS}
		self.power = POWER
		self.swaps = []              # 이번 라운드 섞기 [(a, b, speed, smoked)]
		self.busy_until = 0.0        # 보낸 섞기 애니메이션이 다 끝나는 때
		self.smoke_armed = False
		self.bet = 1
		self.double = False
		self.picks = []
		self.lens = None             # 돋보기로 공개한 빈 컵
		self.result = None           # reveal 때 {ball, picks, hit, points}
		self.winner = None
		self.reason = ""
		self.bot_due = 0.0
		self.bot_belief = None       # 컴퓨터가 생각하는 구슬 위치
		self.bot_plan = 0            # 컴퓨터 사기꾼이 섞을 횟수

	# ── 공통 ──
	def seat_of(self, pid):
		return next((s for s, p in self.seats.items() if p == pid and s not in self.bots), None)

	def other(self, s):
		return "p2" if s == "p1" else "p1"

	@property
	def guesser(self):
		return self.other(self.dealer) if self.dealer else None

	def role(self, s):
		return "dealer" if s == self.dealer else "guesser" if s == self.guesser else None

	def _emit_to(self, room, s, data):
		if s not in self.bots and self.seats[s]:
			room.emit(data, to=self.seats[s])

	def _finish(self, room, winner, reason):
		self.status = "over"
		self.phase = None
		self.winner = winner
		self.reason = reason
		if winner:
			self.wins[winner] += 1
		else:
			self.draws += 1
		room.notice(f"🏁 {reason}")
		room.emit({"type": "over", "winner": winner, "reason": reason})

	# ── 라운드 ──
	def _start_round(self, room, now):
		self.round += 1
		self.dealer = self.first if self.round % 2 == 1 else self.other(self.first)
		self.phase, self.phase_until = "place", now + PLACE_TIME
		self.ball = None
		self.power = POWER
		self.swaps = []
		self.busy_until = 0.0
		self.smoke_armed = False
		self.bet = 1
		self.double = False
		self.picks = []
		self.lens = None
		self.result = None
		self.bot_due = now + self.rng.uniform(0.8, 1.6)
		room.emit({"type": "round", "round": self.round, "dealer": self.dealer})
		room.notice(f"🎲 {self.round}라운드 — {self.names[self.dealer]} 님이 사기꾼! 구슬을 넣을 컵을 고르세요.")

	def _place(self, room, cup, now):
		self.ball = cup
		self.phase, self.phase_until = "show", now + SHOW_TIME   # 처음 자리는 모두에게 보여 줌 — 그 뒤 섞기부터가 승부
		self._emit_to(room, self.dealer, {"type": "ball", "cup": cup})
		room.emit({"type": "placed", "cup": cup})
		if self.dealer in self.bots:
			self.bot_plan = {"easy": 6, "normal": 10, "hard": 99}[self.bot_level]
			self.bot_due = now + SHOW_TIME + 0.6
		if self.guesser in self.bots:
			self.bot_belief = cup
			g = self.guesser
			allowed = BOT_SKILLS[self.bot_level]
			if self.skills_on and "shield" not in self.used[g] and (allowed is None or "shield" in allowed) and self.rng.random() < 0.4:
				self._act_skill(room, g, "shield", {}, now)
			if self.bot_level == "hard" and self.rng.random() < 0.3:
				self.bet = 2
				room.emit({"type": "bet", "bet": 2})
		return True, None

	def _swap(self, room, a, b, speed, now, free=False):
		cost = 0 if free else SWAP_COST[speed]
		if self.power < cost:
			return False, "힘이 모자라요. 더 느린 속도로 섞거나 '다 섞었어요'를 누르세요."
		self.power -= cost
		self.busy_until = max(now, self.busy_until) + SWAP_LEN[speed]
		if self.ball == a:
			self.ball = b
		elif self.ball == b:
			self.ball = a
		smoked = self.smoke_armed
		self.smoke_armed = False
		self.swaps.append((a, b, speed, smoked))
		g = self.guesser
		ev = {"type": "swap", "a": a, "b": b, "speed": speed, "n": len(self.swaps), "power": self.power}
		if smoked:
			# 맞히는 사람(과 구경꾼)에겐 어느 컵인지 가림
			for pid in room.peers:
				if pid == self.seats[self.dealer]:
					room.emit({**ev, "smoke": True}, to=pid)
				else:
					room.emit({**ev, "a": None, "b": None, "smoke": True}, to=pid)
		else:
			room.emit(ev)
		if g in self.bots:
			self._bot_watch(a, b, speed, smoked)
		return True, None

	def _begin_guess(self, room, now):
		start = max(now, self.busy_until)   # 아직 화면에서 섞이는 중이면 그만큼 고를 시간을 더 줌
		self.phase, self.phase_until = "guess", start + GUESS_TIME
		room.emit({"type": "guess-start", "swaps": len(self.swaps)})
		if self.guesser in self.bots:
			self.bot_due = start + self.rng.uniform(1.2, 2.2)

	def _reveal(self, room, picks, now):
		hit = self.ball in picks
		g, d = self.guesser, self.dealer
		points = (1 if self.double else self.bet) if hit else self.bet
		if hit:
			self.score[g] += points
		else:
			self.score[d] += points
		self.picks = picks
		self.result = {"ball": self.ball, "picks": picks, "hit": hit, "points": points, "winner": g if hit else d}
		self.phase, self.phase_until = "reveal", now + REVEAL_TIME
		room.emit({"type": "reveal", **self.result, "swaps": [list(s) for s in self.swaps]})
		room.notice(f"{'🎯 ' + self.names[g] + ' 님이 맞혔어요!' if hit else '😈 ' + self.names[d] + ' 님이 속였어요!'} (+{points})")

	def _next(self, room, now):
		if self.round >= self.rounds:
			a, b = self.score["p1"], self.score["p2"]
			if a == b:
				self._finish(room, None, f"{a} : {b} 무승부!")
			else:
				w = "p1" if a > b else "p2"
				self._finish(room, w, f"{self.names[w]} 님 승리! {max(a, b)} : {min(a, b)}")
			return
		self._start_round(room, now)

	# ── 스킬 ──
	def _act_skill(self, room, s, sid, data, now):
		if not self.skills_on:
			return False, "이 판은 스킬 없이 해요."
		if sid not in SKILLS:
			return False, "모르는 스킬이에요."
		if sid in self.used[s]:
			return False, "이미 쓴 스킬이에요."
		icon, name, _, who, hostile = SKILLS[sid]
		role = self.role(s)
		if who != "both" and who != role:
			return False, f"{'사기꾼' if who == 'dealer' else '맞히는 사람'}일 때 쓰는 스킬이에요."
		if sid in ("teleport", "smoke", "turbo", "whirl") and self.phase != "shuffle":
			return False, "섞는 동안 쓸 수 있어요."
		if sid in ("lens", "rewind") and self.phase != "guess":
			return False, "고를 차례에 쓸 수 있어요."
		if sid == "double" and self.phase not in ("shuffle", "guess"):
			return False, "섞는 동안이나 고를 때 쓸 수 있어요."
		o = self.other(s)
		extra = {}
		if sid == "teleport":
			try:
				to = int(data.get("cup"))
			except (TypeError, ValueError):
				return False, "옮길 컵을 골라 주세요."
			if to == self.ball or not 0 <= to < self.cups:
				return False, "구슬이 없는 다른 컵을 골라 주세요."
		self.used[s].append(sid)
		blocked = False
		if hostile and self.shield[o]:
			self.shield[o] = False
			blocked = True
		elif sid == "teleport":
			old, self.ball = self.ball, to
			self._emit_to(room, self.dealer, {"type": "ball", "cup": to})
			if self.guesser in self.bots and self.bot_belief == old:   # 따라오고 있었다면 '거기엔 없다'는 것만 앎
				self.bot_belief = self.rng.choice([c for c in range(self.cups) if c != old])
		elif sid == "smoke":
			self.smoke_armed = True
		elif sid == "turbo":
			self.power += TURBO_POWER
		elif sid == "shield":
			self.shield[s] = True
		elif sid == "lens":
			empties = [c for c in range(self.cups) if c != self.ball]
			self.lens = self.rng.choice(empties)
			extra = {"lens": self.lens}
			self._emit_to(room, s, {"type": "lens", "cup": self.lens})
		elif sid == "rewind":
			extra = {"swaps": [list(x) for x in self.swaps[-3:]]}
			self._emit_to(room, s, {"type": "rewind", "swaps": extra["swaps"]})
		elif sid == "double":
			self.double = True
		room.emit({"type": "skill", "seat": s, "id": sid, "icon": icon, "name": name, "blocked": blocked, "secret": sid == "smoke" and not blocked})
		room.notice(f"{icon} {self.names[s]} 님의 {name}!" + (" 🛡 방패에 막혔어요." if blocked else ""))
		if sid == "whirl":   # 알림 뒤에 섞기가 보이게
			for _ in range(WHIRL_SWAPS):
				a, b = self.rng.sample(range(self.cups), 2)
				if self.ball not in (a, b) and self.rng.random() < 0.6:
					a = self.ball
				self._swap(room, a, b, 2, now, free=True)
		return True, None

	# ── 메시지 ──
	def on_message(self, room, peer, data):
		kind = data.get("type")
		seat = self.seat_of(peer.pid)
		busy = self.status == "playing"
		now = time.time()
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
			if isinstance(data.get("skills"), bool):
				self.skills_on = data["skills"]
			if data.get("cups") in CUPS:
				self.cups = data["cups"]
			if data.get("rounds") in ROUNDS:
				self.rounds = data["rounds"]
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
			self.status = "playing"
			self._start_round(room, now)
			self.starter = self.other(self.starter)
			return True, None
		if kind == "resign":
			if not busy or not seat:
				return False, None
			self._finish(room, self.other(seat), f"{self.names[seat]} 님이 기권했어요.")
			return True, None
		if kind in ("place", "swap", "done", "bet", "pick", "skill"):
			if self.status != "playing":
				return False, "아직 판이 시작되지 않았어요."
			if not seat:
				return False, "구경 중이에요."
			role = self.role(seat)
			if kind == "place":
				if role != "dealer" or self.phase != "place":
					return False, "지금은 구슬을 놓을 때가 아니에요."
				try:
					cup = int(data.get("cup"))
				except (TypeError, ValueError):
					return False, "컵을 골라 주세요."
				if not 0 <= cup < self.cups:
					return False, "컵을 골라 주세요."
				return self._place(room, cup, now)
			if kind == "swap":
				if role != "dealer" or self.phase != "shuffle":
					return False, "지금은 섞을 때가 아니에요."
				try:
					a, b = int(data.get("a")), int(data.get("b"))
				except (TypeError, ValueError):
					return False, "컵 두 개를 골라 주세요."
				if a == b or not (0 <= a < self.cups and 0 <= b < self.cups):
					return False, "서로 다른 컵 두 개를 골라 주세요."
				speed = data.get("speed")
				if speed not in (0, 1, 2):
					speed = 1 if data.get("fast") else 0
				return self._swap(room, a, b, speed, now)
			if kind == "done":
				if role != "dealer" or self.phase != "shuffle":
					return False, None
				if len(self.swaps) < MIN_SWAPS:
					return False, f"적어도 {MIN_SWAPS}번은 섞어야 해요."
				self._begin_guess(room, now)
				return True, None
			if kind == "bet":
				if role != "guesser" or self.phase not in ("shuffle", "guess"):
					return False, "섞는 동안이나 고를 때 판돈을 올릴 수 있어요."
				if data.get("bet") not in (1, 2):
					return False, None
				self.bet = data["bet"]
				room.emit({"type": "bet", "bet": self.bet})
				return True, None
			if kind == "pick":
				if role != "guesser" or self.phase != "guess":
					return False, "지금은 고를 때가 아니에요."
				cups = data.get("cups") if isinstance(data.get("cups"), list) else [data.get("cup")]
				try:
					picks = sorted({int(c) for c in cups})
				except (TypeError, ValueError):
					return False, "컵을 골라 주세요."
				if not picks or not all(0 <= c < self.cups for c in picks):
					return False, "컵을 골라 주세요."
				if len(picks) > (2 if self.double else 1):
					return False, "컵은 하나만 고를 수 있어요." if not self.double else "두 개까지 고를 수 있어요."
				self._reveal(room, picks, now)
				return True, None
			return self._act_skill(room, seat, data.get("id"), data, now)
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
		if self.status == "playing":
			self._finish(room, self.other(seat), f"{name} 님이 나가서 판이 끝났어요.")
		self.seats[seat], self.names[seat] = None, ""
		return f"{name} 님의 자리가 비었어요."

	# ── 시간·컴퓨터 ──
	def tick(self, room, now):
		if self.status != "playing":
			return False
		if self.phase == "reveal":
			if now >= self.phase_until:
				self._next(room, now)
				return True
			return False
		if now >= self.phase_until:
			if self.phase == "show":
				self.phase, self.phase_until = "shuffle", now + SHUFFLE_TIME
			elif self.phase == "place":
				room.notice("⏰ 시간 초과 — 구슬은 아무 컵에나 들어갔어요.")
				self._place(room, self.rng.randrange(self.cups), now)
			elif self.phase == "shuffle":
				self.power = max(self.power, MIN_SWAPS - len(self.swaps))   # 힘이 모자라도 서버가 채울 만큼은
				while len(self.swaps) < MIN_SWAPS:   # 너무 조금 섞었으면 서버가 채움
					a, b = self.rng.sample(range(self.cups), 2)
					self._swap(room, a, b, 0, now)
				self._begin_guess(room, now)
			elif self.phase == "guess":
				room.notice("⏰ 시간 초과 — 고르지 못했어요.")
				self._reveal(room, [], now)
			return True
		active = self.dealer if self.phase in ("place", "shuffle") else self.guesser
		if active in self.bots and now >= self.bot_due:
			return self._bot_act(room, active, now)
		return False

	def _bot_watch(self, a, b, speed, smoked):
		"""컴퓨터 맞히는 사람이 섞기를 눈으로 따라감 — 빠를수록 자주 놓침."""
		lose = {"easy": (0.12, 0.3, 0.5), "normal": (0.05, 0.15, 0.3), "hard": (0.02, 0.07, 0.15)}[self.bot_level][speed]
		if smoked:
			lose = 0.5 if self.bot_level == "hard" else 0.75
		if self.bot_belief in (a, b):
			if self.rng.random() < lose:
				self.bot_belief = self.rng.randrange(self.cups)
			else:
				self.bot_belief = b if self.bot_belief == a else a
		elif smoked and self.rng.random() < lose / 2:
			self.bot_belief = self.rng.randrange(self.cups)

	def _bot_act(self, room, s, now):
		level, role, o = self.bot_level, self.role(s), self.other(s)
		allowed = BOT_SKILLS[level]
		can = lambda sid: self.skills_on and sid not in self.used[s] and (allowed is None or sid in allowed)
		if role == "dealer":
			if self.phase == "place":
				self._place(room, self.rng.randrange(self.cups), now)
				return True
			if self.phase == "shuffle":
				if can("turbo") and self.rng.random() < 0.3:
					self._act_skill(room, s, "turbo", {}, now)
				if can("shield") and self.rng.random() < 0.3:
					self._act_skill(room, s, "shield", {}, now)
				if can("smoke") and self.power >= 2 and self.rng.random() < 0.35:
					self._act_skill(room, s, "smoke", {}, now)
				if can("teleport") and len(self.swaps) >= 4 and self.rng.random() < 0.25:
					self._act_skill(room, s, "teleport", {"cup": self.rng.choice([c for c in range(self.cups) if c != self.ball])}, now)
				if can("whirl") and len(self.swaps) >= 2 and self.rng.random() < 0.25:
					self._act_skill(room, s, "whirl", {}, now)
					self.bot_due = self.busy_until + 0.2
					return True
				r = self.rng.random()
				speed = {"easy": 0, "normal": 2 if r < 0.15 else 1 if r < 0.5 else 0, "hard": 2 if r < 0.5 else 1 if r < 0.85 else 0}[level]
				while speed and self.power < SWAP_COST[speed]:
					speed -= 1
				cost = SWAP_COST[speed]
				if self.power < cost or len(self.swaps) >= self.bot_plan:
					if len(self.swaps) >= MIN_SWAPS:
						self._begin_guess(room, now)
					else:
						a, b = self.rng.sample(range(self.cups), 2)
						self._swap(room, a, b, 0, now)
						self.bot_due = now + 0.9
					return True
				a, b = self.rng.sample(range(self.cups), 2)
				if self.rng.random() < 0.6 and self.ball not in (a, b):   # 구슬이 든 컵을 자주 움직임
					a = self.ball
				self._swap(room, a, b, speed, now)
				self.bot_due = now + SWAP_LEN[speed] + self.rng.uniform(0.05, 0.3)
				return True
			return False
		# 맞히는 사람
		if self.phase == "guess":
			if can("lens") and self.rng.random() < 0.5:
				self._act_skill(room, s, "lens", {}, now)
				if self.lens is not None and self.bot_belief == self.lens:
					self.bot_belief = self.rng.choice([c for c in range(self.cups) if c != self.lens])
			if can("rewind") and level == "hard" and any(sw[3] for sw in self.swaps[-3:]) and self.rng.random() < 0.7:
				self._act_skill(room, s, "rewind", {}, now)
				self.bot_belief = self.ball if self.rng.random() < 0.8 else self.bot_belief
			picks = [self.bot_belief if self.bot_belief is not None else self.rng.randrange(self.cups)]
			if can("double") and level == "hard" and self.rng.random() < 0.3:
				self._act_skill(room, s, "double", {}, now)
				picks.append(self.rng.choice([c for c in range(self.cups) if c != picks[0]]))
			self._reveal(room, sorted(set(picks)), now)
			return True
		return False

	# ── 보기 ──
	def snapshot(self, room, pid=None):
		me = next((s for s, p in self.seats.items() if p == pid), None)
		now = time.time()
		show_ball = self.phase in ("show", "reveal") or self.status == "over" or (me and me == self.dealer)
		return {
			"status": self.status, "phase": self.phase, "round": self.round, "rounds": self.rounds, "cups": self.cups,
			"skills_on": self.skills_on, "bot_level": self.bot_level,
			"dealer": self.dealer, "ball": self.ball if show_ball else None,
			"left": round(max(0.0, self.phase_until - now), 2) if self.phase else None,
			"phase_time": {"place": PLACE_TIME, "show": SHOW_TIME, "shuffle": SHUFFLE_TIME, "guess": GUESS_TIME, "reveal": REVEAL_TIME}.get(self.phase),
			"power": self.power, "power_max": POWER, "swaps": len(self.swaps), "min_swaps": MIN_SWAPS, "bet": self.bet, "double": self.double,
			"lens": self.lens if me == self.guesser or self.phase == "reveal" else None,
			"smoke_armed": self.smoke_armed if me == self.dealer else False,
			"result": self.result, "score": self.score, "used": self.used,
			"my_shield": bool(me and self.shield[me]),
			"winner": self.winner, "reason": self.reason, "draws": self.draws,
			"skills": [{"id": k, "icon": v[0], "name": v[1], "desc": v[2], "who": v[3]} for k, v in SKILLS.items()],
			"swap_lens": list(SWAP_LEN), "swap_costs": list(SWAP_COST),
			"seats": {s: ({"name": self.names[s], "bot": s in self.bots, "online": s in self.bots or p in room.peers, "wins": self.wins[s]} if p else None)
					  for s, p in self.seats.items()},
		}
