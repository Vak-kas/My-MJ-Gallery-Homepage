"""따라그리기: 도형(0~1 좌표의 선)을 주고, 그린 선이 얼마나 가까운지 서버가 채점."""

import math

ROUND = 5
MODES = {"trace": "따라 그리기", "memory": "보고 기억해서"}
MEMORY_SECONDS = 3
MAX_POINTS = 3000


def _param(f, n=240, closed=False):
	pts = [f(k / n) for k in range(n + (1 if closed else 1))]
	return [(round(x, 4), round(y, 4)) for x, y in pts]


def _poly(*pts):
	return [tuple(p) for p in pts]


def _star(points=5, outer=0.4, inner=0.17):
	out = []
	for k in range(points * 2 + 1):
		a = -math.pi / 2 + k * math.pi / points
		r = outer if k % 2 == 0 else inner
		out.append((0.5 + r * math.cos(a), 0.52 + r * math.sin(a)))
	return out


def _moon():
	"""바깥 원(왼쪽 큰 호) + 안쪽 원(오른쪽에서 파고드는 호)."""
	outer = [(0.5 + 0.36 * math.cos(math.radians(a)), 0.5 + 0.36 * math.sin(math.radians(a))) for a in range(60, 301, 4)]
	r = 0.36 * math.sin(math.radians(60))
	inner = [(0.68 + r * math.cos(math.radians(a)), 0.5 + r * math.sin(math.radians(a))) for a in range(270, 89, -4)]
	return [(round(x, 4), round(y, 4)) for x, y in outer + inner]


SHAPES = {
	"circle": ("동그라미", _param(lambda t: (0.5 + 0.36 * math.cos(2 * math.pi * t), 0.5 + 0.36 * math.sin(2 * math.pi * t)), closed=True)),
	"square": ("네모", _poly((0.18, 0.18), (0.82, 0.18), (0.82, 0.82), (0.18, 0.82), (0.18, 0.18))),
	"triangle": ("세모", _poly((0.5, 0.14), (0.86, 0.8), (0.14, 0.8), (0.5, 0.14))),
	"star": ("별", _star()),
	"heart": ("하트", _param(lambda t: (0.5 + 0.022 * 16 * math.sin(2 * math.pi * t) ** 3,
								  0.47 - 0.022 * (13 * math.cos(2 * math.pi * t) - 5 * math.cos(4 * math.pi * t) - 2 * math.cos(6 * math.pi * t) - math.cos(8 * math.pi * t))), closed=True)),
	"spiral": ("소용돌이", _param(lambda t: (0.5 + 0.38 * t * math.cos(6 * math.pi * t), 0.5 + 0.38 * t * math.sin(6 * math.pi * t)), n=360)),
	"wave": ("물결", _param(lambda t: (0.1 + 0.8 * t, 0.5 + 0.18 * math.sin(4 * math.pi * t)))),
	"zigzag": ("번개", _poly((0.58, 0.08), (0.3, 0.52), (0.52, 0.52), (0.38, 0.92), (0.74, 0.4), (0.52, 0.4), (0.68, 0.08), (0.58, 0.08))),
	"infinity": ("무한대", _param(lambda t: (0.5 + 0.38 * math.cos(2 * math.pi * t) / (1 + math.sin(2 * math.pi * t) ** 2),
									   0.5 + 0.38 * math.sin(2 * math.pi * t) * math.cos(2 * math.pi * t) / (1 + math.sin(2 * math.pi * t) ** 2)), closed=True)),
	"flower": ("꽃", _param(lambda t: (0.5 + 0.38 * math.cos(5 * math.pi * t) * math.cos(math.pi * t),  # 꽃잎 5장은 반 바퀴면 다 그려짐
								   0.5 + 0.38 * math.cos(5 * math.pi * t) * math.sin(math.pi * t)), n=300, closed=True)),
	"house": ("집", _poly((0.2, 0.86), (0.2, 0.46), (0.5, 0.16), (0.8, 0.46), (0.8, 0.86), (0.2, 0.86))),
	"moon": ("초승달", _moon()),
	"diamond": ("다이아몬드", _poly((0.5, 0.1), (0.82, 0.5), (0.5, 0.9), (0.18, 0.5), (0.5, 0.1))),
	"spring": ("용수철", _param(lambda t: (0.12 + 0.76 * t + 0.07 * math.cos(10 * math.pi * t), 0.5 + 0.22 * math.sin(10 * math.pi * t)), n=400)),
	"cloud": ("구름", _param(lambda t: ((0.5 + (0.26 + 0.05 * abs(math.sin(4 * math.pi * t))) * 1.25 * math.cos(2 * math.pi * t)),
									 (0.52 + (0.26 + 0.05 * abs(math.sin(4 * math.pi * t))) * 0.8 * math.sin(2 * math.pi * t))), n=320, closed=True)),
}


def _resample(pts, step):
	"""선을 step 간격 점들로 (끊어진 획은 각각)."""
	if not pts:
		return []
	out = [pts[0]]
	carry = 0.0
	for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
		seg = math.hypot(x1 - x0, y1 - y0)
		d = step - carry
		while d <= seg:
			t = d / seg
			out.append((x0 + (x1 - x0) * t, y0 + (y1 - y0) * t))
			d += step
		carry = seg - (d - step)
	out.append(pts[-1])
	return out


class _Grid:
	"""가까운 점 찾기용 칸 나누기 (numpy 없이 빠르게)."""

	def __init__(self, pts, cell=0.05):
		self.cell = cell
		self.buckets = {}
		for p in pts:
			self.buckets.setdefault((int(p[0] / cell), int(p[1] / cell)), []).append(p)

	def nearest(self, x, y, cap=0.3):
		cx, cy = int(x / self.cell), int(y / self.cell)
		best = cap * cap
		ring = 0
		while ring * self.cell <= cap + self.cell:
			for gx in range(cx - ring, cx + ring + 1):
				for gy in range(cy - ring, cy + ring + 1):
					if max(abs(gx - cx), abs(gy - cy)) != ring:
						continue
					for px, py in self.buckets.get((gx, gy), ()):
						d = (px - x) ** 2 + (py - y) ** 2
						if d < best:
							best = d
			if best < (ring * self.cell) ** 2:
				break
			ring += 1
		return math.sqrt(best)


def clean_strokes(strokes):
	"""브라우저가 보낸 획을 검사·정리. [[x, y], ...] 의 목록."""
	out, total = [], 0
	if not isinstance(strokes, list):
		return out
	for s in strokes[:50]:
		if not isinstance(s, list):
			continue
		pts = []
		for p in s:
			if total >= MAX_POINTS:
				break
			if isinstance(p, (list, tuple)) and len(p) == 2 and all(isinstance(v, (int, float)) and math.isfinite(v) for v in p):
				pts.append((min(max(float(p[0]), -0.2), 1.2), min(max(float(p[1]), -0.2), 1.2)))
				total += 1
		if pts:
			out.append(pts)
	return out


def score(shape, strokes):
	"""0~100. 도형을 얼마나 덮었나(빠뜨린 곳)와 그린 선이 도형에서 얼마나 벗어났나의 평균 거리로."""
	target = _resample(SHAPES[shape][1], 0.006)
	drawn = [p for s in clean_strokes(strokes) for p in _resample(s, 0.008)]
	if len(drawn) < 5:
		return 0
	t_grid, d_grid = _Grid(target), _Grid(drawn)
	cover = sum(d_grid.nearest(x, y) for x, y in target[::2]) / len(target[::2])
	stray = sum(t_grid.nearest(x, y) for x, y in drawn) / len(drawn)
	err = (cover + stray) / 2
	return max(0, min(100, round(100 * (1 - max(0.0, err - 0.004) / 0.04))))
