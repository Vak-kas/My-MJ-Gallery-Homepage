"""랭킹 API: 게임 시작(서버가 seed·문장을 정함) → 끝나면 서버가 직접 점수 계산 → 회원이면 저장."""

import json
import random
import secrets
import time

from django.core.cache import cache
from django.db.models import Max
from django.http import JsonResponse
from django.views.decorators.http import require_GET, require_POST

from . import typing
from .engine2048 import replay
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


def leaderboard(board, user=None):
	best = (Score.objects.filter(board=board).values("user", "user__username")
			.annotate(best=Max("score")).order_by("-best", "user")[:TOP])
	rows = [{"rank": i + 1, "name": r["user__username"], "score": r["best"], "me": bool(user and user.is_authenticated and r["user"] == user.id)}
			for i, r in enumerate(best)]
	mine = None
	if user and user.is_authenticated:
		my_best = Score.objects.filter(board=board, user=user).aggregate(b=Max("score"))["b"]
		if my_best is not None:
			higher = (Score.objects.filter(board=board).values("user").annotate(best=Max("score")).filter(best__gt=my_best).count())
			mine = {"score": my_best, "rank": higher + 1}
	return {"board": board, "rows": rows, "mine": mine}


def _save(request, board, score, detail):
	"""회원이면 저장. 새 개인 최고 기록인지도 알려줌."""
	if not request.user.is_authenticated:
		return {"saved": False, "login": True}
	prev = Score.objects.filter(board=board, user=request.user).aggregate(b=Max("score"))["b"]
	Score.objects.create(board=board, user=request.user, score=score, detail=detail)
	return {"saved": True, "best": prev is None or score > prev}


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
