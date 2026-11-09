"""Studio › Categories — 블로그 카테고리 추가·수정·순서·노출·삭제.

글(Post.category)에는 slug 가 들어가므로 slug 를 바꾸면 글도 같이 옮기고,
지울 때 글이 남아 있으면 다른 카테고리로 옮긴 뒤 지운다 (글은 절대 안 지움).
"""

from django.contrib import messages
from django.db import transaction
from django.db.models import Count, Max
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from blog import categories as cat_lookup
from blog.models import Category, Post

from .. import site_settings
from .common import admin_view

TOGGLES = ("is_private", "show_on_hub", "show_on_home", "in_topic_map")


def _form(request, current_slug=None):
	"""폼 값 읽기 + 검사. (값 dict, 오류 문구 또는 None)"""
	data = {
		"slug": (request.POST.get("slug") or "").strip().lower(),
		"name": " ".join((request.POST.get("name") or "").split())[:30],
		"description": " ".join((request.POST.get("description") or "").split())[:120],
		"color": (request.POST.get("color") or "").strip(),
		"icon": (request.POST.get("icon") or "").strip()[:8] or "📝",
	}
	goal = (request.POST.get("weekly_goal") or "0").strip()
	data["weekly_goal"] = max(0, min(site_settings.BLOG_GOAL_MAX, int(goal))) if goal.isdigit() else 0
	for key in TOGGLES:
		data[key] = request.POST.get(key) == "on"
	if not data["name"]:
		return data, "이름을 입력해 주세요."
	error = cat_lookup.validate_slug(data["slug"], current=current_slug)
	if error:
		return data, error
	if not cat_lookup.COLOR_RE.match(data["color"]):
		return data, "색은 #RRGGBB 형식으로 골라 주세요."
	return data, None


@admin_view
def categories(request):
	counts = dict(Post.objects.values_list("category").annotate(n=Count("id")).values_list("category", "n"))
	items = list(Category.objects.all())
	for c in items:
		c.post_count = counts.get(c.slug, 0)
		c.url = reverse("blog:category", args=[c.slug])
	known = {c.slug for c in items}
	orphans = sorted((slug, n) for slug, n in counts.items() if slug not in known)   # 표에 없는 카테고리 값을 가진 글 (공개 목록엔 안 보임)
	editing_id = request.GET.get("edit", "")
	return render(request, "studio/categories.html", {
		"items": items,
		"orphans": orphans,
		"editing_id": int(editing_id) if editing_id.isdigit() else None,
		"goal_max": site_settings.BLOG_GOAL_MAX,
		"reserved": sorted(cat_lookup.RESERVED),
	})


@admin_view
def category_create(request):
	if request.method != "POST":
		return redirect("studio:categories")
	data, error = _form(request)
	if error:
		messages.error(request, error)
		return redirect("studio:categories")
	order = (Category.objects.aggregate(m=Max("order"))["m"] or 0) + 1
	Category.objects.create(order=order, **data)
	messages.success(request, f"'{data['name']}' 카테고리를 만들었어요. 주소는 /blog/{data['slug']}/ 예요.")
	return redirect("studio:categories")


@admin_view
def category_update(request, id):
	cat = get_object_or_404(Category, id=id)
	if request.method != "POST":
		return redirect("studio:categories")
	data, error = _form(request, current_slug=cat.slug)
	if error:
		messages.error(request, error)
		return redirect(f"{reverse('studio:categories')}?edit={id}#cat-{id}")
	old_slug = cat.slug
	with transaction.atomic():
		for key, value in data.items():
			setattr(cat, key, value)
		cat.save()
		moved = Post.objects.filter(category=old_slug).update(category=cat.slug) if old_slug != cat.slug else 0
	note = f" 주소가 /blog/{cat.slug}/ 로 바뀌었고 글 {moved}편도 같이 옮겼어요." if old_slug != cat.slug else ""
	messages.success(request, f"'{cat.name}' 카테고리를 저장했어요.{note}")
	return redirect("studio:categories")


@admin_view
def category_move(request, id):
	"""▲▼ 순서 바꾸기 — 이웃과 자리 바꿈"""
	cat = get_object_or_404(Category, id=id)
	if request.method == "POST":
		items = list(Category.objects.all())
		i = next(k for k, c in enumerate(items) if c.id == cat.id)
		j = i - 1 if request.POST.get("direction") == "up" else i + 1
		if 0 <= j < len(items):
			items[i], items[j] = items[j], items[i]
			with transaction.atomic():
				for order, c in enumerate(items):
					if c.order != order:
						c.order = order
						c.save(update_fields=["order"])
	return redirect(f"{reverse('studio:categories')}#cat-{cat.id}")


@admin_view
def category_delete(request, id):
	cat = get_object_or_404(Category, id=id)
	if request.method != "POST":
		return redirect("studio:categories")
	if Category.objects.count() <= 1:
		messages.error(request, "카테고리는 하나 이상 있어야 해요.")
		return redirect("studio:categories")
	if (request.POST.get("confirm") or "").strip() != cat.slug:
		messages.error(request, f"지우려면 확인 칸에 주소 '{cat.slug}' 를 그대로 입력해 주세요.")
		return redirect(f"{reverse('studio:categories')}#cat-{cat.id}")
	count = Post.objects.filter(category=cat.slug).count()
	target = None
	if count:
		target = Category.objects.exclude(id=cat.id).filter(slug=(request.POST.get("move_to") or "").strip()).first()
		if not target:
			messages.error(request, f"이 카테고리에 글이 {count}편 있어요. 옮길 카테고리를 골라 주세요.")
			return redirect(f"{reverse('studio:categories')}#cat-{cat.id}")
	with transaction.atomic():
		if target:
			Post.objects.filter(category=cat.slug).update(category=target.slug)
		name = cat.name
		cat.delete()
	moved = f" 글 {count}편은 '{target.name}' 으로 옮겼어요." if target else ""
	messages.success(request, f"'{name}' 카테고리를 지웠어요.{moved}")
	return redirect("studio:categories")
