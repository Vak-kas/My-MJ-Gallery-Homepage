"""지뢰찾기: 지뢰 위치는 서버만 알고, 칸을 열 때마다 서버가 결과를 알려 줌."""

import random

LEVELS = {"easy": ("초급", 9, 9, 10), "normal": ("중급", 16, 16, 40), "hard": ("고급", 16, 30, 99)}  # 이름, 줄, 칸, 지뢰
MINE = -1


class Board:
	def __init__(self, level="easy"):
		self.level = level if level in LEVELS else "easy"
		_, self.rows, self.cols, self.count = LEVELS[self.level]
		self.mines = None  # 첫 칸을 연 뒤에 깔아서 첫 클릭은 항상 안전
		self.opened = set()
		self.state = "ready"  # ready → playing → won / lost
		self.boom = None

	@property
	def size(self):
		return self.rows * self.cols

	def neighbors(self, i):
		r, c = divmod(i, self.cols)
		for dr in (-1, 0, 1):
			for dc in (-1, 0, 1):
				nr, nc = r + dr, c + dc
				if (dr or dc) and 0 <= nr < self.rows and 0 <= nc < self.cols:
					yield nr * self.cols + nc

	def number(self, i):
		return MINE if i in self.mines else sum(1 for j in self.neighbors(i) if j in self.mines)

	def _lay(self, first, rnd):
		safe = {first, *self.neighbors(first)}
		spots = [i for i in range(self.size) if i not in safe]
		if len(spots) < self.count:  # 판이 너무 작으면 첫 칸만 피함
			spots = [i for i in range(self.size) if i != first]
		self.mines = set(rnd.sample(spots, self.count))

	def open(self, cells, rnd=None):
		"""cells 를 차례로 엶. 새로 열린 칸 {번호: 숫자} 를 돌려줌 (0 이면 주변까지 퍼짐)."""
		shown = {}
		for i in cells:
			if self.state not in ("ready", "playing") or not isinstance(i, int) or not 0 <= i < self.size or i in self.opened:
				continue
			if self.mines is None:
				self._lay(i, rnd or random.SystemRandom())
				self.state = "playing"
			if i in self.mines:
				self.state, self.boom = "lost", i
				break
			stack = [i]
			while stack:
				j = stack.pop()
				if j in self.opened:
					continue
				self.opened.add(j)
				shown[j] = n = self.number(j)
				if n == 0:
					stack.extend(k for k in self.neighbors(j) if k not in self.opened)
			if len(self.opened) == self.size - self.count:
				self.state = "won"
				break
		return shown
