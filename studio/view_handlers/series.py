"""Studio › Series — 시리즈(재생목록) 추가·수정·순서·노출·삭제, 시리즈 안 글 순서·추가·빼기.

시리즈를 지워도 글은 그대로 두고 시리즈 연결만 끊는다.
"""

from django.contrib import messages
from django.db import transaction
from django.db.models import Count, Max, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.text import slugify

from blog.models import Post, Series

from .common import admin_view


def _back(series_id=None, edit=False):
	url = reverse("studio:series")
	if series_id:
		url += f"?{'edit' if edit else 'open'}={series_id}#series-{series_id}"
	return redirect(url)


def _form(request, series=None):
	"""폼 값 읽기 + 검사. (값 dict, 오류 문구 또는 None)"""
	data = {
		"name": " ".join((request.POST.get("name") or "").split())[:80],
		"description": " ".join((request.POST.get("description") or "").split())[:200],
		"is_listed": request.POST.get("is_listed") == "on",
		"show_on_hub": request.POST.get("show_on_hub") == "on",
	}
	if not data["name"]:
		return data, "이름을 입력해 주세요."
	raw_slug = (request.POST.get("slug") or "").strip() or data["name"]
	data["slug"] = slugify(raw_slug, allow_unicode=True)[:100]
	if not data["slug"]:
		return data, "주소로 쓸 수 있는 글자(한글·영어·숫자·-)를 넣어 주세요."
	others = Series.objects.exclude(id=series.id) if series else Series.objects.all()
	if others.filter(slug=data["slug"]).exists():
		return data, f"주소 '{data['slug']}' 는 다른 시리즈가 쓰고 있어요."
	author = series.author if series else request.user
	if others.filter(author=author, name=data["name"]).exists():
		return data, f"'{data['name']}' 이름의 시리즈가 이미 있어요."
	return data, None


def _post_id(request):
	raw = (request.POST.get("post_id") or "").strip()
	return int(raw) if raw.isdigit() else 0


def _parts(series):
	"""시리즈 안 글 (임시글 포함) — 번호 순"""
	return list(Post.objects.filter(series=series).order_by("series_order", "published_at", "id"))


def _renumber(parts):
	with transaction.atomic():
		for n, post in enumerate(parts, start=1):
			if post.series_order != n:
				post.series_order = n
				post.save(update_fields=["series_order"])


@admin_view
def series(request):
	items = list(Series.objects.select_related("author").annotate(
		post_count=Count("posts"),
		published_count=Count("posts", filter=Q(posts__is_published=True)),
	))
	open_id = request.GET.get("open", "")
	edit_id = request.GET.get("edit", "")
	open_id = int(open_id) if open_id.isdigit() else None
	edit_id = int(edit_id) if edit_id.isdigit() else None
	for s in items:
		s.url = reverse("blog:series", args=[s.slug])
		s.draft_count = s.post_count - s.published_count
		if s.id in (open_id, edit_id):
			s.parts = _parts(s)
	# 시리즈에 넣을 수 있는 글 (어느 시리즈에도 없는 글)
	free_posts = list(Post.objects.filter(series__isnull=True).order_by("-published_at", "-id")
					  .only("id", "title", "is_published", "published_at", "category")[:300])
	return render(request, "studio/series.html", {
		"items": items,
		"open_id": open_id,
		"editing_id": edit_id,
		"free_posts": free_posts,
	})


@admin_view
def series_create(request):
	if request.method != "POST":
		return _back()
	data, error = _form(request)
	if error:
		messages.error(request, error)
		return _back()
	order = (Series.objects.aggregate(m=Max("order"))["m"] or 0) + 1
	s = Series.objects.create(author=request.user, order=order, **data)
	messages.success(request, f"'{s.name}' 시리즈를 만들었어요. 아래에서 글을 넣거나, 글쓰기 화면에서 이 시리즈를 고르면 돼요.")
	return _back(s.id)


@admin_view
def series_update(request, id):
	s = get_object_or_404(Series, id=id)
	if request.method != "POST":
		return _back(id)
	data, error = _form(request, series=s)
	if error:
		messages.error(request, error)
		return _back(id, edit=True)
	old_slug = s.slug
	for key, value in data.items():
		setattr(s, key, value)
	s.save()
	note = f" 주소가 /blog/series/{s.slug}/ 로 바뀌었어요(옛 주소 링크는 끊겨요)." if old_slug != s.slug else ""
	messages.success(request, f"'{s.name}' 시리즈를 저장했어요.{note}")
	return _back(id)


@admin_view
def series_move(request, id):
	"""▲▼ 시리즈 순서 바꾸기 — 이웃과 자리 바꿈"""
	s = get_object_or_404(Series, id=id)
	if request.method == "POST":
		items = list(Series.objects.all())
		i = next(k for k, x in enumerate(items) if x.id == s.id)
		j = i - 1 if request.POST.get("direction") == "up" else i + 1
		if 0 <= j < len(items):
			items[i], items[j] = items[j], items[i]
			with transaction.atomic():
				for order, x in enumerate(items):
					if x.order != order:
						x.order = order
						x.save(update_fields=["order"])
	return redirect(f"{reverse('studio:series')}#series-{s.id}")


@admin_view
def series_delete(request, id):
	s = get_object_or_404(Series, id=id)
	if request.method != "POST":
		return _back(id)
	if (request.POST.get("confirm") or "").strip() != s.name:
		messages.error(request, f"지우려면 확인 칸에 시리즈 이름 '{s.name}' 을 그대로 입력해 주세요.")
		return _back(id, edit=True)
	with transaction.atomic():
		count = Post.objects.filter(series=s).update(series=None, series_order=None)
		name = s.name
		s.delete()
	messages.success(request, f"'{name}' 시리즈를 지웠어요." + (f" 글 {count}편은 그대로 남고 시리즈에서만 빠졌어요." if count else ""))
	return _back()


@admin_view
def series_part_move(request, id):
	"""시리즈 안 글 순서 ▲▼ — 번호를 1편부터 다시 매김"""
	s = get_object_or_404(Series, id=id)
	if request.method == "POST":
		parts = _parts(s)
		post_id = _post_id(request)
		i = next((k for k, p in enumerate(parts) if p.id == post_id), None)
		if i is not None:
			j = i - 1 if request.POST.get("direction") == "up" else i + 1
			if 0 <= j < len(parts):
				parts[i], parts[j] = parts[j], parts[i]
			_renumber(parts)
	return _back(id)


@admin_view
def series_part_add(request, id):
	s = get_object_or_404(Series, id=id)
	if request.method == "POST":
		post = Post.objects.filter(id=_post_id(request)).first()
		if not post:
			messages.error(request, "넣을 글을 골라 주세요.")
		elif post.series_id == s.id:
			messages.info(request, "이미 이 시리즈에 있는 글이에요.")
		else:
			last = Post.objects.filter(series=s).aggregate(m=Max("series_order"))["m"] or 0
			post.series, post.series_order = s, last + 1
			post.save(update_fields=["series", "series_order"])
			messages.success(request, f"'{post.title}' 을 {last + 1}편으로 넣었어요.")
	return _back(id)


@admin_view
def series_part_remove(request, id):
	s = get_object_or_404(Series, id=id)
	if request.method == "POST":
		post = Post.objects.filter(series=s, id=_post_id(request)).first()
		if post:
			post.series, post.series_order = None, None
			post.save(update_fields=["series", "series_order"])
			_renumber(_parts(s))
			messages.success(request, f"'{post.title}' 을 시리즈에서 뺐어요. 글은 그대로 있어요.")
	return _back(id)
