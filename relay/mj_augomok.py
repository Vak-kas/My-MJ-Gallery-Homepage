"""증목 (증강 오목) — 오목 + 사라지는 돌 + 포인트로 뽑는 증강 카드.

규칙
- 15×15, 다섯 개 이상 이으면 승리 (조커 돌은 누구의 줄에도 들어감)
- 내 차례에 '돌 두기' 또는 '증강 뽑기(무작위·골라 사기)' — 뽑으면 그 턴은 끝남
- 돌을 두면 1포인트, 턴 시작 FAST_WINDOW 초 안에 두면 2포인트
- 내 돌은 내 턴 LIFE 번이 지나면 사라짐 (내 턴이 끝날 때마다 남은 턴 -1), GROW_EVERY 턴마다 새 돌 수명 +1
- 손에 든 카드는 내 턴에 한 장 쓰고, 그 턴에 돌도 둘 수 있음 (손은 최대 HAND_MAX 장)
- 무작위 뽑기는 RANDOM_PRICE 포인트, 등급 확률 RARITY_WEIGHTS, PITY 번 연속 영웅 미만이면 다음은 영웅 이상
- 골라 사기는 내 턴마다 진열되는 3장 중 하나, 값은 등급별 PRICE

판 cells: 'x,y' → {o: 'b'|'w'|'n'(중립)|'j'(조커), ttl, by(줄어드는 기준 자리), perm}
"""

import random
import time

SIZE = 15
LIFE = 5
GROW_EVERY = 12  # 이만큼 턴(둘 합쳐)이 지날 때마다 새로 두는 돌이 1턴 더 버팀 → 서로 막기만 하다 판이 끝나지 않는 걸 막음
FAST_WINDOW = 2.0
QUICK_WINDOW = 5.0
HAND_MAX = 3
START_POINTS = 2
RANDOM_PRICE = 4
PITY = 10
RARITIES = ("common", "rare", "epic", "legend", "myth")
RARITY_WEIGHTS = {"common": 50, "rare": 28, "epic": 14, "legend": 6, "myth": 2}
PRICE = {"common": 3, "rare": 6, "epic": 10, "legend": 15, "myth": 22}
RARITY_NAMES = {"common": "일반", "rare": "희귀", "epic": "영웅", "legend": "전설", "myth": "신화"}
BOT_DELAY = 1.1
EVENT_EVERY = 10      # 이만큼 턴(둘 합쳐)마다 중립 이벤트
UNLOCK_PRICE = 3      # 잠긴 구역 해금 값 (턴을 쓰지 않음)
BOT_NAME = "🤖 컴퓨터"

# id: (등급, 아이콘, 이름, 설명, 대상) — 대상: none / own / opp / empty / any / instant
CARDS = {
	"candle": ("common", "🕯", "연장의 촛불", "내 돌 하나가 3턴 더 버텨요", "own"),
	"breeze": ("common", "💨", "산들바람", "상대 돌 하나의 남은 턴 -2", "opp"),
	"piggy": ("common", "🐷", "저금통", "뽑자마자 포인트 +5", "instant"),
	"wall": ("common", "🧱", "벽 세우기", "빈칸에 아무도 못 쓰는 벽 (내 턴 3번)", "empty"),
	"quick": ("common", "⚡", "번개손", "4턴 동안 빠른 두기 시간이 5초로", "none"),
	"hourglass": ("rare", "⏳", "모래시계", "내 돌 모두 2턴 더 버텨요", "none"),
	"gust": ("rare", "🌪", "돌풍", "상대 돌 하나를 날려 버려요", "opp"),
	"twin": ("rare", "👯", "쌍둥이 돌", "이번 턴 한 번 더 둬요 (첫 돌에서 3칸 이상 떨어진 곳)", "none"),
	"chest": ("rare", "🎁", "보물상자", "무작위 증강 한 장을 공짜로", "instant"),
	"eternal": ("epic", "💎", "불멸의 돌", "내 돌 하나가 사라지지 않아요", "own"),
	"eclipse": ("epic", "🌑", "일식", "상대 돌 모두 남은 턴 -1", "none"),
	"chain": ("epic", "🧨", "연쇄 폭발", "상대 돌 하나와 그 둘레 상대 돌 모두 남은 턴 -3", "opp"),
	"rockfall": ("epic", "🪨", "낙석", "상대 돌 근처에 중립돌 3개 (4턴)", "none"),
	"joker": ("legend", "🃏", "조커 돌", "누구의 다섯 줄에도 들어가는 돌 (6턴)", "empty"),
	"double": ("legend", "✌️", "연속 두기", "이번 턴 아무 데나 두 개", "none"),
	"steal": ("legend", "🧲", "강탈", "상대 돌 하나를 내 돌로 (4턴)", "opp"),
	"rewind": ("legend", "⏪", "되감기", "상대가 마지막에 둔 돌 2개를 지워요", "none"),
	"ruler": ("myth", "👑", "돌을 지배하는 자!!!", "상대의 가장 위험한 돌 2개를 내 것으로 + 내 돌 모두 3턴 더", "none"),
	"puppet": ("myth", "🎭", "꼭두각시", "상대의 다음 돌을 내가 고른 칸에 강제로 둬요", "empty"),
	"blackhole": ("myth", "🕳", "블랙홀", "고른 칸 둘레 3×3 의 돌을 모두 삼켜요 (불멸 빼고)", "any"),
	"undo": ("common", "↩️", "무르기 강요", "상대가 마지막에 둔 돌을 물려요", "none"),
	"pickpocket": ("common", "🦝", "소매치기", "상대 포인트 3P를 뺏어 와요", "none"),
	"charity": ("common", "💝", "선행", "상대에게 3P를 주는 대신, 내 돌이 모두 1턴씩 더 버텨요", "none"),
	"compound": ("rare", "📈", "복리", "3턴 동안 돌을 둘 때마다 +1P 더", "none"),
	"saver": ("rare", "🐿", "저축왕", "이 판 내내: 빠르게 두면 2P 대신 3P", "none"),
	"fifth": ("epic", "🔁", "다섯 번째 돌", "이 판 내내: 돌을 5번 둘 때마다 1개 공짜로 더 (2칸 이상 떨어진 곳)", "none"),
	"sturdy": ("legend", "🗿", "단단한 돌", "이 판 내내: 앞으로 두는 내 돌이 1턴 더 버텨요", "none"),
	"together": ("common", "🤝", "동반 성장", "나와 상대 모두 +4P", "none"),
	"famine": ("common", "💸", "공멸", "나와 상대 모두 -4P", "none"),
	"key": ("common", "🗝", "만능 열쇠", "잠긴 칸·봉인된 칸을 모두 풀어요", "none"),
	"memory": ("rare", "🩶", "잿빛 세상", "4턴 동안 두 사람 화면 모두 흑·백 돌이 회색으로 보여요. 돌은 각자 자기 색으로 놓이니 어느 게 내 돌인지 기억하세요!", "none"),
	"seal": ("rare", "🔒", "봉인", "고른 칸 둘레 3×3 빈칸을 4턴 동안 아무도 못 둬요", "any"),
	"dark": ("epic", "🕶", "암흑", "상대의 다음 2턴 동안 상대 화면에 돌이 하나도 안 보여요", "none"),
	"sleep": ("epic", "😴", "수면", "상대가 다음 턴을 한 번 쉬어요", "none"),
	"dice": ("common", "🎲", "행운의 주사위", "주사위 눈에 따라 보상 (1: -2P · 2: +2P · 3: +3P · 4: 일반 카드 · 5: 내 돌 +1턴 · 6: 희귀 이상 카드)", "none"),
	"oracle": ("rare", "🔮", "AI 조언", "3턴 동안 내 화면에 컴퓨터가 계산한 최선의 수가 빛나요", "none"),
	"duel": ("rare", "⚔️", "칸 뺏기 결투", "상대 돌 하나를 걸고 주사위 대결 — 이기면 그 칸을 뺏고, 지면 2P 를 잃어요", "opp"),
	"roulette": ("rare", "🎡", "운명의 룰렛", "대박부터 꽝까지 7칸 룰렛을 돌려요", "none"),
	"stack": ("epic", "🥞", "돌 업기", "3턴씩 동안 둘 다 돌 위에 돌을 올릴 수 있어요 — 내 돌 위면 그 칸이 2개, 상대 돌 위면 그 칸을 뺏어요", "none"),
	"myreset": ("rare", "🔄", "나의 회귀", "내 돌을 모두 거두고 하나에 2P씩 돌려받아요. 내 턴부터 다시", "none"),
	"quake": ("epic", "🌋", "지진", "판 위의 돌 중 무작위 4개가 사라져요 (누구 돌이든, 불멸 빼고)", "none"),
	"grandreset": ("myth", "⏮", "대회귀", "판 전체를 처음으로 되돌려요. 내 턴부터 다시 시작", "none"),
}
BY_RARITY = {r: [k for k, v in CARDS.items() if v[0] == r] for r in RARITIES}
DIRS = ((1, 0), (0, 1), (1, 1), (1, -1))


# 지속(N턴)·영구(이 판 내내) 카드 — 나머지는 1회용
TIMED = {"quick": 4, "compound": 3, "memory": 4, "seal": 4, "dark": 2, "oracle": 3, "stack": 3}
ROULETTE = [  # (확률 가중치, 아이콘, 이름)
	(25, "💰", "+6P"),
	(20, "🌪", "상대 돌 무작위 2개 날림"),
	(15, "⏳", "내 돌 모두 +2턴"),
	(15, "💀", "내 돌 무작위 2개 사라짐"),
	(10, "😴", "내가 다음 턴 쉼"),
	(10, "🫥", "꽝 — 아무 일도 없음"),
	(5, "🌟", "전설 증강 1장"),
]
PERMANENT = {"saver", "fifth", "sturdy"}


def card_info(cid):
	r, icon, name, desc, target = CARDS[cid]
	dur = "영구" if cid in PERMANENT else f"지속 {TIMED[cid]}턴" if cid in TIMED else "즉시" if target == "instant" else "1회용"
	return {"id": cid, "rarity": r, "icon": icon, "name": name, "desc": desc, "target": target, "price": PRICE[r], "dur": dur}


class AugOmokLogic:
	kind = "augomok"
	SEATS = ("black", "white")

	def __init__(self, rng=None):
		self.rng = rng or random.Random()
		self.seats = {"black": None, "white": None}
		self.names = {"black": "", "white": ""}
		self.bots = set()
		self.wins = {"black": 0, "white": 0}
		self.life = LIFE
		self.events_on = True
		self.starter = "black"
		self.reset()

	def reset(self):
		self.cells = {}
		self.status = "waiting"
		self.turn = None
		self.turn_started = 0.0
		self.winner = None
		self.win_line = []
		self.reason = ""
		self.points = {s: START_POINTS for s in self.SEATS}
		self.hand = {s: [] for s in self.SEATS}
		self.shop = {s: [] for s in self.SEATS}
		self.pity = {s: 0 for s in self.SEATS}
		self.quick = {s: 0 for s in self.SEATS}   # 번개손 남은 턴
		self.timed = {s: {} for s in self.SEATS}  # 지속 효과 → 남은 턴 (복리 등)
		self.passives = {s: [] for s in self.SEATS}  # 영구 효과 (이 판 내내)
		self.place_count = {s: 0 for s in self.SEATS}
		self.bonus_now = False
		self.dark = {s: 0 for s in self.SEATS}    # 암흑: 이 자리 화면에 돌이 안 보이는 남은 턴 (그 자리 턴 기준)
		self.memory = 0                            # 잿빛 세상: 모든 돌이 회색으로 보이는 남은 턴 (둘 합쳐)
		self.skip = set()                          # 다음 턴을 쉬는 자리
		self.locks = {}
		self.stack_turns = 0                       # 돌 업기: 남은 턴 (둘 합쳐)                            # 'x,y' → {'kind': 'seal'|'lock', 'ttl': n, 'region': id}
		self.next_region = 1
		self.used_card = False                     # 이번 턴에 카드 썼는지
		self.extra = None                          # {'left': n, 'min_dist': d, 'first': [x, y]}
		self.forced = None                         # {'seat': 상대, 'cell': [x, y]}
		self.placed = {s: [] for s in self.SEATS}  # 둔 순서 (되감기)
		self.turns = 0
		self.last = None
		self.bot_due = 0.0

	def current_life(self):
		return self.life + self.turns // GROW_EVERY

	# ── 공통 ──
	def seat_of(self, pid):
		return next((s for s, p in self.seats.items() if p == pid and s not in self.bots), None)

	def other(self, s):
		return "white" if s == "black" else "black"

	def color(self, s):
		return s[0]

	@staticmethod
	def key(x, y):
		return f"{x},{y}"

	def at(self, x, y):
		return self.cells.get(self.key(x, y))

	def empty(self, x, y):
		k = self.key(x, y)
		return 0 <= x < SIZE and 0 <= y < SIZE and k not in self.cells and k not in self.locks

	def stones_of(self, s):
		c = self.color(s)
		return [(k, v) for k, v in self.cells.items() if v["o"] == c]

	def _counts_for(self, cell, c):
		return cell is not None and (cell["o"] == c or cell["o"] == "j")

	def _line(self, x, y, c):
		"""(x, y) 를 지나는 가장 긴 줄의 칸 목록 (c 돌 + 조커)."""
		best = []
		for dx, dy in DIRS:
			line = [(x, y)]
			for sign in (1, -1):
				nx, ny = x + dx * sign, y + dy * sign
				while 0 <= nx < SIZE and 0 <= ny < SIZE and self._counts_for(self.at(nx, ny), c):
					line.append((nx, ny))
					nx, ny = nx + dx * sign, ny + dy * sign
			if len(line) > len(best):
				best = line
		return best

	def _weight(self, line):
		"""줄의 돌 수 — 돌 업기로 2개가 된 칸은 2로 셈."""
		return sum((self.at(x, y) or {}).get("h", 1) for x, y in line)

	def _check_win(self, room, s):
		c = self.color(s)
		for k, v in list(self.cells.items()):
			if v["o"] != c:
				continue
			x, y = map(int, k.split(","))
			line = self._line(x, y, c)
			if self._weight(line) >= 5:
				self._finish(room, s, f"{self.names[s]} 님이 다섯 줄을 완성했어요!", sorted(line))
				return True
		return False

	def _finish(self, room, winner, reason, line=None):
		self.status = "over"
		self.turn = None
		self.extra = None
		self.winner = winner
		self.win_line = [list(p) for p in (line or [])]
		self.reason = reason
		if winner:
			self.wins[winner] += 1
		room.notice(f"🏁 {reason}")

	# ── 돌 두기 ──
	def _place(self, room, s, x, y, *, forced=False):
		life = self.current_life() + (1 if "sturdy" in self.passives[s] else 0)
		self.cells[self.key(x, y)] = {"o": self.color(s), "ttl": life, "by": s, "perm": False}
		self.placed[s].append([x, y])
		self.last = {"type": "place", "seat": s, "cell": [x, y], "forced": forced}
		if not forced:
			window = QUICK_WINDOW if self.quick[s] else FAST_WINDOW
			fast = time.time() - self.turn_started <= window
			gain = (3 if "saver" in self.passives[s] else 2) if fast else 1
			if self.timed[s].get("compound"):
				gain += 1
			self.place_count[s] += 1
			# 다섯 번째 돌: 5번 둘 때마다 1개 공짜 (이미 한 번 더 두는 중이면 다음으로 미루지 않음)
			if "fifth" in self.passives[s] and self.place_count[s] % 5 == 0 and not self.extra:
				self.bonus_now = True
			self.points[s] += gain
			self.last["gain"] = gain
			self.last["fast"] = fast
		return self._check_win(room, s)

	def _end_turn(self, room):
		s = self.turn
		# 이 자리가 만든 돌·벽·조커의 남은 턴 줄이기
		gone = []
		for k, v in list(self.cells.items()):
			if v["by"] == s and not v["perm"]:
				v["ttl"] -= 1
				if v["ttl"] <= 0:
					gone.append(k)
					del self.cells[k]
		if self.quick[s]:
			self.quick[s] -= 1
		for name in list(self.timed[s]):
			self.timed[s][name] -= 1
			if self.timed[s][name] <= 0:
				del self.timed[s][name]
		if self.dark[s]:
			self.dark[s] -= 1
		if self.memory:
			self.memory -= 1
		if self.stack_turns:
			self.stack_turns -= 1
		for k, lk in list(self.locks.items()):
			if lk["kind"] == "seal":
				lk["ttl"] -= 1
				if lk["ttl"] <= 0:
					del self.locks[k]
		self.turns += 1
		self.extra = None
		self.used_card = False
		if self.events_on and self.turns % EVENT_EVERY == 0:
			self._event(room)
			if self.status != "playing":
				return
		if gone:
			room.emit({"type": "fade", "cells": gone})
		if len(self.cells) >= SIZE * SIZE:
			self._finish(room, None, "판이 가득 찼어요. 무승부!")
			return
		nxt = self.other(s)
		self.turn = nxt
		self.turn_started = time.time()
		self._restock(nxt)
		if nxt in self.skip:  # 수면: 이번 턴은 쉼 (돌은 그대로 나이 먹음)
			self.skip.discard(nxt)
			room.notice(f"😴 {self.names[nxt]} 님은 이번 턴을 쉬어요.")
			room.emit({"type": "event", "icon": "😴", "name": "쿨쿨…", "desc": f"{self.names[nxt]} 님이 한 턴 쉬어요"})
			self._end_turn(room)
			return
		# 꼭두각시: 상대 차례가 오자마자 정해진 칸에 강제로
		if self.forced and self.forced["seat"] == nxt:
			fx, fy = self.forced["cell"]
			self.forced = None
			if self.empty(fx, fy):
				room.notice(f"🎭 꼭두각시! {self.names[nxt]} 님의 돌이 강제로 놓였어요.")
				room.emit({"type": "puppet", "cell": [fx, fy]})
				if self._place(room, nxt, fx, fy, forced=True):
					return
				self._end_turn(room)
				return
		self._arm_bot()

	def _restock(self, s):
		"""진열 3장 (서로 다른 카드로)."""
		shop = []
		for _ in range(30):
			cid = self._roll(s, count_pity=False)
			if cid not in shop:
				shop.append(cid)
			if len(shop) == 3:
				break
		self.shop[s] = shop

	def _roll(self, s, count_pity=True):
		rarity = self.rng.choices(RARITIES, weights=[RARITY_WEIGHTS[r] for r in RARITIES])[0]
		if count_pity:
			if self.pity[s] >= PITY - 1 and RARITIES.index(rarity) < 2:
				rarity = self.rng.choices(("epic", "legend", "myth"), weights=(70, 24, 6))[0]
			self.pity[s] = 0 if RARITIES.index(rarity) >= 2 else self.pity[s] + 1
		return self.rng.choice(BY_RARITY[rarity])

	def _gain_card(self, room, s, cid, how):
		info = card_info(cid)
		# 누가 뽑든 모두의 화면에 같은 연출 (카드 이름까지)
		room.emit({"type": "draw", "seat": s, "how": how, "rarity": info["rarity"], "card": info})
		if CARDS[cid][4] == "instant":
			self._instant(room, s, cid)
			return
		self.hand[s].append(cid)
		if info["rarity"] in ("legend", "myth"):
			room.notice(f"{'🌈' if info['rarity'] == 'myth' else '🌟'} {self.names[s]} 님이 {RARITY_NAMES[info['rarity']]} 증강 '{info['name']}' 을(를) 손에 넣었어요!")

	def _instant(self, room, s, cid):
		if cid == "piggy":
			self.points[s] += 5
			room.notice(f"🐷 {self.names[s]} 님 저금통 +5포인트!")
		elif cid == "chest":
			room.notice(f"🎁 {self.names[s]} 님이 보물상자를 열었어요!")
			if len(self.hand[s]) < HAND_MAX:
				self._gain_card(room, s, self._roll(s, count_pity=False), "chest")

	# ── 중립 이벤트 (EVENT_EVERY 턴마다) ──
	EVENTS = {
		"acid": ("🌧", "산성비", "모든 돌(불멸 빼고)이 1턴씩 줄어요"),
		"supply": ("🎁", "보급품", "둘 다 +3P"),
		"aftershock": ("🌋", "여진", "판 위의 돌 2개가 무작위로 사라져요"),
		"meteor": ("☄️", "운석", "빈칸 2곳에 중립돌 (4턴)"),
		"vault": ("🔐", "금고", f"무작위 3×3 구역이 잠겨요 — {UNLOCK_PRICE}P 로 해금"),
		"fog": ("🌫", "안개", "2턴 동안 모든 돌이 회색으로"),
		"luck": ("✨", "행운", "둘 다 무작위 일반 증강 1장"),
	}

	def _event(self, room):
		eid = self.rng.choice(list(self.EVENTS))
		icon, name, desc = self.EVENTS[eid]
		cells = []
		empties = [(x, y) for x in range(SIZE) for y in range(SIZE) if self.empty(x, y)]
		if eid == "acid":
			for k, v in list(self.cells.items()):
				if not v["perm"]:
					v["ttl"] -= 1
					cells.append(list(map(int, k.split(","))))
					if v["ttl"] <= 0:
						del self.cells[k]
		elif eid == "supply":
			for x in self.SEATS:
				self.points[x] += 3
		elif eid == "aftershock":
			pool = [k for k, v in self.cells.items() if not v["perm"]]
			for k in self.rng.sample(pool, min(2, len(pool))):
				del self.cells[k]
				cells.append(list(map(int, k.split(","))))
		elif eid == "meteor":
			for x, y in self.rng.sample(empties, min(2, len(empties))):
				self.cells[self.key(x, y)] = {"o": "n", "ttl": 4, "by": self.turn, "perm": False}
				cells.append([x, y])
		elif eid == "vault":
			cx, cy = self.rng.randrange(1, SIZE - 1), self.rng.randrange(1, SIZE - 1)
			rid = self.next_region
			self.next_region += 1
			for dx in (-1, 0, 1):
				for dy in (-1, 0, 1):
					k = self.key(cx + dx, cy + dy)
					if k not in self.cells:
						self.locks[k] = {"kind": "lock", "ttl": 0, "region": rid}
						cells.append([cx + dx, cy + dy])
		elif eid == "fog":
			self.memory = max(self.memory, 2)
		elif eid == "luck":
			for x in self.SEATS:
				if len(self.hand[x]) < HAND_MAX:
					self.hand[x].append(self.rng.choice(BY_RARITY["common"]))
		room.notice(f"{icon} 중립 이벤트 — {name}: {desc}")
		room.emit({"type": "event", "icon": icon, "name": name, "desc": desc, "cells": cells})

	def _act_unlock(self, room, seat, x, y):
		lk = self.locks.get(self.key(x, y))
		if not lk or lk["kind"] != "lock":
			return False, "잠긴 칸이 아니에요." if not lk else "봉인은 시간이 지나야 풀려요. (만능 열쇠로는 풀 수 있어요)"
		if self.points[seat] < UNLOCK_PRICE:
			return False, f"해금하려면 {UNLOCK_PRICE}P 가 필요해요."
		self.points[seat] -= UNLOCK_PRICE
		cells = [k for k, v in self.locks.items() if v["kind"] == "lock" and v["region"] == lk["region"]]
		for k in cells:
			del self.locks[k]
		room.notice(f"🗝 {self.names[seat]} 님이 {UNLOCK_PRICE}P 로 금고를 해금했어요.")
		room.emit({"type": "event", "icon": "🗝", "name": "해금!", "desc": f"{self.names[seat]} 님이 잠긴 구역을 열었어요",
				   "cells": [list(map(int, k.split(","))) for k in cells]})
		return True, None

	# ── 카드 쓰기 ──
	def _danger_stones(self, s, n):
		"""s 의 돌 중 가장 긴 줄에 속한 돌부터 n 개."""
		c = self.color(s)
		scored = []
		for k, v in self.cells.items():
			if v["o"] != c:
				continue
			x, y = map(int, k.split(","))
			scored.append((len(self._line(x, y, c)), self.rng.random(), k))
		scored.sort(reverse=True)
		return [k for _, _, k in scored[:n]]

	def _use(self, room, s, cid, target):
		o = self.other(s)
		kind = CARDS[cid][4]
		cell = None
		if kind in ("own", "opp", "empty", "any"):
			try:
				tx, ty = int(target[0]), int(target[1])
			except (TypeError, ValueError, IndexError):
				return "칸을 골라 주세요."
			if not (0 <= tx < SIZE and 0 <= ty < SIZE):
				return "판 안을 골라 주세요."
			cell = self.at(tx, ty)
			if kind == "own" and not (cell and cell["o"] == self.color(s)):
				return "내 돌을 골라 주세요."
			if kind == "opp" and not (cell and cell["o"] == self.color(o)):
				return "상대 돌을 골라 주세요."
			if kind == "empty" and (cell or self.key(tx, ty) in self.locks):
				return "빈칸(잠기지 않은)을 골라 주세요."
		if cid in ("twin", "double") and self.extra:
			return "이미 한 번 더 두기를 쓰는 중이에요."
		# 효과
		affected = []
		if cid == "candle":
			cell["ttl"] += 3
			affected = [[tx, ty]]
		elif cid == "breeze":
			cell["ttl"] -= 2
			affected = [[tx, ty]]
		elif cid == "wall":
			self.cells[self.key(tx, ty)] = {"o": "n", "ttl": 3, "by": s, "perm": False}
			affected = [[tx, ty]]
		elif cid == "quick":
			self.quick[s] = 4
			self.turn_started = time.time()  # 지금부터 5초
		elif cid == "hourglass":
			for k, v in self.stones_of(s):
				v["ttl"] += 2
				affected.append(list(map(int, k.split(","))))
		elif cid == "gust":
			del self.cells[self.key(tx, ty)]
			affected = [[tx, ty]]
		elif cid == "twin":
			self.extra = {"left": 1, "min_dist": 3, "first": None}
		elif cid == "eternal":
			cell["perm"] = True
			affected = [[tx, ty]]
		elif cid == "eclipse":
			for k, v in self.stones_of(o):
				if not v["perm"]:
					v["ttl"] -= 1
					affected.append(list(map(int, k.split(","))))
		elif cid == "chain":
			for dx in (-1, 0, 1):
				for dy in (-1, 0, 1):
					c2 = self.at(tx + dx, ty + dy)
					if c2 and c2["o"] == self.color(o) and not c2["perm"]:
						c2["ttl"] -= 3
						affected.append([tx + dx, ty + dy])
		elif cid == "rockfall":
			near = set()
			for k, _ in self.stones_of(o):
				x, y = map(int, k.split(","))
				for dx in range(-2, 3):
					for dy in range(-2, 3):
						if self.empty(x + dx, y + dy):
							near.add((x + dx, y + dy))
			pool = list(near) or [(x, y) for x in range(SIZE) for y in range(SIZE) if self.empty(x, y)]
			for x, y in self.rng.sample(pool, min(3, len(pool))):
				self.cells[self.key(x, y)] = {"o": "n", "ttl": 4, "by": s, "perm": False}
				affected.append([x, y])
		elif cid == "joker":
			self.cells[self.key(tx, ty)] = {"o": "j", "ttl": 6, "by": s, "perm": False}
			affected = [[tx, ty]]
		elif cid == "double":
			self.extra = {"left": 1, "min_dist": 0, "first": None}
		elif cid == "steal":
			cell.update(o=self.color(s), ttl=4, by=s, perm=False)
			affected = [[tx, ty]]
		elif cid == "rewind":
			for x, y in self.placed[o][-2:]:
				c2 = self.at(x, y)
				if c2 and c2["o"] == self.color(o) and not c2["perm"]:
					del self.cells[self.key(x, y)]
					affected.append([x, y])
			self.placed[o] = self.placed[o][:-2]
		elif cid == "ruler":
			for k in self._danger_stones(o, 2):
				self.cells[k].update(o=self.color(s), ttl=4, by=s, perm=False)
				affected.append(list(map(int, k.split(","))))
			for k, v in self.stones_of(s):
				v["ttl"] += 3
		elif cid == "puppet":
			self.forced = {"seat": o, "cell": [tx, ty]}
			affected = [[tx, ty]]
		elif cid == "blackhole":
			for dx in (-1, 0, 1):
				for dy in (-1, 0, 1):
					k = self.key(tx + dx, ty + dy)
					if k in self.cells and not self.cells[k]["perm"]:
						del self.cells[k]
						affected.append([tx + dx, ty + dy])
		elif cid == "undo":
			while self.placed[o]:
				x, y = self.placed[o].pop()
				c2 = self.at(x, y)
				if c2 and c2["o"] == self.color(o) and not c2["perm"]:
					del self.cells[self.key(x, y)]
					affected = [[x, y]]
					break
		elif cid == "pickpocket":
			got = min(3, self.points[o])
			self.points[o] -= got
			self.points[s] += got
		elif cid == "charity":
			give = min(3, self.points[s])
			self.points[s] -= give
			self.points[o] += give
			for k, v in self.stones_of(s):
				v["ttl"] += 1
				affected.append(list(map(int, k.split(","))))
		elif cid == "compound":
			self.timed[s]["compound"] = TIMED["compound"]
		elif cid in PERMANENT:
			if cid in self.passives[s]:
				return "이미 켜져 있는 영구 효과예요."
			self.passives[s].append(cid)
		elif cid == "dice":
			roll = self.rng.randint(1, 6)
			text = {1: "-2P", 2: "+2P", 3: "+3P", 4: "일반 증강 1장", 5: "내 돌 모두 +1턴", 6: "희귀 이상 증강 1장"}[roll]
			if roll == 1:
				self.points[s] = max(0, self.points[s] - 2)
			elif roll in (2, 3):
				self.points[s] += roll
			elif roll == 4 and len(self.hand[s]) < HAND_MAX:
				self.hand[s].append(self.rng.choice(BY_RARITY["common"]))
			elif roll == 5:
				for k, v in self.stones_of(s):
					v["ttl"] += 1
			elif roll == 6 and len(self.hand[s]) < HAND_MAX:
				r = self.rng.choices(("rare", "epic", "legend", "myth"), weights=(55, 28, 13, 4))[0]
				self.hand[s].append(self.rng.choice(BY_RARITY[r]))
			room.emit({"type": "dice", "kind": "luck", "seat": s, "rolls": {s: roll}, "text": text})
			room.notice(f"🎲 {self.names[s]} 님 주사위 {roll} → {text}")
		elif cid == "oracle":
			self.timed[s]["oracle"] = TIMED["oracle"]
		elif cid == "duel":
			a, b = self.rng.randint(1, 6), self.rng.randint(1, 6)
			if a > b:
				cell.update(o=self.color(s), by=s, ttl=self.current_life(), perm=False, h=1)
				text = f"승리! 그 칸을 뺏었어요"
				affected = [[tx, ty]]
			elif a < b:
				self.points[s] = max(0, self.points[s] - 2)
				text = "패배… 2P 를 잃었어요"
			else:
				text = "비김 — 아무 일도 없어요"
			room.emit({"type": "dice", "kind": "duel", "seat": s, "rolls": {s: a, o: b}, "text": text, "cell": [tx, ty]})
			room.notice(f"⚔️ 칸 뺏기 결투: {self.names[s]} {a} vs {self.names[o]} {b} → {text}")
		elif cid == "roulette":
			i = self.rng.choices(range(len(ROULETTE)), weights=[w for w, _, _ in ROULETTE])[0]
			icon, label = ROULETTE[i][1], ROULETTE[i][2]
			if i == 0:
				self.points[s] += 6
			elif i in (1, 3):
				who = o if i == 1 else s
				pool = [k for k, v in self.stones_of(who) if not v["perm"]]
				for k in self.rng.sample(pool, min(2, len(pool))):
					del self.cells[k]
					affected.append(list(map(int, k.split(","))))
			elif i == 2:
				for k, v in self.stones_of(s):
					v["ttl"] += 2
			elif i == 4:
				self.skip.add(s)
			elif i == 6 and len(self.hand[s]) < HAND_MAX:
				self.hand[s].append(self.rng.choice(BY_RARITY["legend"]))
			room.emit({"type": "roulette", "seat": s, "index": i, "slots": [[ic, lb] for _, ic, lb in ROULETTE]})
			room.notice(f"🎡 {self.names[s]} 님 룰렛 → {icon} {label}")
		elif cid == "stack":
			self.stack_turns = TIMED["stack"] * 2
		elif cid == "together":
			for x in self.SEATS:
				self.points[x] += 4
		elif cid == "famine":
			for x in self.SEATS:
				self.points[x] = max(0, self.points[x] - 4)
		elif cid == "key":
			affected = [list(map(int, k.split(","))) for k in self.locks]
			self.locks.clear()
		elif cid == "memory":
			self.memory = TIMED["memory"]
		elif cid == "seal":
			for dx in (-1, 0, 1):
				for dy in (-1, 0, 1):
					x, y = tx + dx, ty + dy
					if 0 <= x < SIZE and 0 <= y < SIZE and self.key(x, y) not in self.cells:
						self.locks[self.key(x, y)] = {"kind": "seal", "ttl": TIMED["seal"], "region": 0}
						affected.append([x, y])
		elif cid == "dark":
			self.dark[o] = TIMED["dark"]
		elif cid == "sleep":
			self.skip.add(o)
		elif cid == "quake":
			pool = [k for k, v in self.cells.items() if not v["perm"]]
			for k in self.rng.sample(pool, min(4, len(pool))):
				del self.cells[k]
				affected.append(list(map(int, k.split(","))))
		elif cid == "myreset":
			mine = [k for k, v in self.stones_of(s) if not v["perm"]]
			for k in mine:
				del self.cells[k]
				affected.append(list(map(int, k.split(","))))
			self.points[s] += 2 * len(mine)
			self.placed[s] = []
			self.turn_started = time.time()  # 내 턴부터 다시 (빠른 두기도 다시)
		elif cid == "grandreset":
			affected = [list(map(int, k.split(","))) for k in self.cells]
			self.cells.clear()
			self.placed = {x: [] for x in self.SEATS}
			self.forced = None
			self.turn_started = time.time()
		# 남은 턴이 0 이하가 된 돌은 바로 사라짐
		for k, v in list(self.cells.items()):
			if v["ttl"] <= 0 and not v["perm"]:
				del self.cells[k]
		self.hand[s].remove(cid)
		self.used_card = True
		info = card_info(cid)
		self.last = {"type": "use", "seat": s, "card": cid, "cells": affected}
		room.emit({"type": "use", "seat": s, "card": info, "cells": affected, "target": [tx, ty] if cell is not None or kind in ("empty", "any") else None})
		room.notice(f"{info['icon']} {self.names[s]} 님이 '{info['name']}' 을(를) 썼어요!" + (" (신화)" if info["rarity"] == "myth" else ""))
		# 내 돌이 늘어난 카드(강탈·지배자)는 바로 다섯 줄 확인
		if cid in ("steal", "ruler", "joker", "duel"):
			self._check_win(room, s)
		return None

	# ── 메시지 ──
	def on_message(self, room, peer, data):
		kind = data.get("type")
		seat = self.seat_of(peer.pid)
		if kind == "sit":
			if seat:
				return False, "이미 앉아 있어요."
			if self.status == "playing":
				return False, "판이 진행 중이에요. 끝나면 앉을 수 있어요."
			free = [s for s in self.SEATS if not self.seats[s]]
			want = data.get("seat")
			target = want if want in free else (free[0] if free and want in (None, "any") else None)
			if not target:
				return False, "빈 자리가 없어요."
			self.seats[target], self.names[target] = peer.pid, peer.name
			room.notice(f"{peer.name} 님이 {'흑' if target == 'black' else '백'}으로 앉았어요.")
			return True, None
		if kind == "stand":
			if not seat or self.status == "playing":
				return False, "판이 진행 중이에요. 그만하려면 기권하세요." if seat else None
			self.seats[seat], self.names[seat] = None, ""
			room.notice(f"{peer.name} 님이 자리에서 일어났어요.")
			return True, None
		if kind == "add-bot":
			free = [s for s in self.SEATS if not self.seats[s]]
			if not seat or self.status == "playing" or not free:
				return False, "먼저 자리에 앉으세요." if not seat else None
			s = free[0]
			self.seats[s], self.names[s] = f"bot:{s}", BOT_NAME
			self.bots.add(s)
			room.notice("🤖 컴퓨터가 들어왔어요.")
			return True, None
		if kind == "remove-bot":
			s = data.get("seat")
			if not seat or s not in self.bots or self.status == "playing":
				return False, None
			self.bots.discard(s)
			self.seats[s], self.names[s] = None, ""
			return True, None
		if kind == "options":
			if not seat or self.status == "playing":
				return False, None
			if data.get("life") in (5, 7, 9):
				self.life = data["life"]
			if isinstance(data.get("events"), bool):
				self.events_on = data["events"]
			self.reset()
			return True, None
		if kind in ("start", "rematch"):
			if not seat or self.status == "playing":
				return False, None
			if not all(self.seats.values()):
				return False, "상대가 있어야 시작해요. 컴퓨터를 넣어도 돼요."
			self.reset()
			self.status = "playing"
			self.turn = self.starter
			self.starter = self.other(self.starter)
			self.turn_started = time.time()
			self._restock(self.turn)
			self._arm_bot()
			room.notice(f"증목 시작! {self.names[self.turn]} 님부터. 돌은 내 턴 {self.life}번 뒤에 사라져요.")
			return True, None
		if self.status != "playing" and kind in ("move", "draw", "buy", "use", "unlock"):
			return False, "아직 판이 시작되지 않았어요."
		if kind in ("move", "draw", "buy", "use", "unlock") and seat != self.turn:
			return False, "내 차례가 아니에요." if seat else "구경 중이에요."
		if kind == "move":
			try:
				x, y = int(data.get("x")), int(data.get("y"))
			except (TypeError, ValueError):
				return False, None
			return self._act_move(room, seat, x, y)
		if kind == "draw":
			return self._act_draw(room, seat)
		if kind == "unlock":
			try:
				return self._act_unlock(room, seat, int(data.get("x")), int(data.get("y")))
			except (TypeError, ValueError):
				return False, None
		if kind == "buy":
			try:
				i = int(data.get("slot"))
			except (TypeError, ValueError):
				return False, None
			return self._act_buy(room, seat, i)
		if kind == "use":
			if self.used_card:
				return False, "카드는 한 턴에 한 장만 쓸 수 있어요."
			cid = data.get("card")
			if cid not in self.hand[seat]:
				return False, "손에 없는 카드예요."
			err = self._use(room, seat, cid, data.get("target") or [])
			if err:
				return False, err
			return True, None
		if kind == "resign":
			if self.status != "playing" or not seat:
				return False, None
			self._finish(room, self.other(seat), f"{self.names[seat]} 님이 기권했어요.")
			return True, None
		return False, None

	# ── 행동 (사람·컴퓨터 같이 씀) ──
	def _act_move(self, room, seat, x, y):
		lk = self.locks.get(self.key(x, y))
		if lk:
			return False, f"잠긴 칸이에요. {UNLOCK_PRICE}P 로 해금하세요." if lk["kind"] == "lock" else "봉인된 칸이에요. 시간이 지나면 풀려요."
		target = self.at(x, y)
		if target and self.stack_turns and target["o"] in ("b", "w") and not target["perm"] and target.get("h", 1) < 2:
			return self._act_stack(room, seat, x, y, target)
		if not self.empty(x, y):
			return False, "거기에는 둘 수 없어요." + (" (돌 업기는 한 칸에 2개까지)" if self.stack_turns and target else "")
		if self.extra and self.extra.get("first") and self.extra["min_dist"]:
			fx, fy = self.extra["first"]
			if max(abs(fx - x), abs(fy - y)) < self.extra["min_dist"]:
				return False, f"쌍둥이 돌은 첫 돌에서 {self.extra['min_dist']}칸 이상 떨어진 곳에 둬야 해요."
		if self._place(room, seat, x, y):
			return True, None
		if self.bonus_now:
			self.bonus_now = False
			self.extra = {"left": 1, "min_dist": 2, "first": [x, y], "bonus": True}
			room.notice(f"🔁 {self.names[seat]} 님 다섯 번째 돌! 하나 더 공짜로 둬요.")
			return True, None
		if self.extra:
			if self.extra["first"] is None:
				self.extra["first"] = [x, y]
				room.notice("한 번 더 둘 수 있어요!")
				return True, None
			self.extra = None
		self._end_turn(room)
		return True, None

	def _act_stack(self, room, seat, x, y, target):
		"""돌 업기 중: 내 돌 위 → 그 칸 2개, 상대 돌 위 → 그 칸을 뺏음. 돌 하나 둔 것으로 침."""
		mine = target["o"] == self.color(seat)
		life = self.current_life() + (1 if "sturdy" in self.passives[seat] else 0)
		if mine:
			target.update(h=2, ttl=max(target["ttl"], life))
		else:
			target.update(o=self.color(seat), by=seat, ttl=life, h=1)
		self.placed[seat].append([x, y])
		self.points[seat] += 1
		self.place_count[seat] += 1
		self.last = {"type": "place", "seat": seat, "cell": [x, y], "stack": True}
		room.emit({"type": "event", "icon": "🥞", "name": "돌 업기!" if mine else "칸 뺏기!", "desc": f"{self.names[seat]} 님이 {'내 돌 위에 올려 2개로' if mine else '상대 돌 위에 올라타 그 칸을 뺏었어요'}", "cells": [[x, y]]})
		if self._check_win(room, seat):
			return True, None
		self._end_turn(room)
		return True, None

	def _act_draw(self, room, seat):
		if self.extra and self.extra.get("first"):
			return False, "두 번째 돌을 먼저 두세요."
		if self.points[seat] < RANDOM_PRICE:
			return False, f"무작위 뽑기는 {RANDOM_PRICE}포인트가 필요해요."
		if len(self.hand[seat]) >= HAND_MAX:
			return False, f"손에는 {HAND_MAX}장까지예요. 먼저 한 장 쓰세요."
		self.points[seat] -= RANDOM_PRICE
		self._gain_card(room, seat, self._roll(seat), "draw")
		self.last = {"type": "draw", "seat": seat}
		self._end_turn(room)
		return True, None

	def _act_buy(self, room, seat, i):
		if self.extra and self.extra.get("first"):
			return False, "두 번째 돌을 먼저 두세요."
		if not 0 <= i < len(self.shop[seat]):
			return False, None
		cid = self.shop[seat][i]
		price = PRICE[CARDS[cid][0]]
		if self.points[seat] < price:
			return False, f"'{CARDS[cid][2]}' 은(는) {price}포인트예요."
		if len(self.hand[seat]) >= HAND_MAX and CARDS[cid][4] != "instant":
			return False, f"손에는 {HAND_MAX}장까지예요. 먼저 한 장 쓰세요."
		self.points[seat] -= price
		self.shop[seat].pop(i)
		self._gain_card(room, seat, cid, "buy")
		self.last = {"type": "buy", "seat": seat}
		self._end_turn(room)
		return True, None

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

	# ── 컴퓨터 ──
	def _arm_bot(self):
		if self.status == "playing" and self.turn in self.bots:
			self.bot_due = time.time() + BOT_DELAY

	def _cell_score(self, x, y, c):
		"""(x, y) 에 c 를 두면 생기는 줄들의 점수 (열린 끝 고려)."""
		total = 0
		for dx, dy in DIRS:
			n, ends = 1, 0
			for sign in (1, -1):
				nx, ny = x + dx * sign, y + dy * sign
				while 0 <= nx < SIZE and 0 <= ny < SIZE and self._counts_for(self.at(nx, ny), c):
					n += 1
					nx, ny = nx + dx * sign, ny + dy * sign
				if self.empty(nx, ny):
					ends += 1
			if n >= 5:
				total += 1_000_000
			elif n == 4:
				total += 60_000 if ends == 2 else 9_000 if ends == 1 else 0
			elif n == 3:
				total += 4_000 if ends == 2 else 400 if ends == 1 else 0
			elif n == 2:
				total += 150 if ends == 2 else 30 if ends == 1 else 0
			else:
				total += 5 * ends
		return total

	def _best_cell(self, s, avoid_near=None, min_dist=0):
		me, op = self.color(s), self.color(self.other(s))
		cand = set()
		for k in self.cells:
			x, y = map(int, k.split(","))
			for dx in range(-2, 3):
				for dy in range(-2, 3):
					if self.empty(x + dx, y + dy):
						cand.add((x + dx, y + dy))
		if not cand:
			cand = {(SIZE // 2, SIZE // 2)} if self.empty(SIZE // 2, SIZE // 2) else {(x, y) for x in range(SIZE) for y in range(SIZE) if self.empty(x, y)}
		if avoid_near and min_dist:
			cand = {(x, y) for x, y in cand if max(abs(x - avoid_near[0]), abs(y - avoid_near[1])) >= min_dist} or cand
		best, best_v = None, -1
		for x, y in cand:
			v = self._cell_score(x, y, me) * 1.1 + self._cell_score(x, y, op) + self.rng.random()
			if v > best_v:
				best, best_v = (x, y), v
		return best, best_v

	def _threat(self, s):
		"""s 의 가장 긴 줄 길이."""
		c = self.color(s)
		best = 0
		for k, v in self.cells.items():
			if v["o"] == c:
				x, y = map(int, k.split(","))
				best = max(best, len(self._line(x, y, c)))
		return best

	def bot_act(self, room):
		s, o = self.turn, self.other(self.turn)
		hand = self.hand[s]
		danger = self._threat(o)
		# 1) 카드: 상대가 위험하면 막는 카드, 아니면 내 줄을 살리는 카드
		if not self.used_card and hand:
			pick, target = None, None
			if danger >= 3:
				for cid in ("ruler", "grandreset", "blackhole", "steal", "gust", "sleep", "chain", "rewind", "puppet", "seal", "undo", "quake", "dark", "eclipse", "breeze"):
					if cid in hand and not (cid == "grandreset" and (danger < 4 or self._threat(s) >= 3)):
						pick = cid
						break
				if pick in ("steal", "gust", "chain", "breeze", "blackhole", "seal"):
					target = list(map(int, self._danger_stones(o, 1)[0].split(","))) if self.stones_of(o) else None
				elif pick == "puppet":
					far = [(x, y) for x in (0, SIZE - 1) for y in (0, SIZE - 1) if self.empty(x, y)]
					target = list(far[0]) if far else None
			if not pick:
				for cid in ("sturdy", "fifth", "saver", "compound", "double", "twin", "joker", "hourglass", "eternal", "candle", "quick", "pickpocket", "key", "rockfall", "wall"):
					if cid in hand and (cid not in ("eternal", "candle") or self.stones_of(s)) and not (cid == "pickpocket" and self.points[o] < 2) and not (cid == "key" and not self.locks) \
							and cid not in self.passives[s]:
						pick = cid
						break
				if pick in ("eternal", "candle"):
					target = list(map(int, self._danger_stones(s, 1)[0].split(",")))
				elif pick in ("joker", "wall"):
					cell, _ = self._best_cell(s)
					target = list(cell)
			if pick and (CARDS[pick][4] in ("none",) or target):
				if self._use(room, s, pick, target or []) is None and self.status != "playing":
					return
		# 2) 뽑기: 급하지 않고 포인트가 넉넉하면 가끔
		_, v = self._best_cell(s)
		calm = danger <= 2 and v < 4000
		if calm and len(hand) < HAND_MAX and not self.extra:
			affordable = [i for i, cid in enumerate(self.shop[s]) if PRICE[CARDS[cid][0]] <= self.points[s] and RARITIES.index(CARDS[cid][0]) >= 2]
			if affordable and self.rng.random() < 0.5:
				self._act_buy(room, s, affordable[0])
				return
			if self.points[s] >= RANDOM_PRICE + 2 and self.rng.random() < 0.35:
				self._act_draw(room, s)
				return
		# 3) 두기 (한 번 더 두기면 두 번)
		for _ in range(2):
			if self.status != "playing" or self.turn != s:
				return
			first = self.extra["first"] if self.extra else None
			cell, _ = self._best_cell(s, first, self.extra["min_dist"] if self.extra else 0)
			if cell is None:
				return
			self._act_move(room, s, cell[0], cell[1])

	def tick(self, room, now):
		if self.status != "playing" or self.turn not in self.bots or now < self.bot_due:
			return False
		self.turn_started = now - 0.5  # 컴퓨터도 빠르게 두면 2포인트
		self.bot_act(room)
		return True

	# ── 보여 주기 ──
	def snapshot(self, room, pid=None):
		me = next((s for s, p in self.seats.items() if p == pid), None)
		window = (QUICK_WINDOW if self.turn and self.quick[self.turn] else FAST_WINDOW)
		over = self.status == "over"
		blind = bool(me and self.dark[me]) and not over        # 암흑: 이 사람 화면엔 돌이 안 보임
		gray = bool(self.memory) and not over                   # 잿빛 세상: 모두에게 회색, 남은 턴도 숨김
		cells = []
		if not blind:
			for k, v in self.cells.items():
				x, y = map(int, k.split(","))
				cells.append({"x": x, "y": y, "o": "g", "ttl": None, "perm": False, "by": None} if gray else {"x": x, "y": y, **v})
		return {
			"size": SIZE,
			"cells": cells, "blind": self.dark[me] if blind else 0, "gray": self.memory if gray else 0,
			"locks": [{"x": int(k.split(",")[0]), "y": int(k.split(",")[1]), **v} for k, v in self.locks.items()],
			"skip": sorted(self.skip), "dark": self.dark, "events_on": self.events_on, "stack_turns": self.stack_turns,
			"hint": list(self._best_cell(me)[0]) if (me and self.turn == me and self.timed[me].get("oracle") and self.status == "playing") else None,
			"next_event": EVENT_EVERY - self.turns % EVENT_EVERY, "unlock_price": UNLOCK_PRICE,
			"status": self.status, "turn": self.turn, "winner": self.winner, "win_line": self.win_line, "reason": self.reason,
			"life": self.life, "current_life": self.current_life(), "grow_every": GROW_EVERY,
			"next_grow": GROW_EVERY - self.turns % GROW_EVERY, "turns": self.turns, "last": None if (blind or gray) else self.last,
			"elapsed": round(time.time() - self.turn_started, 2) if self.turn else None, "fast_window": window,
			"used_card": self.used_card, "extra": self.extra, "forced": self.forced if self.forced and me == self.other(self.forced["seat"]) else None,
			"points": self.points, "hand_count": {s: len(self.hand[s]) for s in self.SEATS},
			"hand": [card_info(c) for c in self.hand[me]] if me else [],
			"shop": [card_info(c) for c in self.shop[me]] if me else [],
			"pity": self.pity[me] if me else 0, "pity_max": PITY,
			"random_price": RANDOM_PRICE, "hand_max": HAND_MAX,
			"odds": RARITY_WEIGHTS, "prices": PRICE,
			"quick": self.quick,
			"effects": {x: ([{"id": c, "icon": CARDS[c][1], "name": CARDS[c][2], "dur": "영구"} for c in self.passives[x]]
							+ [{"id": c, "icon": CARDS[c][1], "name": CARDS[c][2], "dur": f"{n}턴 남음"} for c, n in self.timed[x].items()]
							+ ([{"id": "quick", "icon": "⚡", "name": "번개손", "dur": f"{self.quick[x]}턴 남음"}] if self.quick[x] else []))
						for x in self.SEATS},
			"place_count": self.place_count,
			"seats": {s: ({"name": self.names[s], "bot": s in self.bots, "online": s in self.bots or p in room.peers, "wins": self.wins[s]} if p else None)
					  for s, p in self.seats.items()},
		}
