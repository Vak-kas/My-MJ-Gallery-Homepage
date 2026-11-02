"""🏴‍☠️ 1:1 함대 격침 (배틀십) + 스킬.

규칙
- 10×10 바다에 배 5척(5·4·3·3·2칸)을 가로·세로로 숨기고 번갈아 한 칸씩 포격
- 맞으면 💥 명중, 그 배의 칸을 다 맞히면 ⚓ 침몰, 빗나가면 💦 물기둥
- 상대 배를 다 가라앉히면 승리. 선공이 먼저 끝내면 후공에게 마지막 기회 1번 → 둘 다 끝내면 무승부
- 옵션 '명중하면 한 번 더'(기본 꺼짐), 한 턴 TURN_LIMIT 초 — 넘기면 그 턴은 지나감
- 스킬(켜면): 판마다 종류별로 1번, 한 턴에 하나
"""

import random
import time

SIZE = 10
SHIPS = [("carrier", "기함", 5), ("battleship", "전함", 4), ("cruiser", "순양함", 3), ("submarine", "잠수함", 3), ("destroyer", "구축함", 2)]
SHIP_LEN = {k: n for k, _, n in SHIPS}
SHIP_NAME = {k: name for k, name, _ in SHIPS}
TURN_LIMIT = 45
BOT_DELAY = 2.6
BOT_SKILL_DELAY = 3.6
BOT_NAME = "🤖 컴퓨터"
BOT_LEVELS = ("easy", "normal", "hard")
BOT_SKILLS = {"easy": set(), "normal": {"shield", "repair"}, "hard": None}

# id: (아이콘, 이름, 설명, 상대에게 거는 방해인지 — 방패로 막힘, 판에서 칸을 골라야 하는지)
SKILLS = {
	"radar": ("📡", "레이더", "고른 칸 둘레 3×3 안에 아직 안 맞힌 배 칸이 몇 개인지 알려 줘요", True, True),
	"salvo": ("💥", "일제사격", "이번 턴엔 한 줄로 3칸을 한꺼번에 쏴요", False, True),
	"smoke": ("🌫", "연막", "상대의 다음 포격 결과를 상대에게 가려요", True, False),
	"repair": ("🔧", "수리", "아직 안 가라앉은 내 배의 맞은 칸 하나를 고쳐요 — 상대는 그 칸을 다시 쏴야 해요", False, True),
	"shield": ("🛡", "방패", "상대가 다음에 거는 방해 스킬(레이더·연막) 하나를 막아요", False, False),
}


def cells_of(x, y, n, d):
	return [(x + i, y) if d == "h" else (x, y + i) for i in range(n)]


def in_board(x, y):
	return 0 <= x < SIZE and 0 <= y < SIZE


def validate_fleet(ships):
	"""[{id, x, y, dir}] → {id: [(x, y), ...]} 또는 (None, 이유)."""
	if not isinstance(ships, list) or sorted(str(s.get("id")) for s in ships if isinstance(s, dict)) != sorted(SHIP_LEN):
		return None, "배 5척을 모두 놓아 주세요."
	fleet, taken = {}, set()
	for s in ships:
		try:
			x, y, d = int(s["x"]), int(s["y"]), str(s.get("dir") or "h")
		except (KeyError, TypeError, ValueError):
			return None, "배 위치가 올바르지 않아요."
		if d not in ("h", "v"):
			return None, "배 방향이 올바르지 않아요."
		cells = cells_of(x, y, SHIP_LEN[s["id"]], d)
		if not all(in_board(*c) for c in cells):
			return None, f"{SHIP_NAME[s['id']]}이 바다 밖으로 나갔어요."
		if taken & set(cells):
			return None, "배끼리 겹쳤어요."
		taken |= set(cells)
		fleet[s["id"]] = cells
	return fleet, None


def random_fleet(rng):
	while True:
		ships, taken, ok = [], set(), True
		for sid, _, n in SHIPS:
			for _ in range(200):
				d = rng.choice("hv")
				x, y = rng.randrange(SIZE - (n - 1 if d == "h" else 0)), rng.randrange(SIZE - (n - 1 if d == "v" else 0))
				cells = set(cells_of(x, y, n, d))
				if not cells & taken:
					taken |= cells
					ships.append({"id": sid, "x": x, "y": y, "dir": d})
					break
			else:
				ok = False
				break
		if ok:
			return ships


class BattleshipLogic:
	kind = "battleship"
	SEATS = ("p1", "p2")

	def __init__(self, rng=None):
		self.rng = rng or random.Random()
		self.seats = {s: None for s in self.SEATS}
		self.names = {s: "" for s in self.SEATS}
		self.bots = set()
		self.wins = {s: 0 for s in self.SEATS}
		self.draws = 0
		self.skills_on = True
		self.again = False
		self.bot_level = "normal"
		self.starter = "p1"
		self.reset()

	def reset(self):
		self.status = "waiting"          # waiting / setup / playing / over
		self.fleet = {s: None for s in self.SEATS}      # s 의 배: {id: [cells]}
		self.hits = {s: set() for s in self.SEATS}      # s 의 배에서 맞은 칸
		self.shots = {s: {} for s in self.SEATS}        # s 가 쏜 칸: (x,y) → "hit"/"miss"/"repaired", 가려진 건 hidden 표시
		self.hidden = {s: set() for s in self.SEATS}    # s 가 쏜 칸 중 연막으로 s 에게 가려진 칸
		self.sunk = {s: [] for s in self.SEATS}         # s 의 배 중 가라앉은 id
		self.turn = None
		self.first = None
		self.turn_started = 0.0
		self.turns = {s: 0 for s in self.SEATS}
		self.done = {s: False for s in self.SEATS}      # s 가 상대 배를 다 가라앉힘
		self.used = {s: [] for s in self.SEATS}
		self.skill_this_turn = False
		self.salvo_now = False
		self.smoke = {s: False for s in self.SEATS}     # s 의 다음 포격 결과가 s 에게 가려짐
		self.shield = {s: False for s in self.SEATS}
		self.winner = None
		self.reason = ""
		self.bot_due = 0.0
		self.bot_plan = {s: None for s in self.SEATS}

	# ── 공통 ──
	def seat_of(self, pid):
		return next((s for s, p in self.seats.items() if p == pid and s not in self.bots), None)

	def other(self, s):
		return "p2" if s == "p1" else "p1"

	def ship_at(self, s, cell):
		return next((sid for sid, cells in self.fleet[s].items() if cell in cells), None)

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
		room.emit({"type": "over", "winner": winner, "reason": reason})

	def _begin_play(self, room):
		self.status = "playing"
		self.first = self.starter
		self.starter = self.other(self.starter)
		self._start_turn(self.first)
		room.notice(f"⚓ 출항! {self.names[self.first]} 님 선공. 상대 바다를 포격하세요.")

	def _start_turn(self, s):
		self.turn = s
		self.turn_started = time.time()
		self.skill_this_turn = False
		self.salvo_now = False
		if s in self.bots:
			self.bot_due = time.time() + BOT_DELAY

	def _end_turn(self, room, hit=False):
		s, o = self.turn, self.other(self.turn)
		self.turns[s] += 1
		if self.done[s]:
			if self.turns[o] < self.turns[s]:
				room.notice(f"🔥 {self.names[s]} 님이 함대를 전멸시켰어요! {self.names[o]} 님에게 마지막 기회!")
				room.emit({"type": "last-chance", "seat": o})
				self._start_turn(o)
				return
			if self.done[o]:
				self._finish(room, None, "둘 다 함대를 전멸시켰어요. 무승부!")
			else:
				self._finish(room, s, f"{self.names[s]} 님이 {self.turns[s]}번 포격으로 함대를 전멸시켰어요! 🎉")
			return
		if self.done[o]:
			self._finish(room, o, f"{self.names[o]} 님 승리! ({self.names[s]} 님이 마지막 기회를 놓쳤어요)")
			return
		if hit and self.again and not self.done[o]:
			self.turn_started = time.time()
			self.skill_this_turn = False
			self.salvo_now = False
			if s in self.bots:
				self.bot_due = time.time() + BOT_DELAY
			return
		self._start_turn(o)

	# ── 포격 ──
	def _fire_one(self, s, x, y):
		"""한 칸 포격. 결과 dict (이미 쏜 칸이면 None)."""
		o = self.other(s)
		cell = (x, y)
		if self.shots[s].get(cell) in ("hit", "miss"):
			return None
		sid = self.ship_at(o, cell)
		res = {"x": x, "y": y, "hit": bool(sid), "sunk": None}
		if sid:
			self.hits[o].add(cell)
			self.shots[s][cell] = "hit"
			if all(c in self.hits[o] for c in self.fleet[o][sid]):
				self.sunk[o].append(sid)
				res["sunk"] = {"id": sid, "name": SHIP_NAME[sid], "cells": [list(c) for c in self.fleet[o][sid]]}
		else:
			self.shots[s][cell] = "miss"
		return res

	def _act_fire(self, room, s, cells):
		o = self.other(s)
		cells = [(x, y) for x, y in cells if in_board(x, y) and self.shots[s].get((x, y)) not in ("hit", "miss")]
		if not cells:
			return False, "이미 쏜 칸이에요. 다른 칸을 고르세요."
		results = [r for r in (self._fire_one(s, x, y) for x, y in cells) if r]
		hide = self.smoke[s] and not (len(self.sunk[o]) == len(SHIPS))
		self.smoke[s] = False
		for r in results:
			if hide and not r["sunk"]:
				self.hidden[s].add((r["x"], r["y"]))
		ev = {"type": "shots", "seat": s, "shots": results, "salvo": len(cells) > 1, "hidden": False}
		if hide:
			room.emit(ev, exclude=self.seats[s])
			masked = [{**r, "hit": None, "sunk": None} if (r["x"], r["y"]) in self.hidden[s] else r for r in results]
			room.emit({**ev, "shots": masked, "hidden": True}, to=self.seats[s])
			room.notice(f"💣 {self.names[s]}: {self._coord(cells[0])}{' 외 ' + str(len(cells) - 1) + '칸' if len(cells) > 1 else ''} → 🌫 연막 속 결과")
		else:
			room.emit(ev)
			for r in results:
				text = f"⚓ {r['sunk']['name']} 침몰!" if r["sunk"] else "💥 명중" if r["hit"] else "💦 물기둥"
				room.notice(f"💣 {self.names[s]}: {self._coord((r['x'], r['y']))} → {text}")
		if len(self.sunk[o]) == len(SHIPS):
			self.done[s] = True
		self._end_turn(room, hit=any(r["hit"] for r in results))
		return True, None

	@staticmethod
	def _coord(cell):
		return f"{'ABCDEFGHIJ'[cell[0]]}{cell[1] + 1}"

	# ── 스킬 ──
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
		icon, name, _, hostile, needs_cell = SKILLS[sid]
		data = data or {}
		x = y = None
		if needs_cell:
			try:
				x, y = int(data.get("x")), int(data.get("y"))
			except (TypeError, ValueError):
				return False, "판에서 칸을 골라 주세요."
			if not in_board(x, y):
				return False, "바다 안의 칸을 골라 주세요."
		private = None
		area = None
		if sid == "repair":
			cell = (x, y)
			ship = self.ship_at(s, cell)
			if cell not in self.hits[s] or not ship or ship in self.sunk[s]:
				return False, "아직 안 가라앉은 내 배의 맞은 칸을 골라요."
			self.hits[s].discard(cell)
			self.shots[o][cell] = "repaired"
			self.hidden[o].discard(cell)
		elif sid == "salvo":
			d = "v" if data.get("dir") == "v" else "h"
			cells = [(x + i, y) if d == "h" else (x, y + i) for i in (-1, 0, 1)]
			cells = [c for c in cells if in_board(*c) and self.shots[s].get(c) not in ("hit", "miss")]
			if not cells:
				return False, "이미 다 쏜 칸이에요."
			self.used[s].append(sid)
			self.skill_this_turn = True
			self.salvo_now = True
			room.notice(f"{icon} {self.names[s]} 님의 일제사격!")
			room.emit({"type": "skill", "seat": s, "id": sid, "icon": icon, "name": name, "cells": [list(c) for c in cells]})
			return self._act_fire(room, s, cells)
		self.used[s].append(sid)
		self.skill_this_turn = True
		if hostile and self.shield[o]:
			self.shield[o] = False
			room.notice(f"🛡 {self.names[o]} 님의 방패가 {self.names[s]} 님의 {icon} {name} 을(를) 막았어요!")
			room.emit({"type": "skill", "seat": s, "id": sid, "icon": icon, "name": name, "blocked": True})
			return True, None
		if sid == "radar":
			area = [(x + dx, y + dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1) if in_board(x + dx, y + dy)]
			n = sum(1 for c in area if self.ship_at(o, c) and c not in self.hits[o])
			private = f"📡 {self._coord((x, y))} 둘레에 아직 안 맞힌 배 칸이 {n}개 있어요." if n else f"📡 {self._coord((x, y))} 둘레엔 배가 없어요."
			self.bot_plan[s] = {"radar": (x, y, n)}
		elif sid == "smoke":
			self.smoke[o] = True
		elif sid == "shield":
			self.shield[s] = True
		room.notice(f"{icon} {self.names[s]} 님이 '{name}' 스킬을 썼어요!")
		room.emit({"type": "skill", "seat": s, "id": sid, "icon": icon, "name": name, "cell": [x, y] if needs_cell else None, "count": None})
		if private:
			room.emit({"type": "intel", "text": private, "cell": [x, y]}, to=self.seats[s])
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
			if isinstance(data.get("skills"), bool):
				self.skills_on = data["skills"]
			if isinstance(data.get("again"), bool):
				self.again = data["again"]
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
				self.fleet[s], _ = validate_fleet(random_fleet(self.rng))
			room.notice("⚓ 각자 배 5척을 바다에 숨기세요.")
			return True, None
		if kind == "place":
			if self.status != "setup" or not seat:
				return False, None
			ships = random_fleet(self.rng) if data.get("auto") else data.get("ships")
			fleet, err = validate_fleet(ships)
			if err:
				return False, err
			first_time = self.fleet[seat] is None
			self.fleet[seat] = fleet
			if first_time:
				room.notice(f"🔒 {peer.name} 님이 함대 배치를 마쳤어요.")
			if all(self.fleet.values()):
				self._begin_play(room)
			return True, None
		if kind == "resign":
			if not busy or not seat:
				return False, None
			self._finish(room, self.other(seat), f"{self.names[seat]} 님이 기권했어요.")
			return True, None
		if kind in ("fire", "skill"):
			if self.status != "playing":
				return False, "아직 판이 시작되지 않았어요."
			if seat != self.turn:
				return False, "내 차례가 아니에요." if seat else "구경 중이에요."
			if kind == "fire":
				try:
					x, y = int(data.get("x")), int(data.get("y"))
				except (TypeError, ValueError):
					return False, "칸을 골라 주세요."
				if not in_board(x, y):
					return False, "바다 안의 칸을 골라 주세요."
				return self._act_fire(room, seat, [(x, y)])
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

	def _open_cells(self, s):
		return [(x, y) for x in range(SIZE) for y in range(SIZE) if self.shots[s].get((x, y)) not in ("hit", "miss")]

	def _active_hits(self, s):
		"""s 가 맞힌 칸 중 아직 안 가라앉은 배의 칸 (수리된 칸도 다시 쏠 곳으로)."""
		o = self.other(s)
		sunk_cells = {c for sid in self.sunk[o] for c in self.fleet[o][sid]}
		return [c for c, r in self.shots[s].items() if r == "hit" and c not in sunk_cells and c not in self.hidden[s]]

	def _targets(self, s):
		"""명중한 칸 둘레의 안 쏜 칸 — 두 칸 이상 한 줄이면 그 줄 양 끝부터."""
		hits = self._active_hits(s)
		if not hits:
			return []
		opened = lambda c: self.shots[s].get(c) in ("hit", "miss")
		out = []
		hs = set(hits)
		for (x, y) in hits:
			for d, (dx, dy) in (("h", (1, 0)), ("h", (-1, 0)), ("v", (0, 1)), ("v", (0, -1))):
				c = (x + dx, y + dy)
				line = (x - dx, y - dy) in hs
				if in_board(*c) and not opened(c):
					out.append((2 if line else 1, c))
		if not out:
			return []
		best = max(p for p, _ in out)
		return [c for p, c in out if p == best]

	def _density(self, s):
		"""남은 배들을 놓을 수 있는 자리 수로 칸마다 점수 (어려움)."""
		o = self.other(s)
		remaining = [SHIP_LEN[sid] for sid in SHIP_LEN if sid not in self.sunk[o]]
		sunk_cells = {c for sid in self.sunk[o] for c in self.fleet[o][sid]}
		blocked = {c for c, r in self.shots[s].items() if r == "miss"} | sunk_cells
		hits = set(self._active_hits(s))
		score = {}
		for n in remaining:
			for x in range(SIZE):
				for y in range(SIZE):
					for d in "hv":
						cells = cells_of(x, y, n, d)
						if not all(in_board(*c) for c in cells) or blocked & set(cells):
							continue
						w = 1 + 12 * len(hits & set(cells))
						for c in cells:
							if c not in hits:
								score[c] = score.get(c, 0) + w
		return score

	def _bot_pick(self, s):
		repaired = [c for c, r in self.shots[s].items() if r == "repaired"]
		if repaired:
			return self.rng.choice(repaired)
		targets = self._targets(s)
		if targets and not (self.bot_level == "easy" and self.rng.random() < 0.35):  # 쉬움은 가끔 딴 데를 쏨
			return self.rng.choice(targets)
		open_cells = self._open_cells(s)
		if self.bot_level == "hard":
			dens = self._density(s)
			plan = self.bot_plan[s] or {}
			if "radar" in plan:  # 레이더로 본 둘레를 우선
				rx, ry, n = plan["radar"]
				for c in list(dens):
					if abs(c[0] - rx) <= 1 and abs(c[1] - ry) <= 1:
						dens[c] = dens[c] * 3 if n else 0
			best = max((dens.get(c, 0) for c in open_cells), default=0)
			pool = [c for c in open_cells if dens.get(c, 0) == best] or open_cells
			return self.rng.choice(pool)
		if self.bot_level == "normal":
			parity = [c for c in open_cells if (c[0] + c[1]) % 2 == 0]
			return self.rng.choice(parity or open_cells)
		return self.rng.choice(open_cells)

	def _bot_skill(self, s, o):
		allowed = BOT_SKILLS[self.bot_level]
		free = [k for k in SKILLS if k not in self.used[s] and (allowed is None or k in allowed)]
		my_damaged = [c for c in self.hits[s] if self.ship_at(s, c) not in self.sunk[s]]
		if "repair" in free and len(my_damaged) >= 2:
			return "repair", {"x": my_damaged[0][0], "y": my_damaged[0][1]}
		if "shield" in free and self.turns[s] == 2:
			return "shield", None
		opp_close = len(self.sunk[s]) >= 3
		if "smoke" in free and opp_close:
			return "smoke", None
		hits = self._active_hits(s)
		if "salvo" in free and len(hits) >= 2:
			(x1, y1), (x2, y2) = hits[0], hits[1]
			if x1 == x2 or y1 == y2:
				d = "v" if x1 == x2 else "h"
				ys = sorted(c[1] if d == "v" else c[0] for c in hits if (c[0] == x1 if d == "v" else c[1] == y1))
				end = ys[-1] + 1 if self.rng.random() < 0.5 else ys[0] - 1
				c = (x1, end) if d == "v" else (end, y1)
				if in_board(*c):
					return "salvo", {"x": c[0], "y": c[1], "dir": d}
		if "radar" in free and self.turns[s] == 3 and not hits:
			dens = self._density(s)
			best = max(((x, y) for x in range(1, SIZE - 1) for y in range(1, SIZE - 1)),
					   key=lambda c: sum(dens.get((c[0] + dx, c[1] + dy), 0) for dx in (-1, 0, 1) for dy in (-1, 0, 1)))
			return "radar", {"x": best[0], "y": best[1]}
		return None, None

	def bot_act(self, room):
		s, o = self.turn, self.other(self.turn)
		if self.skills_on and not self.skill_this_turn:
			pick, extra = self._bot_skill(s, o)
			if pick:
				ok, _ = self._act_skill(room, s, pick, extra)
				if ok:
					if pick == "radar":
						self.bot_plan[s] = {**(self.bot_plan[s] or {}), "radar_turn": self.turns[s]}
					if self.status == "playing" and self.turn == s:
						self.bot_due = time.time() + BOT_SKILL_DELAY
					return
		x, y = self._bot_pick(s)
		self._act_fire(room, s, [(x, y)])
		if self.status == "playing" and self.turn == s:  # 명중하면 한 번 더
			self.bot_due = time.time() + BOT_DELAY

	# ── 보여 주기 ──
	def snapshot(self, room, pid=None):
		me = next((s for s, p in self.seats.items() if p == pid), None)
		over = self.status == "over"

		def shots_view(s):
			"""s 가 쏜 칸들. s 본인에게 가려진 칸은 '?'."""
			out = []
			for (x, y), r in self.shots[s].items():
				if (x, y) in self.hidden[s] and not over and me == s:
					out.append({"x": x, "y": y, "r": "?"})
				else:
					out.append({"x": x, "y": y, "r": r})
			return out

		def fleet_view(s):
			if not self.fleet[s]:
				return None
			if over or me == s:
				return {sid: [list(c) for c in cells] for sid, cells in self.fleet[s].items()}
			return {sid: [list(c) for c in self.fleet[s][sid]] for sid in self.sunk[s]}  # 남에겐 가라앉은 배만

		return {
			"status": self.status, "skills_on": self.skills_on, "again": self.again,
			"turn": self.turn, "first": self.first, "bot_level": self.bot_level, "winner": self.winner, "reason": self.reason,
			"elapsed": round(time.time() - self.turn_started, 2) if self.turn else None, "turn_limit": TURN_LIMIT,
			"skill_this_turn": self.skill_this_turn,
			"last_chance": bool(self.turn and self.done[self.other(self.turn)]),
			"ready": {s: self.fleet[s] is not None for s in self.SEATS},
			"fleet": {s: fleet_view(s) for s in self.SEATS},
			"hits": {s: [list(c) for c in self.hits[s]] for s in self.SEATS},
			"shots": {s: shots_view(s) for s in self.SEATS},
			"sunk": self.sunk,
			"turns": self.turns,
			"used": self.used,
			"my_shield": bool(me and self.shield[me]),
			"smoked": bool(me and self.smoke[me]),
			"ships": [{"id": k, "name": n, "len": ln} for k, n, ln in SHIPS],
			"skills": [{"id": k, "icon": v[0], "name": v[1], "desc": v[2], "cell": v[4]} for k, v in SKILLS.items()],
			"draws": self.draws,
			"seats": {s: ({"name": self.names[s], "bot": s in self.bots, "online": s in self.bots or p in room.peers, "wins": self.wins[s]} if p else None)
					  for s, p in self.seats.items()},
		}
