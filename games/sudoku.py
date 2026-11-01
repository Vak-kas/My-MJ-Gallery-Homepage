"""스도쿠: 서버가 답이 하나뿐인 문제를 만들고, 제출한 판을 답과 비교."""

import random

LEVELS = {"easy": ("쉬움", 40), "normal": ("보통", 32), "hard": ("어려움", 26)}  # 남길 숫자 수(목표)

ROWS = [[r * 9 + c for c in range(9)] for r in range(9)]
COLS = [[r * 9 + c for r in range(9)] for c in range(9)]
BOXES = [[(br * 3 + r) * 9 + bc * 3 + c for r in range(3) for c in range(3)] for br in range(3) for bc in range(3)]
UNIT_OF = [(i // 9, i % 9, (i // 27) * 3 + (i % 9) // 3) for i in range(81)]
ALL = 0x3FE  # 1~9 비트


def _search(grid, limit, rnd=None):
	"""답 개수를 limit 까지 셈. rnd 가 있으면 숫자를 섞어 넣어 첫 답을 grid 에 남김."""
	rows, cols, boxes = [0] * 9, [0] * 9, [0] * 9
	empty = []
	for i, v in enumerate(grid):
		if v:
			r, c, b = UNIT_OF[i]
			bit = 1 << v
			if (rows[r] | cols[c] | boxes[b]) & bit:
				return 0
			rows[r] |= bit; cols[c] |= bit; boxes[b] |= bit
		else:
			empty.append(i)
	found = 0

	def go():
		nonlocal found
		best, best_mask, best_n = -1, 0, 10
		for i in empty:
			if grid[i]:
				continue
			r, c, b = UNIT_OF[i]
			mask = ALL & ~(rows[r] | cols[c] | boxes[b])
			n = bin(mask).count("1")
			if n < best_n:
				best, best_mask, best_n = i, mask, n
				if n <= 1:
					break
		if best < 0:
			found += 1
			return found >= limit
		if best_n == 0:
			return False
		r, c, b = UNIT_OF[best]
		digits = [d for d in range(1, 10) if best_mask >> d & 1]
		if rnd:
			rnd.shuffle(digits)
		for d in digits:
			bit = 1 << d
			grid[best] = d
			rows[r] |= bit; cols[c] |= bit; boxes[b] |= bit
			if go():
				if rnd:
					return True  # 답을 grid 에 남겨 둠
				grid[best] = 0
				rows[r] &= ~bit; cols[c] &= ~bit; boxes[b] &= ~bit
				return True
			grid[best] = 0
			rows[r] &= ~bit; cols[c] &= ~bit; boxes[b] &= ~bit
		return False

	go()
	return found


def count_solutions(grid, limit=2):
	return _search(list(grid), limit)


def generate(level="normal", rnd=None):
	"""(문제, 답) — 81자 문자열, 빈칸은 0. 대칭으로 지우되 답이 하나일 때만."""
	rnd = rnd or random.SystemRandom()
	target = LEVELS.get(level, LEVELS["normal"])[1]
	solution = [0] * 81
	_search(solution, 1, rnd)
	puzzle = solution[:]
	cells = list(range(41))
	rnd.shuffle(cells)
	clues = 81
	for i in cells:
		if clues <= target:
			break
		pair = {i, 80 - i}
		saved = [(j, puzzle[j]) for j in pair]
		for j in pair:
			puzzle[j] = 0
		if count_solutions(puzzle) != 1:
			for j, v in saved:
				puzzle[j] = v
		else:
			clues -= len(pair)
	singles = [i for i in range(81) if puzzle[i]]  # 대칭으로 더 못 지우면 한 칸씩
	rnd.shuffle(singles)
	for i in singles:
		if clues <= target:
			break
		v, puzzle[i] = puzzle[i], 0
		if count_solutions(puzzle) != 1:
			puzzle[i] = v
		else:
			clues -= 1
	return "".join(map(str, puzzle)), "".join(map(str, solution))


def is_solved(puzzle, solution, answer):
	"""제출한 판이 답과 같고, 처음 숫자도 그대로인지."""
	if not isinstance(answer, str) or len(answer) != 81 or not answer.isdigit():
		return False
	return answer == solution and all(p == "0" or p == a for p, a in zip(puzzle, answer))
