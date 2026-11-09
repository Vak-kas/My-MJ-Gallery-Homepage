"""블로그 카테고리 조회 도우미 — Category 표(몇 줄 안 됨)를 요청 하나 안에서만 기억해 두고 씀.

요청마다 처음 한 번만 DB 에서 읽어서, 여러 서버 프로세스 사이에 옛 값이 남지 않음.
요청 밖(관리 명령·테스트에서 직접 부를 때)은 매번 읽음. 저장·삭제하면 clear_cache() 로 바로 비움.
"""

import re
import threading
from types import SimpleNamespace

from django.core.signals import request_finished, request_started

_local = threading.local()

# /blog/<slug>/ 와 겹치면 안 되는 주소 (블로그의 다른 페이지)
RESERVED = {"write", "post", "series", "all", "board", "api", "category", "categories", "feed", "rss", "tag", "tags", "search", "admin", "static", "media"}
SLUG_RE = re.compile(r"^[a-z][a-z0-9-]{0,29}$")
COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def _load():
	from .models import Category

	return [
		SimpleNamespace(
			id=c.id, slug=c.slug, name=c.name, description=c.description, color=c.color, soft_color=c.soft_color,
			icon=c.icon or "📝", order=c.order, is_private=c.is_private, show_on_hub=c.show_on_hub,
			show_on_home=c.show_on_home, in_topic_map=c.in_topic_map, weekly_goal=c.weekly_goal,
		)
		for c in Category.objects.all()
	]


def all_categories():
	items = getattr(_local, "items", None)
	if items is None:
		items = _load()
		if getattr(_local, "in_request", False):
			_local.items = items
	return items


def clear_cache():
	_local.items = None


def _request_started(**kwargs):
	_local.in_request = True
	_local.items = None


def _request_finished(**kwargs):
	_local.in_request = False
	_local.items = None


request_started.connect(_request_started, dispatch_uid="blog_categories_request_started")
request_finished.connect(_request_finished, dispatch_uid="blog_categories_request_finished")


def visible_to(user):
	"""이 사람에게 보이는 카테고리 (관리자 전용은 관리자에게만)"""
	admin = getattr(user, "is_superuser", False)
	return [c for c in all_categories() if admin or not c.is_private]


def slugs():
	return [c.slug for c in all_categories()]


def private_slugs():
	return [c.slug for c in all_categories() if c.is_private]


def topic_map_slugs():
	return [c.slug for c in all_categories() if c.in_topic_map]


def get(slug):
	for c in all_categories():
		if c.slug == slug:
			return c
	# 지워진 카테고리에 남은 글: 이름만 slug 로, 관리자 전용처럼 다룸
	return SimpleNamespace(id=None, slug=slug, name=slug, description="", color="#6e6e73", soft_color="#6e6e731a", icon="📝",
		order=9999, is_private=True, show_on_hub=False, show_on_home=False, in_topic_map=False, weekly_goal=0)


def exists(slug):
	return any(c.slug == slug for c in all_categories())


def is_private(slug):
	return get(slug).is_private


def hex_to_rgb(color):
	color = color if COLOR_RE.match(color or "") else "#0066cc"
	return tuple(int(color[i:i + 2], 16) for i in (1, 3, 5))


def validate_slug(slug, current=None):
	"""주소로 쓸 수 있는지. 문제가 있으면 안내 문구, 괜찮으면 None"""
	if not SLUG_RE.match(slug or ""):
		return "주소는 영어 소문자로 시작하고 영어 소문자·숫자·하이픈(-)만, 30자까지 쓸 수 있어요."
	if slug in RESERVED:
		return f"'{slug}' 는 블로그의 다른 페이지 주소라 쓸 수 없어요."
	if slug != current and exists(slug):
		return f"'{slug}' 주소를 쓰는 카테고리가 이미 있어요."
	return None


def public_slugs():
	"""누구에게나 보이는 카테고리 slug — 공개 목록·피드·사이트맵은 이 안의 글만 (표에 없는 값의 글은 숨김)"""
	return [c.slug for c in all_categories() if not c.is_private]
