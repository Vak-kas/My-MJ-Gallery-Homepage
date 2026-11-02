"""🎣 1:1 낚시 대결 + 방해 스킬.

규칙
- 같은 연못에서 제한 시간(60·90·120초) 동안 동시에 낚시. 끝났을 때 잡은 물고기 총 무게(또는 가장 큰 한 마리)가 많은 쪽이 승리
- 자리 3곳(얕은 물·수초·깊은 물) 중 하나에 던지면 잠시 뒤 입질 — 그 순간 챔질(여유 시간은 물고기마다 다름).
  너무 빠르거나 늦으면 도망. 걸리면 당기기: 당길수록 진행이 차고 줄 긴장도 올라감(가만히 있으면 내려감),
  긴장이 1을 넘으면 줄이 끊어짐. 물고기가 발버둥칠 땐 긴장이 확 오르니 멈췄다 당겨야 함
- 시간이 끝났을 때 누가 당기는 중이면 최대 OVERTIME 초까지 기다려 줌(그동안 새로 던지기는 안 됨)
- 스킬(켜면): 판마다 종류별로 1번

서버가 입질 시각·물고기·긴장을 모두 들고 있고, 클라이언트는 긴장 감소만 똑같은 공식으로 미리 그림.
틱은 0.25초(mj_game GameHub) — 입질 알림이 최대 그만큼 늦게 가지만 챔질 여유는 알림을 보낸 시각부터 재므로 공평함.
"""

import random
import time

DURATIONS = (60, 90, 120)
MODES = {"total": "총 무게", "biggest": "가장 큰 한 마리"}
OVERTIME = 10
DECAY = 0.5          # 초당 줄어드는 긴장
PULL_T = 0.2         # 한 번 당길 때 오르는 긴장
PULL_T_SURGE = 0.42  # 발버둥 중에 당기면
SURGE_LEN = 1.1
PULL_GAP = 0.08      # 이보다 빠른 연타는 무시 (자동 클릭 방지)
BOT_NAME = "🤖 컴퓨터"
BOT_LEVELS = ("easy", "normal", "hard")
BOT_SKILLS = {"easy": set(), "normal": {"bait", "glove", "shield"}, "hard": None}

# id: (이름, 입질까지 걸리는 시간 범위)
SPOTS = {
	"shallow": ("얕은 물", (1.5, 4.0)),
	"weeds": ("수초", (2.5, 6.0)),
	"deep": ("깊은 물", (3.5, 8.0)),
}
# id: (이모지, 이름, 최소 kg, 최대 kg, 기본 당김 횟수, 발버둥 세기, 챔질 여유 초)
FISH = {
	"boot": ("🥾", "장화", 0, 0, 2, 0.0, 1.4),
	"can": ("🥫", "깡통", 0, 0, 2, 0.0, 1.4),
	"weed": ("🌿", "수초 뭉치", 0, 0, 3, 0.0, 1.4),
	"minnow": ("🐟", "피라미", 0.05, 0.3, 4, 0.1, 1.3),
	"crucian": ("🐠", "붕어", 0.2, 1.2, 6, 0.18, 1.1),
	"trout": ("🐡", "송어", 0.5, 2.5, 8, 0.25, 1.0),
	"turtle": ("🐢", "자라", 1.0, 5.0, 9, 0.2, 1.2),
	"carp": ("🎏", "잉어", 1.0, 7.0, 11, 0.32, 0.9),
	"catfish": ("🐋", "메기", 2.0, 12.0, 14, 0.4, 0.8),
	"snakehead": ("🦈", "가물치", 3.0, 15.0, 16, 0.45, 0.75),
	"sturgeon": ("🐉", "철갑상어", 10.0, 40.0, 22, 0.55, 0.65),
	"golden": ("✨", "황금 잉어", 5.0, 9.0, 12, 0.35, 0.7),
}
JUNK = {"boot", "can", "weed"}
# 자리별 확률 가중치
TABLE = {
	"shallow": [("boot", 6), ("can", 5), ("minnow", 40), ("crucian", 33), ("trout", 12), ("carp", 4)],
	"weeds": [("weed", 8), ("boot", 4), ("minnow", 14), ("crucian", 28), ("trout", 20), ("turtle", 8), ("carp", 13), ("catfish", 4), ("golden", 1)],
	"deep": [("can", 7), ("boot", 6), ("crucian", 10), ("trout", 19), ("carp", 25), ("catfish", 18), ("snakehead", 11), ("sturgeon", 3), ("golden", 1)],
}

# id: (아이콘, 이름, 설명, 상대에게 거는 방해인지 — 방패로 막힘)
SKILLS = {
	"bait": ("🪱", "특제 미끼", "다음 입질이 빨리 오고, 그 자리에서 큰 물고기가 물어요", False),
	"glove": ("🧤", "낚시 장갑", "다음에 걸린 물고기는 아무리 세게 당겨도 줄이 안 끊어져요", False),
	"rock": ("🪨", "돌 던지기", "상대 찌 옆에 돌을 던져요 — 기다리던 물고기는 도망가고, 당기는 중이면 줄 긴장이 확 올라요", True),
	"fake": ("🫧", "가짜 입질", "상대 찌를 몰래 두 번 흔들어요 — 속아서 챔질하면 물고기가 도망가요", True),
	"shield": ("🛡", "방패", "상대가 다음에 거는 방해 스킬(돌·가짜 입질) 하나를 막아요", False),
}


def size_hint(kg):
	if kg <= 0:
		return "뭔가 무겁기만 한 게…"
	if kg < 1:
		return "작은 녀석"
	if kg < 4:
		return "제법 묵직!"
	if kg < 10:
		return "큰 놈이다!"
	return "엄청난 거물!!"


class FishingLogic:
	kind = "fishing"
	SEATS = ("p1", "p2")

	def __init__(self, rng=None):
		self.rng = rng or random.Random()
		self.seats = {s: None for s in self.SEATS}
		self.names = {s: "" for s in self.SEATS}
		self.bots = set()
		self.wins = {s: 0 for s in self.SEATS}
		self.draws = 0
		self.skills_on = True
		self.duration = 90
		self.mode = "total"
		self.bot_level = "normal"
		self.reset()

	def reset(self):
		self.status = "waiting"          # waiting / playing / over
		self.started_at = 0.0
		self.ends_at = 0.0
		self.state = {s: "idle" for s in self.SEATS}    # idle / waiting / bite / reeling
		self.spot = {s: None for s in self.SEATS}
		self.bite_at = {s: 0.0 for s in self.SEATS}     # 비밀: 입질이 올 시각
		self.bite_sent = {s: 0.0 for s in self.SEATS}   # 입질을 알린 시각
		self.fish = {s: None for s in self.SEATS}        # 물고 있는/걸린 물고기 {id, kg, stamina, power, window}
		self.reel = {s: None for s in self.SEATS}        # {progress, tension, t, surge_at, surge_until, last_pull}
		self.basket = {s: [] for s in self.SEATS}
		self.used = {s: [] for s in self.SEATS}
		self.shield = {s: False for s in self.SEATS}
		self.bait = {s: False for s in self.SEATS}
		self.glove = {s: False for s in self.SEATS}
		self.fakes = {s: [] for s in self.SEATS}         # s 에게 보낼 가짜 입질 시각들
		self.fake_until = {s: 0.0 for s in self.SEATS}   # 이 시각까지 챔질하면 가짜에 속은 것
		self.slow_until = {s: 0.0 for s in self.SEATS}   # 돌 맞은 뒤 다음 입질이 늦어짐
		self.winner = None
		self.reason = ""
		self.bot_due = {s: 0.0 for s in self.SEATS}

	# ── 공통 ──
	def seat_of(self, pid):
		return next((s for s, p in self.seats.items() if p == pid and s not in self.bots), None)

	def other(self, s):
		return "p2" if s == "p1" else "p1"

	def total(self, s):
		return round(sum(f["kg"] for f in self.basket[s]), 2)

	def biggest(self, s):
		return max((f["kg"] for f in self.basket[s]), default=0.0)

	def score(self, s):
		return self.total(s) if self.mode == "total" else self.biggest(s)

	def _emit_to(self, room, s, data):
		"""자리 s 의 사람에게만 (컴퓨터면 안 보냄)."""
		if s not in self.bots and self.seats[s]:
			room.emit(data, to=self.seats[s])

	def _finish(self, room, winner, reason):
		self.status = "over"
		self.winner = winner
		self.reason = reason
		for s in self.SEATS:
			self.state[s] = "idle"
			self.fish[s] = self.reel[s] = None
		if winner:
			self.wins[winner] += 1
		else:
			self.draws += 1
		room.notice(f"🏁 {reason}")
		room.emit({"type": "over", "winner": winner, "reason": reason})

	def _finish_by_score(self, room):
		a, b = self.score("p1"), self.score("p2")
		label = MODES[self.mode]
		if a == b:
			self._finish(room, None, f"{label} {a:g}kg 로 똑같아요. 무승부!")
		else:
			w = "p1" if a > b else "p2"
			self._finish(room, w, f"{self.names[w]} 님 승리! {label} {max(a, b):g}kg vs {min(a, b):g}kg")

	# ── 물고기 ──
	def _pick_fish(self, spot, boosted=False):
		table = TABLE[spot]
		if boosted:
			table = sorted((row for row in table if row[0] not in JUNK), key=lambda r: FISH[r[0]][3])[-3:]
			table = [(fid, 1) for fid, _ in table]
		total = sum(w for _, w in table)
		pick = self.rng.random() * total
		for fid, w in table:
			pick -= w
			if pick <= 0:
				break
		emoji, name, lo, hi, stamina, power, window = FISH[fid]
		t = self.rng.random() ** 1.6
		if boosted:
			t = 0.5 + t / 2
		kg = round(lo + (hi - lo) * t, 2) if hi else 0.0
		return {"id": fid, "emoji": emoji, "name": name, "kg": kg, "stamina": max(2, round(stamina * (0.8 + 0.4 * t))), "power": power, "window": window}

	def _schedule_bite(self, s, now, extra=0.0):
		lo, hi = SPOTS[self.spot[s]][1]
		delay = self.rng.uniform(lo, hi)
		if self.bait[s]:
			delay *= 0.5
		if self.slow_until[s] > now:
			extra += self.slow_until[s] - now
		self.bite_at[s] = now + delay + extra
		self.state[s] = "waiting"
		self.fish[s] = None

	def _cast(self, room, s, spot, now):
		self.spot[s] = spot
		self._schedule_bite(s, now)
		room.emit({"type": "cast", "seat": s, "spot": spot})
		return True, None

	def _escape(self, room, s, why, text):
		"""물고기가 도망감 → 다시 던져야 함."""
		fish = self.fish[s]
		self.state[s] = "idle"
		self.fish[s] = self.reel[s] = None
		self.glove[s] = False
		if s in self.bots:
			self.bot_due[s] = time.time() + self.rng.uniform(0.8, 2.0)
		room.emit({"type": "escape", "seat": s, "why": why, "text": text, "fish": fish if why == "snap" else None})

	def _bite(self, room, s, now, fake=False):
		if not fake:
			self.fish[s] = self._pick_fish(self.spot[s], self.bait[s])
			self.bait[s] = False
			self.state[s] = "bite"
			self.bite_sent[s] = now
			if s in self.bots:
				self.bot_due[s] = now + self._bot_reaction()
		else:
			self.fake_until[s] = now + 1.5
		self._emit_to(room, s, {"type": "bite", "seat": s})

	def _strike(self, room, s, now):
		st = self.state[s]
		if st == "waiting":
			if self.fake_until[s] > now:
				self.fake_until[s] = 0.0
				self._escape(room, s, "fake", "🫧 가짜 입질이었어요! 물고기가 놀라서 도망갔어요")
			else:
				self._escape(room, s, "early", "너무 빨랐어요! 입질이 오기 전에 챘어요")
			return True, None
		if st != "bite":
			return False, "지금은 챌 게 없어요."
		if now - self.bite_sent[s] > self.fish[s]["window"]:
			self._escape(room, s, "late", "늦었어요… 물고기가 미끼만 먹고 갔어요")
			return True, None
		self.state[s] = "reeling"
		f = self.fish[s]
		self.reel[s] = {"progress": 0.0, "tension": 0.25, "t": now, "surge_at": now + self._surge_gap(f), "surge_until": 0.0, "last_pull": 0.0}
		room.emit({"type": "hooked", "seat": s, "hint": size_hint(f["kg"]), "glove": self.glove[s]})
		return True, None

	def _surge_gap(self, f):
		return self.rng.uniform(1.6, 3.4) / (0.6 + f["power"])

	def _sync(self, s, now):
		r = self.reel[s]
		r["tension"] = max(0.0, r["tension"] - DECAY * (now - r["t"]))
		r["t"] = now
		return r

	def _reel_view(self, s, now):
		r = self.reel[s]
		return {"progress": round(r["progress"], 3), "tension": round(r["tension"], 3), "surge": round(max(0.0, r["surge_until"] - now), 2)}

	def _pull(self, room, s, now):
		if self.state[s] != "reeling":
			return False, "걸린 물고기가 없어요."
		r = self._sync(s, now)
		if now - r["last_pull"] < PULL_GAP:
			return False, None
		r["last_pull"] = now
		f = self.fish[s]
		surging = r["surge_until"] > now
		r["tension"] += PULL_T_SURGE if surging else PULL_T
		r["progress"] += 1.0 / f["stamina"]
		if r["tension"] > 1.0 and not self.glove[s]:
			self._escape(room, s, "snap", f"💥 줄이 끊어졌어요! {size_hint(f['kg'])} 놓침…")
			return True, None
		r["tension"] = min(r["tension"], 1.0)
		if r["progress"] >= 1.0:
			self._catch(room, s)
			return True, None
		self._emit_to(room, s, {"type": "reel", "seat": s, **self._reel_view(s, now)})
		return True, None

	def _catch(self, room, s):
		f = self.fish[s]
		self.state[s] = "idle"
		self.fish[s] = self.reel[s] = None
		self.glove[s] = False
		if f["id"] not in JUNK:
			self.basket[s].append({"id": f["id"], "emoji": f["emoji"], "name": f["name"], "kg": f["kg"]})
			room.notice(f"🎣 {self.names[s]} 님이 {f['emoji']} {f['name']} {f['kg']:g}kg 를 잡았어요!")
		else:
			room.notice(f"{f['emoji']} {self.names[s]} 님이 {f['name']}을(를) 건졌어요…")
		room.emit({"type": "catch", "seat": s, "fish": {"id": f["id"], "emoji": f["emoji"], "name": f["name"], "kg": f["kg"]}, "junk": f["id"] in JUNK,
				   "best": f["kg"] > 0 and f["kg"] >= self.biggest(s)})

	# ── 스킬 ──
	def _act_skill(self, room, s, sid, now):
		if not self.skills_on:
			return False, "이 판은 스킬 없이 해요."
		if sid not in SKILLS:
			return False, "모르는 스킬이에요."
		if sid in self.used[s]:
			return False, "이미 쓴 스킬이에요."
		icon, name, _, hostile = SKILLS[sid]
		o = self.other(s)
		if sid == "bait" and self.state[s] == "reeling":
			return False, "당기는 중엔 미끼를 못 갈아요."
		if sid == "glove" and self.state[s] == "reeling":
			return False, "이미 걸린 물고기엔 늦었어요. 다음 물고기 전에 끼세요."
		self.used[s].append(sid)
		blocked = False
		if hostile and self.shield[o]:
			self.shield[o] = False
			blocked = True
		elif sid == "bait":
			self.bait[s] = True
			if self.state[s] in ("waiting", "bite"):
				self.bite_at[s] = min(self.bite_at[s], now + self.rng.uniform(0.8, 1.6))
				if self.state[s] == "bite":
					self.state[s] = "waiting"   # 지금 문 건 보내고 더 큰 걸로
		elif sid == "glove":
			self.glove[s] = True
		elif sid == "shield":
			self.shield[s] = True
		elif sid == "rock":
			if self.state[o] in ("waiting", "bite"):
				if self.state[o] == "bite":
					self.fish[o] = None
				before = self.bite_at[o]
				self._schedule_bite(o, now, extra=3.0)
				self.bite_at[o] = max(self.bite_at[o], before + 3.0)   # 원래 올 시각보다 꼭 늦게
				self._emit_to(room, o, {"type": "escape", "seat": o, "why": "rock", "text": "🪨 돌이 떨어져 물고기가 달아났어요! 찌는 그대로…", "fish": None, "keep": True})
			elif self.state[o] == "reeling":
				r = self._sync(o, now)
				r["tension"] = min(0.97, r["tension"] + 0.45)
				r["surge_until"] = max(r["surge_until"], now + SURGE_LEN)
				self._emit_to(room, o, {"type": "reel", "seat": o, **self._reel_view(o, now), "rock": True})
			else:
				self.slow_until[o] = now + 3.0
		elif sid == "fake":
			self.fakes[o] = sorted(now + self.rng.uniform(1.0, 12.0) for _ in range(2))
		room.emit({"type": "skill", "seat": s, "id": sid, "icon": icon, "name": name, "blocked": blocked,
				   "secret": sid == "fake" and not blocked})
		if sid == "fake" and not blocked:
			room.notice(f"{icon} {self.names[s]} 님이 스킬을 썼어요.")
		else:
			room.notice(f"{icon} {self.names[s]} 님의 {name}!" + (" 🛡 방패에 막혔어요." if blocked else ""))
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
			if data.get("duration") in DURATIONS:
				self.duration = data["duration"]
			if data.get("mode") in MODES:
				self.mode = data["mode"]
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
			self.started_at = now
			self.ends_at = now + self.duration
			for s in self.bots:
				self.bot_due[s] = now + self.rng.uniform(0.8, 2.0)
			room.notice(f"🎣 낚시 시작! {self.duration}초 동안 {MODES[self.mode]}로 겨뤄요. 자리를 골라 던지세요.")
			return True, None
		if kind == "resign":
			if not busy or not seat:
				return False, None
			self._finish(room, self.other(seat), f"{self.names[seat]} 님이 기권했어요.")
			return True, None
		if kind in ("cast", "strike", "pull", "reel-in", "skill"):
			if self.status != "playing":
				return False, "아직 판이 시작되지 않았어요."
			if not seat:
				return False, "구경 중이에요."
			if kind == "cast":
				if self.state[seat] != "idle":
					return False, "이미 찌를 던져 뒀어요. 거두려면 '거두기'."
				if now >= self.ends_at:
					return False, "시간이 다 됐어요."
				spot = data.get("spot")
				if spot not in SPOTS:
					return False, "자리를 골라 주세요."
				return self._cast(room, seat, spot, now)
			if kind == "strike":
				return self._strike(room, seat, now)
			if kind == "pull":
				return self._pull(room, seat, now)
			if kind == "reel-in":
				if self.state[seat] not in ("waiting", "bite"):
					return False, None
				self.state[seat] = "idle"
				self.fish[seat] = None
				room.emit({"type": "escape", "seat": seat, "why": "reel-in", "text": "찌를 거뒀어요", "fish": None})
				return True, None
			return self._act_skill(room, seat, data.get("id"), now)
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
		changed = False
		for s in self.SEATS:
			st = self.state[s]
			if st == "waiting":
				if now >= self.bite_at[s]:
					self._bite(room, s, now)
					changed = True
				elif self.fakes[s] and now >= self.fakes[s][0]:
					self.fakes[s].pop(0)
					self._bite(room, s, now, fake=True)
			elif st == "bite" and now - self.bite_sent[s] > self.fish[s]["window"]:
				self._escape(room, s, "late", "늦었어요… 물고기가 미끼만 먹고 갔어요")
				changed = True
			elif st == "reeling":
				r = self._sync(s, now)
				if now >= r["surge_at"]:
					f = self.fish[s]
					r["tension"] = min(0.97, r["tension"] + f["power"])
					r["progress"] = max(0.0, r["progress"] - 0.05)
					r["surge_until"] = now + SURGE_LEN
					r["surge_at"] = now + SURGE_LEN + self._surge_gap(f)
					self._emit_to(room, s, {"type": "reel", "seat": s, **self._reel_view(s, now), "surge_hit": True})
					changed = True
			if s in self.bots and self.status == "playing":
				changed = self._bot_act(room, s, now) or changed
		if self.status == "playing" and now >= self.ends_at:
			reeling = any(self.state[s] == "reeling" for s in self.SEATS)
			if not reeling or now >= self.ends_at + OVERTIME:
				self._finish_by_score(room)
				return True
		return changed

	def _bot_reaction(self):
		return {"easy": self.rng.uniform(0.3, 1.9), "normal": self.rng.uniform(0.3, 0.9), "hard": self.rng.uniform(0.2, 0.55)}[self.bot_level]

	def _bot_spot(self):
		r = self.rng.random()
		if self.bot_level == "easy":
			return self.rng.choice(list(SPOTS))
		if self.bot_level == "normal":
			return "weeds" if r < 0.6 else "deep"
		if self.mode == "biggest":
			return "deep"
		return "deep" if r < 0.7 else "weeds"

	def _bot_act(self, room, s, now):
		st, o = self.state[s], self.other(s)
		level = self.bot_level
		if self.skills_on and self.rng.random() < 0.3:
			allowed = BOT_SKILLS[level]
			pick = None
			left = self.ends_at - now
			if (allowed is None or "shield" in allowed) and "shield" not in self.used[s] and left < self.duration - 5:
				pick = "shield"
			elif (allowed is None or "glove" in allowed) and "glove" not in self.used[s] and st == "idle" and left < self.duration * 0.7:
				pick = "glove"
			elif (allowed is None or "bait" in allowed) and "bait" not in self.used[s] and st in ("idle", "waiting") and left < self.duration * 0.6:
				pick = "bait"
			elif allowed is None and "rock" not in self.used[s] and self.state[o] == "reeling" and self.reel[o]["progress"] > 0.4:
				pick = "rock"
			elif allowed is None and "fake" not in self.used[s] and self.state[o] == "waiting" and left > 15:
				pick = "fake"
			if pick:
				self._act_skill(room, s, pick, now)
				return True
		if st == "idle":
			if now >= self.bot_due[s] and now < self.ends_at:
				self._cast(room, s, self._bot_spot(), now)
				return True
			return False
		if st == "bite":
			if now >= self.bot_due[s]:
				self._strike(room, s, now)
				return True
			return False
		if st == "reeling":
			r = self._sync(s, now)
			surging = r["surge_until"] > now
			thr = {"easy": 0.85, "normal": 0.7, "hard": 0.62}[level]
			if surging and (level != "easy" or self.rng.random() < 0.6):
				return False
			pulls = 0
			if r["tension"] < thr:
				pulls = 1
				if r["tension"] < 0.4 and (level == "hard" or (level == "normal" and self.rng.random() < 0.5)):
					pulls = 2
			for i in range(pulls):
				if self.state[s] != "reeling":
					break
				r["last_pull"] = 0.0
				self._pull(room, s, now + i * 0.01)
			if self.state[s] == "idle":
				self.bot_due[s] = now + self.rng.uniform(0.8, 2.0)
			return pulls > 0
		return False

	# ── 보기 ──
	def snapshot(self, room, pid=None):
		me = next((s for s, p in self.seats.items() if p == pid), None)
		now = time.time()
		over = self.status == "over"

		def player(s):
			mine = me == s or over
			d = {
				"state": self.state[s], "spot": self.spot[s], "basket": self.basket[s],
				"total": self.total(s), "biggest": self.biggest(s), "used": self.used[s],
			}
			if self.state[s] == "reeling" and self.reel[s]:
				view = self._reel_view(s, now)
				d["reel"] = view if mine else {"progress": view["progress"]}
				d["hint"] = size_hint(self.fish[s]["kg"])
			if mine:
				d["shield"], d["bait"], d["glove"] = self.shield[s], self.bait[s], self.glove[s]
			return d

		return {
			"status": self.status, "skills_on": self.skills_on, "duration": self.duration, "mode": self.mode, "bot_level": self.bot_level,
			"winner": self.winner, "reason": self.reason,
			"left": round(max(0.0, self.ends_at - now), 2) if self.status == "playing" else None,
			"overtime": bool(self.status == "playing" and now >= self.ends_at),
			"players": {s: player(s) for s in self.SEATS},
			"spots": [{"id": k, "name": v[0]} for k, v in SPOTS.items()],
			"skills": [{"id": k, "icon": v[0], "name": v[1], "desc": v[2]} for k, v in SKILLS.items()],
			"modes": [{"id": k, "name": v} for k, v in MODES.items()],
			"draws": self.draws,
			"seats": {s: ({"name": self.names[s], "bot": s in self.bots, "online": s in self.bots or p in room.peers, "wins": self.wins[s]} if p else None)
					  for s, p in self.seats.items()},
		}
