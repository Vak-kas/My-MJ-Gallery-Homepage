"""2048 규칙 (templates/games/2048.html 의 JS 와 똑같아야 함).

서버가 준 seed 로 같은 난수를 만들고, 브라우저가 보낸 움직임(U·D·L·R)을 처음부터 다시 둬서 점수를 직접 계산한다.
"""

MASK = 0xFFFFFFFF


def mulberry32(seed):
	a = seed & MASK

	def rnd():
		nonlocal a
		a = (a + 0x6D2B79F5) & MASK
		t = ((a ^ (a >> 15)) * (a | 1)) & MASK
		t = ((t + (((t ^ (t >> 7)) * (t | 61)) & MASK)) & MASK) ^ t
		return ((t ^ (t >> 14)) & MASK) / 4294967296

	return rnd


LINES = {
	"L": [[r * 4 + c for c in range(4)] for r in range(4)],
	"R": [[r * 4 + c for c in reversed(range(4))] for r in range(4)],
	"U": [[r * 4 + c for r in range(4)] for c in range(4)],
	"D": [[r * 4 + c for r in reversed(range(4))] for c in range(4)],
}


class Game:
	def __init__(self, seed):
		self.rnd = mulberry32(seed)
		self.board = [0] * 16
		self.score = 0
		self.moves = 0
		self.spawn()
		self.spawn()

	def spawn(self):
		empty = [i for i, v in enumerate(self.board) if not v]
		if not empty:
			return
		i = empty[int(self.rnd() * len(empty))]
		self.board[i] = 2 if self.rnd() < 0.9 else 4

	def move(self, d):
		moved = False
		for line in LINES[d]:
			vals = [self.board[i] for i in line if self.board[i]]
			out = []
			k = 0
			while k < len(vals):
				if k + 1 < len(vals) and vals[k] == vals[k + 1]:
					out.append(vals[k] * 2)
					self.score += vals[k] * 2
					k += 2
				else:
					out.append(vals[k])
					k += 1
			out += [0] * (4 - len(out))
			for i, v in zip(line, out):
				if self.board[i] != v:
					moved = True
				self.board[i] = v
		if moved:
			self.moves += 1
			self.spawn()
		return moved

	def over(self):
		if 0 in self.board:
			return False
		for r in range(4):
			for c in range(4):
				v = self.board[r * 4 + c]
				if (c < 3 and self.board[r * 4 + c + 1] == v) or (r < 3 and self.board[(r + 1) * 4 + c] == v):
					return False
		return True


def replay(seed, moves):
	game = Game(seed)
	for d in moves:
		if d not in LINES:
			raise ValueError("bad move")
		if game.over():
			break
		game.move(d)
	return game
