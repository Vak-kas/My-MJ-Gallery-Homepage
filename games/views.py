from django.shortcuts import render
from django.urls import reverse

from .registry import CATEGORIES, GAMES


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
