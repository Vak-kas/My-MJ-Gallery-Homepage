from django.shortcuts import render
from django.urls import reverse

from .registry import TOOLS


def index(request):
	tools = [{**tool, "url": reverse(tool["url_name"])} for tool in TOOLS]
	return render(request, "tools/index.html", {"tools": tools})


def duplex(request):
	return render(request, "tools/duplex.html")


def subnet(request):
	return render(request, "tools/subnet.html")
