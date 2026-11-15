"""🫥 숨바꼭질 (물건으로 변신) — 술래 1명(1인칭) 대 숨는 사람들(3인칭, 물건으로 변신).

1단계 규칙
- 방장이 [시작] → 술래 한 명(판마다 돌아가며), 나머지는 숨는 사람
- 숨기(HIDE 초): 술래는 눈을 감고 못 움직임. 숨는 사람은 집 안의 물건을 보고 E 로 그 물건으로 변신해 자리를 잡음
- 찾기(SEEK 초): 술래가 1인칭으로 돌아다니며 수상한 물건을 쏨
  · 숨은 사람을 맞히면 그 사람 체력 −HIT_DAMAGE (0 이 되면 잡힘)
  · 진짜 물건을 쏘면 술래 체력 −MISS_PENALTY (마구 쏘기 방지), 0 이 되면 숨는 쪽 승리
  · TAUNT_EVERY 초마다 살아 있는 숨는 사람 자리에서 '삑' 소리 (술래가 방향으로 들음)
- 다 잡으면 술래 승리, 시간이 끝나면 살아남은 숨는 사람 승리

판정은 서버가: 위치는 브라우저가 보내되 서버가 집 범위·속도를 확인, 쏘기는 거리·방향·쿨타임을 서버가 확인.
위치는 상태 전체를 다시 보내지 않고 room.emit 으로 바로 전달 (초당 십여 번).
숨는 사람은 술래에게 이름 대신 아무 뜻 없는 번호(eid)로만 보임.
"""

import math
import random
import secrets
import time

MAX_PLAYERS = 8
HIDE_CHOICES = (20, 30, 45, 60)
SEEK_CHOICES = (120, 180, 240, 300)
HIDER_HP = 100
SEEKER_HP = 100
HIT_DAMAGE = 50
MISS_PENALTY = 8
SHOOT_COOLDOWN = 0.35
SHOOT_RANGE = 16.0
SHOOT_CONE = math.cos(math.radians(35))
TAUNT_EVERY = 30
SPEED = {"hider": 4.2, "seeker": 4.6}   # m/s — 클라이언트와 같아야 함
POS_MIN_INTERVAL = 0.045
WALL_H = 3.0

# 물건 종류: (이름, 가로 w, 높이 h, 세로 d) — 미터. 모양·색은 브라우저가 종류로 그림
PROPS = {
	"box": ("상자", 0.8, 0.8, 0.8),
	"chair": ("의자", 0.6, 1.0, 0.6),
	"stool": ("스툴", 0.45, 0.5, 0.45),
	"table": ("탁자", 1.6, 0.8, 0.9),
	"sofa": ("소파", 2.2, 0.9, 0.9),
	"plant": ("화분", 0.5, 1.2, 0.5),
	"lamp": ("스탠드", 0.4, 1.6, 0.4),
	"barrel": ("통", 0.7, 1.0, 0.7),
	"shelf": ("책장", 1.2, 2.0, 0.4),
	"tv": ("TV", 1.4, 0.9, 0.5),
	"bed": ("침대", 2.0, 0.6, 1.6),
	"fridge": ("냉장고", 0.8, 1.9, 0.8),
	"trash": ("쓰레기통", 0.45, 0.7, 0.45),
	"ball": ("공", 0.5, 0.5, 0.5),
}


def _house():
	"""집 한 채: 거실(왼쪽 12×16), 부엌(오른쪽 아래 12×9), 침실(오른쪽 위 12×7). 좌표 x·z (m), 벽은 가운데·크기."""
	W, D = 24.0, 16.0
	t = 0.3
	walls = [
		(W / 2, -t / 2, W + 2 * t, t), (W / 2, D + t / 2, W + 2 * t, t),
		(-t / 2, D / 2, t, D), (W + t / 2, D / 2, t, D),
		# 거실 | 부엌·침실 (문 두 개: z 3~5, 11.5~13.5)
		(12, 1.5, t, 3), (12, 8.25, t, 6.5), (12, 14.75, t, 2.5),
		# 부엌 | 침실 (문: x 17~19)
		(14.5, 9, 5, t), (21.5, 9, 5, t),
	]
	P = [
		# 거실
		("sofa", 3.5, 1.2, 0), ("table", 3.5, 3.2, 0), ("tv", 3.5, 7.2, math.pi), ("lamp", 0.8, 0.8, 0),
		("plant", 7.0, 0.8, 0), ("shelf", 0.5, 6.0, math.pi / 2), ("shelf", 0.5, 9.0, math.pi / 2),
		("chair", 2.3, 3.2, math.pi / 2), ("chair", 4.7, 3.2, -math.pi / 2), ("box", 9.0, 1.0, 0.3),
		("box", 10.0, 1.2, 0), ("box", 9.5, 2.1, 0.8), ("barrel", 11.0, 6.5, 0), ("ball", 6.5, 10.5, 0),
		("plant", 11.3, 15.2, 0), ("stool", 8.0, 12.5, 0), ("table", 6.0, 14.6, 0), ("chair", 5.0, 13.6, 0),
		("chair", 7.0, 13.6, 0), ("lamp", 0.8, 15.2, 0), ("trash", 10.8, 10.5, 0), ("box", 1.2, 12.5, 0.2),
		# 부엌
		("fridge", 23.3, 0.7, 0), ("shelf", 20.5, 0.4, 0), ("table", 17.5, 4.5, 0), ("chair", 16.6, 3.5, 0),
		("chair", 18.4, 3.5, 0), ("chair", 16.6, 5.5, math.pi), ("chair", 18.4, 5.5, math.pi), ("trash", 13.0, 0.6, 0),
		("barrel", 23.2, 7.8, 0), ("box", 22.0, 8.0, 0.5), ("stool", 14.5, 7.5, 0), ("plant", 13.0, 8.2, 0),
		# 침실
		("bed", 21.8, 13.5, 0), ("shelf", 23.6, 10.5, -math.pi / 2), ("lamp", 23.3, 15.4, 0), ("box", 13.0, 15.2, 0),
		("box", 13.0, 14.3, 0.4), ("tv", 16.0, 15.5, math.pi), ("ball", 15.5, 11.0, 0), ("plant", 18.7, 9.8, 0),
		("trash", 13.0, 9.9, 0), ("stool", 19.0, 15.0, 0),
	]
	props = [{"id": f"p{i}", "type": t_, "x": x, "z": z, "ry": round(ry, 4)} for i, (t_, x, z, ry) in enumerate(P)]
	return {
		"name": "집",
		"w": W, "d": D, "wall_h": WALL_H,
		"walls": [{"x": x, "z": z, "w": w, "d": d} for x, z, w, d in walls],
		"rooms": [{"name": "거실", "x": 0, "z": 0, "w": 12, "d": 16}, {"name": "부엌", "x": 12, "z": 0, "w": 12, "d": 9}, {"name": "침실", "x": 12, "z": 9, "w": 12, "d": 7}],
		"props": props,
		"seeker_spawn": [6.0, 8.0],
		"hider_spawns": [[3, 11], [9, 4], [16, 2], [21, 4], [15, 12], [20, 11], [8, 15], [10.5, 8]],
	}


MAP = _house()
PROP_BY_ID = {p["id"]: p for p in MAP["props"]}


def _dist(a, b):
	return math.hypot(a[0] - b[0], a[1] - b[1])


class HideSeekLogic:
	kind = "hideseek"

	def __init__(self, rng=None):
		self.rng = rng or random.Random()
		self.players = {}   # pid → {name, role, alive, hp, eid, prop, x, z, ry, last_pos, last_shot}
		self.order = []
		self.host = None
		self.hide_time = 30
		self.seek_time = 180
		self.seats = {}     # 방 목록 '빈 자리' 계산용 (자리 개념 없음)
		self.round = 0
		self.seeker_idx = -1
		self.status = "lobby"     # lobby / hide / seek / over
		self.until = 0.0
		self.next_taunt = 0.0
		self.result = None

	# ── 공통 훅 ──
	def seat_of(self, pid):
		p = self.players.get(pid)
		if not p:
			return None
		return p["role"] or "player"

	def on_join(self, room, peer):
		p = self.players.get(peer.pid)
		if p:
			p["name"] = peer.name
		elif len(self.players) < MAX_PLAYERS:
			self.players[peer.pid] = self._new_player(peer.name)
			self.order.append(peer.pid)
			if not self.host:
				self.host = peer.pid
		room.emit({"type": "map", "map": MAP, "props": {k: list(v) for k, v in PROPS.items()}, "speed": SPEED}, to=peer.pid)

	def _new_player(self, name):
		return {"name": name, "role": None, "alive": True, "hp": 0, "eid": None, "prop": "box", "x": 0.0, "z": 0.0, "ry": 0.0, "last_pos": 0.0, "last_shot": 0.0}

	def on_leave(self, room, pid):
		p = self.players.pop(pid, None)
		if not p:
			return None
		self.order.remove(pid)
		if self.host == pid:
			self.host = self.order[0] if self.order else None
		if self.status in ("hide", "seek"):
			if p["role"] == "seeker":
				self._finish(room, "hiders", "술래가 나가서 숨는 쪽이 이겼어요.")
			elif not self._alive_hiders():
				self._finish(room, "seeker", "숨는 사람이 아무도 안 남았어요.")
		return f"{p['name']} 님이 게임에서 빠졌어요."

	# ── 진행 ──
	def _alive_hiders(self):
		return [pid for pid, p in self.players.items() if p["role"] == "hider" and p["alive"]]

	def _seeker(self):
		return next((pid for pid, p in self.players.items() if p["role"] == "seeker"), None)

	def _start(self, room, now):
		self.round += 1
		self.seeker_idx = (self.seeker_idx + 1) % len(self.order)
		seeker = self.order[self.seeker_idx]
		spawns = list(MAP["hider_spawns"])
		self.rng.shuffle(spawns)
		props = [k for k in PROPS if k not in ("bed", "sofa", "fridge")]
		used_eids = set()
		for i, pid in enumerate(self.order):
			p = self.players[pid]
			p.update(alive=True, last_pos=now, last_shot=0.0)   # 첫 위치도 시작 뒤 걸린 시간만큼만 움직일 수 있게
			if pid == seeker:
				p.update(role="seeker", hp=SEEKER_HP, eid=None, x=MAP["seeker_spawn"][0], z=MAP["seeker_spawn"][1], ry=0.0)
			else:
				eid = "e" + secrets.token_hex(3)
				while eid in used_eids:
					eid = "e" + secrets.token_hex(3)
				used_eids.add(eid)
				sx, sz = spawns[i % len(spawns)]
				p.update(role="hider", hp=HIDER_HP, eid=eid, prop=self.rng.choice(props), x=float(sx), z=float(sz), ry=0.0)
		self.status, self.until = "hide", now + self.hide_time
		self.result = None
		room.emit({"type": "round", "round": self.round})
		room.notice(f"🫥 {self.round}판 시작! 술래는 {self.players[seeker]['name']} 님 — {self.hide_time}초 동안 숨으세요.")

	def _finish(self, room, winner, reason):
		self.status = "over"
		self.until = 0.0
		caught = [self.players[pid]["name"] for pid in self.order if self.players[pid]["role"] == "hider" and not self.players[pid]["alive"]]
		alive = [self.players[pid]["name"] for pid in self._alive_hiders()]
		self.result = {"winner": winner, "reason": reason, "caught": caught, "alive": alive}
		room.notice(f"🏁 {reason}")
		room.emit({"type": "over", "winner": winner, "reason": reason})

	def tick(self, room, now):
		if self.status == "hide" and now >= self.until:
			self.status, self.until = "seek", now + self.seek_time
			self.next_taunt = now + TAUNT_EVERY
			room.notice("👀 술래가 눈을 떴어요! 찾기 시작.")
			return True
		if self.status == "seek":
			if now >= self.until:
				self._finish(room, "hiders", f"시간 끝! 숨은 사람 {len(self._alive_hiders())}명이 살아남았어요.")
				return True
			if now >= self.next_taunt:
				self.next_taunt = now + TAUNT_EVERY
				pts = [[round(self.players[pid]["x"], 2), round(self.players[pid]["z"], 2)] for pid in self._alive_hiders()]
				if pts:
					room.emit({"type": "taunt", "pts": pts})
		return False

	# ── 메시지 ──
	def on_message(self, room, peer, data):
		kind = data.get("type")
		now = time.time()
		p = self.players.get(peer.pid)
		if p is None:
			return False, "구경 중이에요 (최대 8명)."
		is_host = peer.pid == self.host

		if kind == "pos":
			return self._on_pos(room, peer.pid, p, data, now)

		if kind == "settings":
			if not is_host or self.status not in ("lobby", "over"):
				return False, "방장만, 판이 없을 때 바꿀 수 있어요."
			hide, seek = data.get("hide"), data.get("seek")
			if hide in HIDE_CHOICES:
				self.hide_time = hide
			if seek in SEEK_CHOICES:
				self.seek_time = seek
			return True, None

		if kind == "start":
			if not is_host:
				return False, "방장만 시작할 수 있어요."
			if self.status in ("hide", "seek"):
				return False, "이미 하고 있어요."
			if len(self.players) < 2:
				return False, "2명 이상이어야 해요."
			self._start(room, now)
			return True, None

		if kind == "disguise":
			if p["role"] != "hider" or not p["alive"] or self.status not in ("hide", "seek"):
				return False, None
			prop = data.get("prop")
			if prop not in PROPS:
				return False, "모르는 물건이에요."
			# 보고 있는 진짜 물건을 따라 하는 것 → 그 물건 가까이 있어야 함
			src = PROP_BY_ID.get(data.get("from"))
			if src is not None and (src["type"] != prop or _dist((p["x"], p["z"]), (src["x"], src["z"])) > 4.0):
				return False, "너무 멀어요 — 가까이 가서 변신하세요."
			p["prop"] = prop
			room.emit({"type": "disguise", "id": p["eid"], "prop": prop})
			return False, None

		if kind == "shoot":
			return self._on_shoot(room, peer.pid, p, data, now)

		return False, None

	def _on_pos(self, room, pid, p, data, now):
		if self.status not in ("hide", "seek") or not p["alive"] or not p["role"]:
			return False, None
		if p["role"] == "seeker" and self.status == "hide":
			return False, None   # 눈 감는 동안은 못 움직임
		if now - p["last_pos"] < POS_MIN_INTERVAL:
			return False, None
		try:
			x, z, ry = float(data.get("x")), float(data.get("z")), float(data.get("ry", 0.0))
		except (TypeError, ValueError):
			return False, None
		if not all(math.isfinite(v) for v in (x, z, ry)):
			return False, None
		x = min(max(x, 0.2), MAP["w"] - 0.2)
		z = min(max(z, 0.2), MAP["d"] - 0.2)
		# 속도 확인: 지난번 위치에서 너무 멀면 갈 수 있는 만큼만
		dt = min(1.0, now - p["last_pos"])
		max_step = SPEED[p["role"]] * dt * 1.5 + 0.4
		d = _dist((x, z), (p["x"], p["z"]))
		fixed = False
		if d > max_step:
			k = max_step / d
			x, z = p["x"] + (x - p["x"]) * k, p["z"] + (z - p["z"]) * k
			fixed = True
		p.update(x=x, z=z, ry=math.remainder(ry, 2 * math.pi), last_pos=now)
		eid = "seeker" if p["role"] == "seeker" else p["eid"]
		room.emit({"type": "pos", "id": eid, "x": round(x, 3), "z": round(z, 3), "ry": round(p["ry"], 3)}, exclude=pid)
		if fixed:
			room.emit({"type": "fix", "x": round(x, 3), "z": round(z, 3)}, to=pid)
		return False, None

	def _on_shoot(self, room, pid, p, data, now):
		if p["role"] != "seeker" or self.status != "seek":
			return False, None
		if now - p["last_shot"] < SHOOT_COOLDOWN:
			return False, None
		p["last_shot"] = now
		target = str(data.get("target") or "")
		me = (p["x"], p["z"])
		hider_pid = next((q for q, h in self.players.items() if h["eid"] == target and h["role"] == "hider" and h["alive"]), None)
		if hider_pid:
			h = self.players[hider_pid]
			pos = (h["x"], h["z"])
		elif target in PROP_BY_ID:
			pr = PROP_BY_ID[target]
			pos = (pr["x"], pr["z"])
		else:
			room.emit({"type": "shot", "hit": None}, to=pid)
			return False, None
		dist = _dist(me, pos)
		# 술래가 보는 방향(ry: 0 = −z 쪽) 과 과녁 방향이 비슷해야 함
		fx, fz = -math.sin(p["ry"]), -math.cos(p["ry"])
		cos = ((pos[0] - me[0]) * fx + (pos[1] - me[1]) * fz) / dist if dist > 0.5 else 1.0
		if dist > SHOOT_RANGE or cos < SHOOT_CONE:
			room.emit({"type": "shot", "hit": None, "why": "far"}, to=pid)
			return False, None
		if hider_pid:
			h["hp"] = max(0, h["hp"] - HIT_DAMAGE)
			room.emit({"type": "hit", "id": target, "hp": h["hp"]})
			if h["hp"] <= 0:
				h["alive"] = False
				room.notice(f"🎯 {h['name']} 님이 잡혔어요! ({self.players[pid]['name']} 님)")
				if not self._alive_hiders():
					self._finish(room, "seeker", f"{self.players[pid]['name']} 님(술래)이 모두 찾았어요!")
			return True, None
		p["hp"] = max(0, p["hp"] - MISS_PENALTY)
		room.emit({"type": "miss", "id": target, "hp": p["hp"]})
		if p["hp"] <= 0:
			self._finish(room, "hiders", "술래가 엉뚱한 물건을 너무 많이 쏴서 쓰러졌어요.")
		return True, None

	# ── 보여 주기 ──
	def snapshot(self, room, pid):
		me = self.players.get(pid)
		viewer_role = me["role"] if me else None
		# 이름은 숨는 사람끼리·잡힌 사람·구경꾼·판이 끝난 뒤에만 (술래는 번호만)
		reveal = self.status in ("over", "lobby") or viewer_role == "hider" or not (me and me["alive"])
		ents = []
		for q in self.order:
			h = self.players[q]
			if h["role"] != "hider" or (not h["alive"] and self.status != "over"):
				continue
			e = {"id": h["eid"], "prop": h["prop"], "x": round(h["x"], 3), "z": round(h["z"], 3), "ry": round(h["ry"], 3), "alive": h["alive"], "hp": h["hp"]}
			if reveal:
				e["name"] = h["name"]
			ents.append(e)
		sk = self._seeker()
		seeker = None
		if sk and self.status in ("hide", "seek", "over"):
			s = self.players[sk]
			seeker = {"name": s["name"], "x": round(s["x"], 3), "z": round(s["z"], 3), "ry": round(s["ry"], 3), "hp": s["hp"]}
		return {
			"status": self.status,
			"left": max(0.0, round(self.until - time.time(), 2)) if self.until else 0,
			"round": self.round,
			"host": pid == self.host,
			"host_name": self.players[self.host]["name"] if self.host in self.players else "",
			"hide_time": self.hide_time, "seek_time": self.seek_time,
			"hide_choices": HIDE_CHOICES, "seek_choices": SEEK_CHOICES,
			"players": [{"name": self.players[q]["name"], "role": self.players[q]["role"], "alive": self.players[q]["alive"], "me": q == pid, "host": q == self.host} for q in self.order],
			"me": None if not me else {"role": me["role"], "alive": me["alive"], "hp": me["hp"], "eid": me["eid"], "prop": me["prop"], "x": me["x"], "z": me["z"], "ry": me["ry"]},
			"ents": ents,
			"seeker": seeker,
			"result": self.result,
			"rules": {"hit": HIT_DAMAGE, "miss": MISS_PENALTY, "taunt": TAUNT_EVERY, "range": SHOOT_RANGE},
		}
