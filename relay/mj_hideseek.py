"""🫥 숨바꼭질 (물건으로 변신) — 술래 1명(1인칭) 대 숨는 사람들(3인칭, 물건으로 변신).

1단계 규칙
- 방장이 [시작] → 술래 한 명(판마다 돌아가며), 나머지는 숨는 사람
- 숨기(HIDE 초): 술래는 눈을 감고 못 움직임. 숨는 사람은 집 안의 물건을 보고 E 로 그 물건으로 변신해 자리를 잡음
- 찾기(SEEK 초): 술래가 1인칭으로 돌아다니며 수상한 물건을 쏨
  · 숨은 사람을 맞히면 그 사람 체력 −HIT_DAMAGE (0 이 되면 잡힘)
  · 진짜 물건을 쏘면 술래 체력 −MISS_PENALTY (마구 쏘기 방지), 0 이 되면 숨는 쪽 승리
  · TAUNT_EVERY 초마다 살아 있는 숨는 사람 자리에서 '삑' 소리 (술래가 방향으로 들음)
- 다 잡으면 술래 승리, 시간이 끝나면 살아남은 숨는 사람 승리

2단계 — 지도와 자리 바꾸기
- 지도(M): 집의 '원래 배치도'. 숨은 사람은 지도에 없으므로, 지도에 없는데 놓여 있는 물건이 수상한 것
  · 술래는 MAP_SHOW 초 보고 나면 MAP_COOLDOWN 초 쉬어야 함 (브라우저가 지킴 — 지도 자체는 처음부터 다 받는 정보)
- 자리 바꾸기(F, 판마다 SWAPS 번): 숨는 사람이 진짜 물건 하나를 치우고 그 자리·방향 그대로 들어감 → 지도와 똑같아짐.
  치운 물건은 그 판 동안 사라지므로, 거기서 떠나면 지도엔 있는데 실제론 빈 자리가 남음

3단계 — 맵 고르기·점수·소리
- 방장이 판 사이에 맵(MAPS)을 고름: 집 / 사무실·창고. 바꾸면 모두에게 map 을 다시 보냄
- 점수: 술래는 한 명 잡을 때마다 +1, 숨는 사람은 끝까지 살아남으면 +2 (방이 있는 동안 쌓임)
- 발소리·모바일 조작은 브라우저 쪽 (static/js/hideseek.js)

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
SWAPS = 2             # 판마다 자리 바꾸기 횟수
SWAP_RANGE = 4.0
SWAP_HOLD = 0.4       # 자리 바꾼 직후 이 시간 동안은 (바꾸기 전에 보낸) 위치를 무시
MAP_SHOW = 6          # 술래가 지도를 한 번에 보는 시간(초)
MAP_COOLDOWN = 20     # 그 뒤 쉬는 시간(초)
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
	"desk": ("책상", 1.4, 0.75, 0.7),
	"cabinet": ("캐비닛", 0.9, 1.3, 0.45),
	"cone": ("고깔", 0.4, 0.6, 0.4),
	"locker": ("사물함", 0.5, 1.8, 0.5),
	"bench": ("벤치", 1.5, 0.45, 0.4),
	"cart": ("카트", 0.6, 1.0, 0.9),
	"counter": ("계산대", 1.8, 0.9, 0.7),
}
BIG_PROPS = ("bed", "sofa", "fridge", "bench", "counter")   # 처음 모습으로는 안 줌 (너무 큼)


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
	rooms = [("거실", 0, 0, 12, 16, "#c8a77e"), ("부엌", 12, 0, 12, 9, "#d6d6d2"), ("침실", 12, 9, 12, 7, "#b7c4d6")]
	return _map("house", "집", W, D, walls, rooms, P, [6.0, 8.0], [[3, 11], [9, 4], [16, 2], [21, 4], [15, 12], [20, 11], [8, 15], [10.5, 8]])


def _office():
	"""사무실·창고: 위쪽 사무실(22×8), 왼쪽 아래 창고(13×10), 오른쪽 아래 휴게실(9×10)."""
	W, D = 22.0, 18.0
	t = 0.3
	walls = [
		(W / 2, -t / 2, W + 2 * t, t), (W / 2, D + t / 2, W + 2 * t, t),
		(-t / 2, D / 2, t, D), (W + t / 2, D / 2, t, D),
		# 사무실 | 창고·휴게실 (문 두 개: x 5~7, 16~18)
		(2.5, 8, 5, t), (11.5, 8, 9, t), (20, 8, 4, t),
		# 창고 | 휴게실 (문: z 12~14)
		(13, 10, t, 4), (13, 16, t, 4),
	]
	h = math.pi / 2
	P = [
		# 사무실
		("desk", 3, 2, 0), ("desk", 6, 2, 0), ("desk", 9, 2, 0), ("desk", 3, 5.5, 0), ("desk", 6, 5.5, 0), ("desk", 9, 5.5, 0),
		("chair", 3, 2.9, math.pi), ("chair", 6, 2.9, math.pi), ("chair", 9, 2.9, math.pi), ("chair", 3, 6.4, math.pi), ("chair", 6, 6.4, math.pi), ("chair", 9, 6.4, math.pi),
		("cabinet", 13, 0.4, 0), ("cabinet", 14.2, 0.4, 0), ("cabinet", 15.4, 0.4, 0), ("plant", 0.6, 0.6, 0), ("plant", 21.3, 0.6, 0),
		("trash", 11, 1, 0), ("trash", 11, 6.8, 0), ("shelf", 21.6, 3, -h), ("shelf", 21.6, 5, -h), ("table", 17, 4.5, 0),
		("chair", 16.1, 3.6, 0), ("chair", 17.9, 3.6, 0), ("chair", 16.1, 5.4, math.pi), ("chair", 17.9, 5.4, math.pi), ("lamp", 0.6, 7.3, 0), ("cone", 12.5, 7.2, 0),
		# 창고
		("box", 1, 9.5, 0), ("box", 2, 9.6, 0.3), ("box", 1.2, 10.6, 0.5), ("box", 4, 17, 0), ("box", 5, 17.1, 0.2), ("box", 4.5, 16.1, 0.7),
		("box", 11.5, 9.3, 0), ("box", 11.8, 17.2, 0.4), ("barrel", 1, 17, 0), ("barrel", 2, 17.1, 0), ("barrel", 1.5, 16.1, 0), ("barrel", 9, 13, 0),
		("barrel", 10, 9.2, 0), ("shelf", 0.5, 13, h), ("shelf", 9.5, 8.4, 0), ("cone", 6, 12, 0), ("cone", 7.5, 14, 0), ("cone", 4, 12.5, 0),
		("stool", 9.5, 16.5, 0), ("trash", 12.3, 11, 0), ("ball", 7, 10.5, 0), ("cabinet", 12.5, 15.5, -h),
		# 휴게실
		("sofa", 17.5, 17.2, math.pi), ("table", 17.5, 15.2, 0), ("tv", 15, 8.5, 0), ("fridge", 21.3, 8.7, 0), ("plant", 13.8, 8.7, 0), ("plant", 21.3, 17.3, 0),
		("stool", 15, 12, 0), ("stool", 16, 12.4, 0), ("chair", 19.5, 15.2, -h), ("lamp", 13.7, 17.3, 0), ("ball", 20, 11.5, 0), ("box", 21, 13, 0.3),
		("trash", 14, 14.2, 0), ("barrel", 21.2, 15, 0),
	]
	rooms = [("사무실", 0, 0, 22, 8, "#cfd3d8"), ("창고", 0, 8, 13, 10, "#a9a397"), ("휴게실", 13, 8, 9, 10, "#d9c7a8")]
	return _map("office", "사무실·창고", W, D, walls, rooms, P, [11.0, 4.0], [[1.5, 4], [7.5, 3.8], [14, 3], [20, 2], [3, 13.5], [8, 16], [16, 10.5], [19.5, 13.2]])


def _school():
	"""학교: 위쪽 교실 둘(1반·2반, 13×6.5씩), 가운데 긴 복도(26×3), 아래 체육 창고(10×6.5)·급식실(16×6.5)."""
	W, D = 26.0, 16.0
	t = 0.3
	walls = [
		(W / 2, -t / 2, W + 2 * t, t), (W / 2, D + t / 2, W + 2 * t, t),
		(-t / 2, D / 2, t, D), (W + t / 2, D / 2, t, D),
		# 교실 | 복도 (문 두 개: x 5~7, 18~20)
		(2.5, 6.5, 5, t), (12.5, 6.5, 11, t), (23, 6.5, 6, t),
		# 1반 | 2반
		(13, 3.175, t, 6.35),
		# 복도 | 체육 창고·급식실 (문 두 개: x 3~5, 16~18)
		(1.5, 9.5, 3, t), (10.5, 9.5, 11, t), (22, 9.5, 8, t),
		# 체육 창고 | 급식실 (문: z 12~14)
		(10, 10.825, t, 2.35), (10, 15, t, 2),
	]
	h = math.pi / 2
	P = [
		# 1반
		("desk", 3, 1.8, 0), ("desk", 5.5, 1.8, 0), ("desk", 8, 1.8, 0), ("desk", 3, 4.2, 0), ("desk", 5.5, 4.2, 0), ("desk", 8, 4.2, 0),
		("chair", 3, 2.7, math.pi), ("chair", 5.5, 2.7, math.pi), ("chair", 8, 2.7, math.pi), ("chair", 3, 5.1, math.pi), ("chair", 5.5, 5.1, math.pi), ("chair", 8, 5.1, math.pi),
		("desk", 11, 3, h), ("cabinet", 11.5, 0.4, 0), ("shelf", 0.5, 3.25, h), ("plant", 0.6, 0.6, 0), ("trash", 12.3, 5.8, 0), ("ball", 1.5, 5.5, 0),
		# 2반
		("desk", 16, 1.8, 0), ("desk", 18.5, 1.8, 0), ("desk", 21, 1.8, 0), ("desk", 16, 4.2, 0), ("desk", 18.5, 4.2, 0), ("desk", 21, 4.2, 0),
		("chair", 16, 2.7, math.pi), ("chair", 18.5, 2.7, math.pi), ("chair", 21, 2.7, math.pi), ("chair", 16, 5.1, math.pi), ("chair", 18.5, 5.1, math.pi), ("chair", 21, 5.1, math.pi),
		("locker", 25.6, 0.6, 0), ("locker", 25.6, 1.15, 0), ("locker", 25.6, 1.7, 0), ("locker", 25.6, 2.25, 0), ("tv", 24, 6.0, math.pi), ("plant", 13.6, 0.6, 0),
		("trash", 13.7, 5.9, 0), ("lamp", 25.4, 5.8, 0), ("stool", 23.5, 3.5, 0), ("box", 14, 3.2, 0),
		# 복도
		("locker", 8.8, 7.0, 0), ("locker", 9.35, 7.0, 0), ("locker", 9.9, 7.0, 0), ("locker", 10.45, 7.0, 0), ("locker", 11, 7.0, 0),
		("locker", 14, 7.0, 0), ("locker", 14.55, 7.0, 0), ("locker", 15.1, 7.0, 0), ("bench", 8, 9.1, 0), ("bench", 12, 9.1, 0), ("bench", 21, 9.1, 0),
		("plant", 0.6, 8, 0), ("plant", 25.4, 8, 0), ("trash", 1.5, 9.0, 0), ("cone", 15.5, 8.6, 0), ("barrel", 24.5, 9.0, 0), ("box", 22.8, 7.1, 0),
		# 체육 창고
		("ball", 1, 15, 0), ("ball", 1.7, 15.2, 0), ("ball", 1.3, 14.4, 0), ("ball", 6, 12, 0), ("cone", 7, 10.3, 0), ("cone", 7.7, 10.3, 0),
		("cone", 8.4, 10.3, 0), ("cone", 5.5, 14, 0), ("barrel", 9.2, 10.2, 0), ("barrel", 9.2, 15.2, 0), ("barrel", 8.3, 15.3, 0), ("box", 0.6, 10.3, 0),
		("box", 1.5, 10.4, 0.3), ("box", 0.9, 11.4, 0.6), ("box", 4, 15.4, 0), ("shelf", 0.5, 13, h), ("bench", 4.5, 12.5, 0), ("stool", 2.5, 13, 0),
		("cabinet", 9.5, 11.2, -h), ("trash", 6, 15.5, 0),
		# 급식실
		("table", 14, 12.5, 0), ("table", 18, 12.5, 0), ("table", 22, 12.5, 0), ("bench", 14, 11.7, 0), ("bench", 14, 13.3, 0), ("bench", 22, 11.7, 0),
		("bench", 22, 13.3, 0), ("chair", 17.55, 11.6, 0), ("chair", 18.45, 11.6, 0), ("chair", 17.55, 13.4, math.pi), ("chair", 18.45, 13.4, math.pi), ("fridge", 25.4, 10.1, 0),
		("shelf", 23, 9.9, 0), ("cabinet", 20.5, 9.95, 0), ("trash", 10.6, 15.4, 0), ("trash", 11.2, 15.4, 0), ("barrel", 25.3, 15.3, 0), ("plant", 10.6, 10.2, 0),
		("tv", 20, 15.6, math.pi), ("stool", 12, 14.8, 0), ("box", 25.2, 13, 0.3), ("lamp", 10.6, 11.2, 0), ("ball", 15, 15, 0),
	]
	rooms = [("1반", 0, 0, 13, 6.5, "#d9c9a3"), ("2반", 13, 0, 13, 6.5, "#d3cdb0"), ("복도", 0, 6.5, 26, 3, "#c9ccd1"),
		("체육 창고", 0, 9.5, 10, 6.5, "#b9a98f"), ("급식실", 10, 9.5, 16, 6.5, "#d6dde0")]
	return _map("school", "학교", W, D, walls, rooms, P, [13.0, 8.0], [[1.8, 3.2], [9.8, 3], [14.5, 5], [23.5, 1.5], [3, 12], [7.5, 13], [12, 12.5], [24, 12.5]])


def _mart():
	"""마트: 왼쪽 위 매장(16×12, 진열대 줄), 왼쪽 아래 계산대(16×6), 오른쪽 위 창고(8×10), 오른쪽 아래 푸드코트(8×8)."""
	W, D = 24.0, 18.0
	t = 0.3
	walls = [
		(W / 2, -t / 2, W + 2 * t, t), (W / 2, D + t / 2, W + 2 * t, t),
		(-t / 2, D / 2, t, D), (W + t / 2, D / 2, t, D),
		# 매장·계산대 | 창고·푸드코트 (문 두 개: z 4~6, 14~16)
		(16, 2, t, 4), (16, 10, t, 8), (16, 17, t, 2),
		# 매장 | 계산대 (넓게 트인 곳 두 군데: x 2~7, 9~14)
		(1, 12, 2, t), (8, 12, 2, t), (14.925, 12, 1.85, t),
		# 창고 | 푸드코트 (문: x 19~21)
		(17.575, 10, 2.85, t), (22.5, 10, 3, t),
	]
	h = math.pi / 2
	P = [("shelf", x, z, 0) for z in (3, 6, 9) for x in (3, 4.2, 5.4, 6.6, 9.5, 10.7, 11.9, 13.1)]   # 진열대 세 줄
	P += [
		# 매장
		("fridge", 1, 0.45, 0), ("fridge", 1.85, 0.45, 0), ("fridge", 2.7, 0.45, 0), ("fridge", 12, 0.45, 0), ("fridge", 12.85, 0.45, 0), ("table", 10, 1.4, 0),
		("cart", 1.2, 10.5, 0), ("cart", 1.2, 9.4, 0), ("cart", 8, 1.5, h), ("cart", 14.8, 7.5, 0), ("box", 8.05, 3, 0), ("box", 8.05, 6, 0),
		("box", 1, 4.5, 0.2), ("box", 1.1, 5.5, 0), ("barrel", 8, 9, 0), ("cone", 5, 4.5, 0), ("cone", 11, 7.5, 0), ("ball", 4, 1.5, 0),
		("plant", 0.6, 11.3, 0), ("trash", 15.4, 0.6, 0), ("stool", 14.8, 10.8, 0), ("lamp", 15.4, 11.3, 0),
		# 창고
		("box", 23.4, 0.6, 0), ("box", 22.5, 0.6, 0), ("box", 23.3, 1.5, 0.4), ("box", 17, 9.2, 0), ("box", 17.9, 9.3, 0), ("box", 20, 2, 0.5),
		("box", 21, 2.6, 0), ("barrel", 23.4, 9.2, 0), ("barrel", 22.6, 9.3, 0), ("barrel", 23.3, 8.3, 0), ("barrel", 16.7, 0.7, 0), ("barrel", 19, 6, 0),
		("shelf", 23.6, 5, -h), ("shelf", 20, 0.4, 0), ("cabinet", 16.5, 7.5, h), ("cone", 18, 3, 0), ("cone", 21.5, 6.5, 0), ("cart", 21, 8.6, 0),
		("trash", 16.6, 2.5, 0), ("stool", 22, 4, 0), ("ball", 18.5, 8, 0), ("lamp", 23.5, 3, 0),
		# 푸드코트
		("table", 18, 12.8, 0), ("table", 22, 12.8, 0), ("table", 20, 16, 0), ("chair", 18, 11.9, 0), ("chair", 18, 13.7, math.pi), ("chair", 22, 11.9, 0),
		("chair", 22, 13.7, math.pi), ("chair", 20, 15.1, 0), ("chair", 20, 16.9, math.pi), ("fridge", 23.4, 17.4, 0), ("tv", 17.5, 17.6, math.pi), ("plant", 23.4, 10.6, 0),
		("plant", 16.6, 10.6, 0), ("trash", 23.5, 14.5, 0), ("stool", 16.8, 12, 0), ("barrel", 22, 17.4, 0), ("ball", 18, 15, 0),
		# 계산대
		("counter", 3, 14.5, h), ("counter", 6, 14.5, h), ("counter", 10, 14.5, h), ("counter", 13, 14.5, h), ("stool", 3.8, 14.5, 0), ("stool", 6.8, 14.5, 0),
		("stool", 10.8, 14.5, 0), ("stool", 13.8, 14.5, 0), ("cart", 1, 17.2, 0), ("cart", 1.7, 17.2, 0), ("cart", 2.4, 17.2, 0), ("plant", 0.6, 12.6, 0),
		("plant", 15.4, 17.4, 0), ("trash", 8, 17.4, 0), ("trash", 4.5, 13, 0), ("cone", 8, 14.5, 0), ("bench", 11.5, 17.5, 0), ("bench", 5.5, 17.5, 0),
		("box", 15.2, 12.7, 0), ("barrel", 14.5, 17.4, 0), ("lamp", 0.6, 15, 0), ("ball", 12, 13, 0),
	]
	rooms = [("매장", 0, 0, 16, 12, "#e4e1d6"), ("창고", 16, 0, 8, 10, "#a9a397"), ("계산대", 0, 12, 16, 6, "#cdd6dc"), ("푸드코트", 16, 10, 8, 8, "#e0c9a6")]
	return _map("mart", "마트", W, D, walls, rooms, P, [8.0, 16.0], [[2, 2], [8, 7.5], [14.8, 4.5], [5, 10.7], [18.5, 5], [22, 7], [20, 14], [12, 16]])


def _map(key, name, W, D, walls, rooms, P, seeker_spawn, hider_spawns):
	return {
		"key": key, "name": name,
		"w": W, "d": D, "wall_h": WALL_H,
		"walls": [{"x": x, "z": z, "w": w, "d": d} for x, z, w, d in walls],
		"rooms": [{"name": n, "x": x, "z": z, "w": w, "d": d, "color": c} for n, x, z, w, d, c in rooms],
		"props": [{"id": f"p{i}", "type": t_, "x": x, "z": z, "ry": round(ry, 4)} for i, (t_, x, z, ry) in enumerate(P)],
		"seeker_spawn": seeker_spawn,
		"hider_spawns": hider_spawns,
	}


MAPS = {m["key"]: m for m in (_house(), _office(), _school(), _mart())}
MAP = MAPS["house"]   # 기본 맵


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
		self.removed = set()      # 이번 판에 숨는 사람이 치운 진짜 물건 id
		self.map = MAP
		self.prop_by_id = {p["id"]: p for p in MAP["props"]}

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
		self._send_map(room, to=peer.pid)

	def _send_map(self, room, to=None):
		room.emit({"type": "map", "map": self.map, "props": {k: list(v) for k, v in PROPS.items()}, "speed": SPEED}, to=to)

	def _new_player(self, name):
		return {"name": name, "role": None, "alive": True, "hp": 0, "eid": None, "prop": "box", "x": 0.0, "z": 0.0, "ry": 0.0, "last_pos": 0.0, "last_shot": 0.0, "swaps": 0, "hold": 0.0, "score": 0}

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
		spawns = list(self.map["hider_spawns"])
		self.rng.shuffle(spawns)
		props = sorted({pr["type"] for pr in self.map["props"]} - set(BIG_PROPS))   # 이 맵에 있는 물건 가운데서
		used_eids = set()
		self.removed = set()
		for i, pid in enumerate(self.order):
			p = self.players[pid]
			p.update(alive=True, last_pos=now, last_shot=0.0, swaps=0, hold=0.0)   # 첫 위치도 시작 뒤 걸린 시간만큼만 움직일 수 있게
			if pid == seeker:
				p.update(role="seeker", hp=SEEKER_HP, eid=None, x=float(self.map["seeker_spawn"][0]), z=float(self.map["seeker_spawn"][1]), ry=0.0)
			else:
				eid = "e" + secrets.token_hex(3)
				while eid in used_eids:
					eid = "e" + secrets.token_hex(3)
				used_eids.add(eid)
				sx, sz = spawns[i % len(spawns)]
				p.update(role="hider", hp=HIDER_HP, eid=eid, prop=self.rng.choice(props), x=float(sx), z=float(sz), ry=0.0, swaps=SWAPS)
		self.status, self.until = "hide", now + self.hide_time
		self.result = None
		room.emit({"type": "round", "round": self.round})
		room.notice(f"🫥 {self.round}판 시작! 술래는 {self.players[seeker]['name']} 님 — {self.hide_time}초 동안 숨으세요.")

	def _finish(self, room, winner, reason):
		self.status = "over"
		self.until = 0.0
		caught = [self.players[pid]["name"] for pid in self.order if self.players[pid]["role"] == "hider" and not self.players[pid]["alive"]]
		alive = [self.players[pid]["name"] for pid in self._alive_hiders()]
		if winner == "hiders":
			for pid in self._alive_hiders():
				self.players[pid]["score"] += 2
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
			key = data.get("map")
			if key in MAPS and key != self.map["key"]:
				self.map = MAPS[key]
				self.prop_by_id = {pr["id"]: pr for pr in self.map["props"]}
				self.removed = set()
				self._send_map(room)
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
			src = self.prop_by_id.get(data.get("from"))
			if src is not None and src["id"] in self.removed:
				return False, "그 물건은 이제 없어요."
			if src is not None and (src["type"] != prop or _dist((p["x"], p["z"]), (src["x"], src["z"])) > 4.0):
				return False, "너무 멀어요 — 가까이 가서 변신하세요."
			p["prop"] = prop
			room.emit({"type": "disguise", "id": p["eid"], "prop": prop})
			return False, None

		if kind == "swap":
			return self._on_swap(room, p, data, now)

		if kind == "shoot":
			return self._on_shoot(room, peer.pid, p, data, now)

		return False, None

	def _on_swap(self, room, p, data, now):
		"""진짜 물건을 치우고 그 자리에 들어가기."""
		if p["role"] != "hider" or not p["alive"] or self.status not in ("hide", "seek"):
			return False, None
		if p["swaps"] <= 0:
			return False, "자리 바꾸기를 다 썼어요."
		src = self.prop_by_id.get(data.get("prop"))
		if src is None or src["id"] in self.removed:
			return False, "그 물건은 이제 없어요."
		if _dist((p["x"], p["z"]), (src["x"], src["z"])) > SWAP_RANGE:
			return False, "너무 멀어요 — 가까이 가서 바꾸세요."
		self.removed.add(src["id"])
		p.update(prop=src["type"], x=float(src["x"]), z=float(src["z"]), ry=float(src["ry"]), swaps=p["swaps"] - 1, last_pos=now, hold=now + SWAP_HOLD)
		room.emit({"type": "swap", "id": p["eid"], "prop": src["id"], "kind": src["type"], "x": src["x"], "z": src["z"], "ry": src["ry"]})
		return True, None

	def _on_pos(self, room, pid, p, data, now):
		if self.status not in ("hide", "seek") or not p["alive"] or not p["role"]:
			return False, None
		if p["role"] == "seeker" and self.status == "hide":
			return False, None   # 눈 감는 동안은 못 움직임
		if now < p["hold"] or now - p["last_pos"] < POS_MIN_INTERVAL:
			return False, None
		try:
			x, z, ry = float(data.get("x")), float(data.get("z")), float(data.get("ry", 0.0))
		except (TypeError, ValueError):
			return False, None
		if not all(math.isfinite(v) for v in (x, z, ry)):
			return False, None
		x = min(max(x, 0.2), self.map["w"] - 0.2)
		z = min(max(z, 0.2), self.map["d"] - 0.2)
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
		elif target in self.prop_by_id and target not in self.removed:
			pr = self.prop_by_id[target]
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
				p["score"] += 1
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
			"map": self.map["key"], "map_choices": [[k, m["name"]] for k, m in MAPS.items()],
			"players": [{"name": self.players[q]["name"], "role": self.players[q]["role"], "alive": self.players[q]["alive"], "me": q == pid, "host": q == self.host, "score": self.players[q]["score"]} for q in self.order],
			"me": None if not me else {"role": me["role"], "alive": me["alive"], "hp": me["hp"], "eid": me["eid"], "prop": me["prop"], "x": me["x"], "z": me["z"], "ry": me["ry"], "swaps": me["swaps"]},
			"removed": sorted(self.removed),
			"ents": ents,
			"seeker": seeker,
			"result": self.result,
			"rules": {"hit": HIT_DAMAGE, "miss": MISS_PENALTY, "taunt": TAUNT_EVERY, "range": SHOOT_RANGE, "swaps": SWAPS, "swap_range": SWAP_RANGE, "map_show": MAP_SHOW, "map_cool": MAP_COOLDOWN},
		}
