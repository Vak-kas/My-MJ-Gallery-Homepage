"""랭킹 API: 게임 시작(서버가 seed·문장을 정함) → 끝나면 서버가 직접 점수 계산 → 회원이면 저장."""

import json
import random
import secrets
import time

from django.core.cache import cache
from django.db.models import Max, Min
from django.http import JsonResponse
from django.views.decorators.http import require_GET, require_POST

from . import sudoku, trace, typing
from .engine2048 import replay
from .mines import LEVELS as MINE_LEVELS, Board as MineBoard
from .models import Score

SESSION_TTL = 6 * 60 * 60
MAX_MOVES = 30_000
TOP = 10


def _json(request):
	try:
		return json.loads(request.body or b"{}")
	except ValueError:
		return {}


def _err(msg, status=400):
	return JsonResponse({"ok": False, "error": msg}, status=status)


def is_time(board):
	"""걸린 시간(ms) 랭킹 — 짧을수록 위."""
	return board.startswith(("sudoku-", "mines-"))


def time_text(ms):
	s = ms / 1000
	return f"{int(s // 60)}:{s % 60:04.1f}" if s >= 60 else f"{s:.1f}초"


def leaderboard(board, user=None):
	low = is_time(board)
	agg, order, better = (Min, "best", "best__lt") if low else (Max, "-best", "best__gt")
	text = time_text if low else (lambda v: None)
	best = (Score.objects.filter(board=board).values("user", "user__username")
			.annotate(best=agg("score")).order_by(order, "user")[:TOP])
	rows = [{"rank": i + 1, "name": r["user__username"], "score": r["best"], "text": text(r["best"]), "me": bool(user and user.is_authenticated and r["user"] == user.id)}
			for i, r in enumerate(best)]
	mine = None
	if user and user.is_authenticated:
		my_best = Score.objects.filter(board=board, user=user).aggregate(b=agg("score"))["b"]
		if my_best is not None:
			ahead = (Score.objects.filter(board=board).values("user").annotate(best=agg("score")).filter(**{better: my_best}).count())
			mine = {"score": my_best, "text": text(my_best), "rank": ahead + 1}
	return {"board": board, "rows": rows, "mine": mine}


def _save(request, board, score, detail):
	"""회원이면 저장. 새 개인 최고 기록인지도 알려줌."""
	if not request.user.is_authenticated:
		return {"saved": False, "login": True}
	low = is_time(board)
	prev = Score.objects.filter(board=board, user=request.user).aggregate(b=(Min if low else Max)("score"))["b"]
	Score.objects.create(board=board, user=request.user, score=score, detail=detail)
	return {"saved": True, "best": prev is None or (score < prev if low else score > prev)}


def _session(data, prefix):
	key = f"{prefix}:{str(data.get('token') or '')[:64]}"
	return key, cache.get(key)


@require_GET
def board_view(request, board):
	if board not in dict(Score.BOARDS):
		return _err("없는 랭킹이에요.", 404)
	return JsonResponse(leaderboard(board, request.user))


# ── 2048 ──

@require_POST
def g2048_start(request):
	token = secrets.token_urlsafe(16)
	seed = secrets.randbits(32)
	cache.set(f"g2048:{token}", {"seed": seed, "t": time.time()}, SESSION_TTL)
	return JsonResponse({"token": token, "seed": seed})


@require_POST
def g2048_submit(request):
	data = _json(request)
	key = f"g2048:{str(data.get('token') or '')[:64]}"
	session = cache.get(key)
	if not session:
		return _err("게임 정보가 없어요. 새 게임으로 다시 해 주세요.")
	moves = str(data.get("moves") or "")
	if len(moves) > MAX_MOVES or set(moves) - set("UDLR"):
		return _err("움직임 기록이 올바르지 않아요.")
	cache.delete(key)  # 한 판은 한 번만 등록
	game = replay(session["seed"], moves)
	detail = {"max_tile": max(game.board), "moves": game.moves, "seconds": round(time.time() - session["t"])}
	return JsonResponse({"ok": True, "score": game.score, **detail, **_save(request, "2048", game.score, detail), "leaderboard": leaderboard("2048", request.user)})


# ── 타자 연습 ──

@require_POST
def typing_start(request):
	lang = _json(request).get("lang")
	if lang not in typing.TEXTS:
		lang = "ko"
	idx = random.sample(range(len(typing.TEXTS[lang])), typing.ROUND)
	token = secrets.token_urlsafe(16)
	cache.set(f"typing:{token}", {"lang": lang, "idx": idx, "t": time.time()}, SESSION_TTL)
	return JsonResponse({"token": token, "lang": lang, "texts": [typing.TEXTS[lang][i] for i in idx]})


@require_POST
def typing_submit(request):
	data = _json(request)
	key = f"typing:{str(data.get('token') or '')[:64]}"
	session = cache.get(key)
	if not session:
		return _err("연습 정보가 없어요. 새로 시작해 주세요.")
	typed = data.get("typed")
	if not isinstance(typed, list) or len(typed) != typing.ROUND:
		return _err("입력한 문장 수가 맞지 않아요.")
	cache.delete(key)
	targets = [typing.TEXTS[session["lang"]][i] for i in session["idx"]]
	# 시간은 서버 기준 (시작 뒤 3초 세는 동안은 빼 줌) — 브라우저가 보낸 시간보다 짧게는 인정 안 함
	server = time.time() - session["t"] - 3
	try:
		client = float(data.get("seconds") or 0)
	except (TypeError, ValueError):
		client = 0
	seconds = max(server - 2, min(client, server)) if client > 0 else server
	result = typing.grade(targets, [str(t or "") for t in typed], max(seconds, 1))
	board = f"typing-{session['lang']}"
	saved = {"saved": False, "reason": "accuracy"}
	if result["cpm"] > typing.MAX_CPM:
		saved = {"saved": False, "reason": "speed"}
	elif result["accuracy"] >= typing.MIN_ACCURACY:
		saved = _save(request, board, result["cpm"], result)
	return JsonResponse({"ok": True, **result, **saved, "min_accuracy": typing.MIN_ACCURACY, "leaderboard": leaderboard(board, request.user)})


# ── 스도쿠 ──

@require_POST
def sudoku_start(request):
	level = _json(request).get("level")
	if level not in sudoku.LEVELS:
		level = "normal"
	puzzle, solution = sudoku.generate(level)
	token = secrets.token_urlsafe(16)
	cache.set(f"sudoku:{token}", {"level": level, "puzzle": puzzle, "solution": solution, "t": time.time(), "hints": 0}, SESSION_TTL)
	return JsonResponse({"token": token, "level": level, "puzzle": puzzle})


@require_POST
def sudoku_hint(request):
	"""틀린 칸이 있으면 그 칸, 없으면 빈칸 하나의 답. 힌트를 쓰면 랭킹엔 안 올라감."""
	data = _json(request)
	key, session = _session(data, "sudoku")
	if not session:
		return _err("게임 정보가 없어요. 새 문제로 다시 해 주세요.")
	grid = str(data.get("grid") or "")
	if len(grid) != 81 or not grid.isdigit():
		return _err("판 정보가 올바르지 않아요.")
	sol = session["solution"]
	wrong = [i for i in range(81) if grid[i] != "0" and grid[i] != sol[i]]
	empty = [i for i in range(81) if grid[i] == "0"]
	if not wrong and not empty:
		return _err("고칠 칸이 없어요.")
	i = wrong[0] if wrong else random.choice(empty)
	session["hints"] += 1
	cache.set(key, session, SESSION_TTL)
	return JsonResponse({"ok": True, "i": i, "v": int(sol[i]), "wrong": bool(wrong), "hints": session["hints"]})


@require_POST
def sudoku_submit(request):
	data = _json(request)
	key, session = _session(data, "sudoku")
	if not session:
		return _err("게임 정보가 없어요. 새 문제로 다시 해 주세요.")
	if not sudoku.is_solved(session["puzzle"], session["solution"], str(data.get("grid") or "")):
		return _err("아직 답이 맞지 않아요.")  # 판은 그대로 두고 계속 풀 수 있게
	cache.delete(key)
	ms = round((time.time() - session["t"]) * 1000)
	board = f"sudoku-{session['level']}"
	detail = {"level": session["level"], "hints": session["hints"]}
	saved = {"saved": False, "reason": "hint"} if session["hints"] else _save(request, board, ms, detail)
	return JsonResponse({"ok": True, "ms": ms, "text": time_text(ms), **detail, **saved, "leaderboard": leaderboard(board, request.user)})


# ── 지뢰찾기 ──

@require_POST
def mines_start(request):
	level = _json(request).get("level")
	b = MineBoard(level)
	token = secrets.token_urlsafe(16)
	cache.set(f"mines:{token}", {"board": b, "t": None}, SESSION_TTL)
	return JsonResponse({"token": token, "level": b.level, "rows": b.rows, "cols": b.cols, "count": b.count})


@require_POST
def mines_open(request):
	"""칸 열기. 숫자 칸 주변 한꺼번에 열기(깃발 수가 맞을 때)는 브라우저가 열 칸 목록을 보냄."""
	data = _json(request)
	key, session = _session(data, "mines")
	if not session:
		return _err("게임 정보가 없어요. 새 게임으로 다시 해 주세요.")
	cells = data.get("cells")
	if not isinstance(cells, list) or not cells or len(cells) > 8:
		return _err("열 칸이 올바르지 않아요.")
	b = session["board"]
	if b.state in ("won", "lost"):
		return _err("이미 끝난 판이에요.")
	shown = b.open([c for c in cells if isinstance(c, int) and not isinstance(c, bool)])
	if session["t"] is None and b.state != "ready":
		session["t"] = time.time()  # 시간은 첫 칸을 연 순간부터
	res = {"ok": True, "shown": {str(i): n for i, n in shown.items()}, "state": b.state}
	if b.state in ("won", "lost"):
		cache.delete(key)
		res["mines"] = sorted(b.mines)
		res["boom"] = b.boom
		ms = round((time.time() - session["t"]) * 1000)
		res.update(ms=ms, text=time_text(ms))
		if b.state == "won":
			board = f"mines-{b.level}"
			res.update(_save(request, board, ms, {"level": b.level}), leaderboard=leaderboard(board, request.user))
	else:
		cache.set(key, session, SESSION_TTL)
	return JsonResponse(res)


# ── 따라그리기 ──

@require_POST
def trace_start(request):
	mode = _json(request).get("mode")
	if mode not in trace.MODES:
		mode = "trace"
	shapes = random.sample(list(trace.SHAPES), trace.ROUND)
	token = secrets.token_urlsafe(16)
	cache.set(f"trace:{token}", {"mode": mode, "shapes": shapes, "scores": []}, SESSION_TTL)
	return JsonResponse({"token": token, "mode": mode, "memory_seconds": trace.MEMORY_SECONDS,
						 "shapes": [{"key": k, "label": trace.SHAPES[k][0], "points": trace.SHAPES[k][1]} for k in shapes]})


@require_POST
def trace_draw(request):
	"""도형 하나를 그릴 때마다 채점. 다섯 개를 다 그리면 합계로 랭킹."""
	data = _json(request)
	key, session = _session(data, "trace")
	if not session:
		return _err("게임 정보가 없어요. 새로 시작해 주세요.")
	i = len(session["scores"])
	if data.get("i") != i:
		return _err("이미 채점한 도형이에요.")
	shape = session["shapes"][i]
	got = trace.score(shape, data.get("strokes"))
	session["scores"].append(got)
	res = {"ok": True, "i": i, "score": got, "label": trace.SHAPES[shape][0], "done": len(session["scores"]) == trace.ROUND}
	if res["done"]:
		cache.delete(key)
		total = sum(session["scores"])
		board = f"trace-{session['mode']}"
		res.update(total=total, scores=session["scores"], **_save(request, board, total, {"scores": session["scores"], "shapes": session["shapes"]}),
				   leaderboard=leaderboard(board, request.user))
	else:
		cache.set(key, session, SESSION_TTL)
	return JsonResponse(res)
