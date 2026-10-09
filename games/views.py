from django.shortcuts import render
from django.views.decorators.csrf import ensure_csrf_cookie
from django.urls import reverse

from .registry import CATEGORIES, GAMES
from .scores import leaderboard
from .typing import LANGS, MIN_ACCURACY, ROUND


def index(request):
	sections = []
	for key, icon, title, note in CATEGORIES:
		items = [{**g, "url": reverse(g["url_name"]) if g["url_name"] else None} for g in GAMES if g["category"] == key]
		if items:
			sections.append({"key": key, "icon": icon, "title": title, "note": note, "games": items})
	return render(request, "games/index.html", {"sections": sections, "ready_count": sum(1 for g in GAMES if g["url_name"])})


def ladder(request):
	return render(request, "games/ladder.html")


def roulette(request):
	return render(request, "games/roulette.html")


def seconds(request):
	return render(request, "games/seconds.html")


def reaction(request):
	return render(request, "games/reaction.html")


def bomb(request):
	return render(request, "games/bomb.html")


def updown(request):
	return render(request, "games/updown.html")


def cards(request):
	return render(request, "games/cards.html")


@ensure_csrf_cookie
def g2048(request):
	return render(request, "games/2048.html", {"board": leaderboard("2048", request.user)})


@ensure_csrf_cookie
def typing_page(request):
	boards = [(lang, label, leaderboard(f"typing-{lang}", request.user)) for lang, label in LANGS.items()]
	return render(request, "games/typing.html", {"langs": LANGS, "boards": boards, "round": ROUND, "min_accuracy": MIN_ACCURACY})
