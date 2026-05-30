from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.http import Http404
from django.shortcuts import redirect, render
from django.utils import timezone
from django.utils.text import slugify
from urllib.parse import urlencode

from .models import Comment, GuestbookEntry, Post, Tag


def _published_posts_qs():
	return Post.objects.filter(is_published=True).prefetch_related("tags")


def _accessible_posts_qs(request):
	qs = _published_posts_qs()
	if request.user.is_superuser:
		return qs
	return qs.exclude(category=Post.CATEGORY_SECRET)


def _sidebar_context(request):
	post_comment_count = Count("comments", filter=Q(comments__is_visible=True), distinct=True)

	popular_posts = list(
		_accessible_posts_qs(request)
		.annotate(visible_comment_count=post_comment_count)
		.order_by("-views", "-visible_comment_count", "-published_at", "-id")[:10]
	)

	tag_filter = Q(posts__is_published=True)
	if not request.user.is_superuser:
		tag_filter &= ~Q(posts__category=Post.CATEGORY_SECRET)

	tags = list(
		Tag.objects.annotate(
			published_post_count=Count("posts", filter=tag_filter, distinct=True)
		)
		.filter(published_post_count__gt=0)
		.order_by("-published_post_count", "name")[:24]
	)

	recent_comment_qs = Comment.objects.select_related("post").filter(
		is_visible=True,
		post__is_published=True,
	)
	if not request.user.is_superuser:
		recent_comment_qs = recent_comment_qs.exclude(post__category=Post.CATEGORY_SECRET)

	recent_comments = list(recent_comment_qs.order_by("-created_at", "-id")[:8])

	guestbook_entries = list(
		GuestbookEntry.objects.filter(is_visible=True).order_by("-created_at", "-id")[:8]
	)

	return {
		"popular_posts": popular_posts,
		"tag_list": tags,
		"recent_comments": recent_comments,
		"guestbook_entries": guestbook_entries,
	}


def _category_page(request, category: str, page_title: str):
	if category == Post.CATEGORY_SECRET and not request.user.is_superuser:
		raise Http404("Not found")

	posts = list(
		_accessible_posts_qs(request)
		.filter(category=category)
		.annotate(visible_comment_count=Count("comments", filter=Q(comments__is_visible=True), distinct=True))
		.order_by("-published_at", "-id")[:18]
	)

	context = {
		"active_tab": category,
		"posts": posts,
		"page_title": page_title,
	}
	context.update(_sidebar_context(request))
	return context


def index(request):
	if request.method == "POST":
		author_name = (request.POST.get("author_name") or "").strip()
		message = (request.POST.get("message") or "").strip()

		if author_name and message:
			GuestbookEntry.objects.create(author_name=author_name[:60], message=message[:1000])
			messages.success(request, "방명록이 등록되었습니다.")
		else:
			messages.error(request, "이름과 메시지를 모두 입력해 주세요.")

		return redirect("blog:index")

	search_query = (request.GET.get("q") or "").strip()
	show_all = request.GET.get("show") == "all"
	current_sort = (request.GET.get("sort") or "latest").strip()
	if current_sort not in {"latest", "oldest", "popular"}:
		current_sort = "latest"

	mine_only = request.user.is_authenticated and request.GET.get("mine") == "1"
	page_limit = 10

	post_comment_count = Count("comments", filter=Q(comments__is_visible=True), distinct=True)
	feed_qs = _accessible_posts_qs(request).annotate(visible_comment_count=post_comment_count)

	if search_query:
		feed_qs = feed_qs.filter(
			Q(title__icontains=search_query)
			| Q(summary__icontains=search_query)
			| Q(content__icontains=search_query)
			| Q(tags__name__icontains=search_query)
		).distinct()

	if mine_only:
		feed_qs = feed_qs.filter(author=request.user)

	if current_sort == "oldest":
		order_fields = ("published_at", "id")
	elif current_sort == "popular":
		order_fields = ("-views", "-visible_comment_count", "-published_at", "-id")
	else:
		order_fields = ("-published_at", "-id")

	all_posts = list(feed_qs.order_by(*order_fields))

	def _query_link(**updates):
		params = {}
		if search_query:
			params["q"] = search_query
		if show_all:
			params["show"] = "all"
		params["sort"] = current_sort
		if mine_only:
			params["mine"] = "1"

		for key, value in updates.items():
			if value is None:
				params.pop(key, None)
			else:
				params[key] = value

		if params.get("sort") == "latest":
			params.pop("sort", None)
		if params.get("mine") != "1":
			params.pop("mine", None)

		query = urlencode(params)
		return f"?{query}" if query else ""
	feed_posts = all_posts if show_all else all_posts[:page_limit]
	has_more_posts = len(all_posts) > page_limit and not show_all

	context = {
		"active_tab": "hub",
		"show_secret": request.user.is_superuser,
		"current_sort": current_sort,
		"mine_only": mine_only,
		"search_query": search_query,
		"show_all": show_all,
		"page_limit": page_limit,
		"total_posts": len(all_posts),
		"has_more_posts": has_more_posts,
		"sort_latest_qs": _query_link(sort="latest"),
		"sort_oldest_qs": _query_link(sort="oldest"),
		"sort_popular_qs": _query_link(sort="popular"),
		"toggle_mine_qs": _query_link(mine=None if mine_only else "1"),
		"show_all_qs": _query_link(show="all"),
		"collapse_qs": _query_link(show=None),
		"feed_posts": feed_posts,
		"all_posts": all_posts,
		"tech_posts": [post for post in all_posts if post.category == Post.CATEGORY_TECH][:3],
		"board_posts": [post for post in all_posts if post.category == Post.CATEGORY_BOARD][:3],
		"life_posts": [post for post in all_posts if post.category == Post.CATEGORY_LIFE][:3],
		"secret_posts": [post for post in all_posts if post.category == Post.CATEGORY_SECRET][:3],
	}
	context.update(_sidebar_context(request))
	return render(request, "blog/index.html", context)


def tech(request):
	return render(request, "blog/tech.html", _category_page(request, Post.CATEGORY_TECH, "Tech"))


def board(request):
	return render(request, "blog/board.html", _category_page(request, Post.CATEGORY_BOARD, "Board"))


def life(request):
	return render(request, "blog/life.html", _category_page(request, Post.CATEGORY_LIFE, "Life"))


def secret(request):
	return render(request, "blog/secret.html", _category_page(request, Post.CATEGORY_SECRET, "Secret"))


@login_required
def post_create(request):
	if request.method == "POST":
		title = (request.POST.get("title") or "").strip()
		category = (request.POST.get("category") or "").strip()
		summary = (request.POST.get("summary") or "").strip()
		content = (request.POST.get("content") or "").strip()
		tags_raw = (request.POST.get("tags") or "").strip()
		is_published = request.POST.get("is_published") == "1"

		if not title or category not in dict(Post.CATEGORY_CHOICES):
			messages.error(request, "제목과 카테고리는 필수입니다.")
			return render(request, "blog/write.html", {
				"categories": Post.CATEGORY_CHOICES,
				"form_data": request.POST,
			})

		# slug 생성 (중복 시 숫자 suffix)
		base_slug = slugify(title, allow_unicode=True)
		if not base_slug:
			base_slug = "post"
		slug = base_slug
		counter = 1
		while Post.objects.filter(slug=slug).exists():
			slug = f"{base_slug}-{counter}"
			counter += 1

		post = Post.objects.create(
			title=title,
			category=category,
			slug=slug,
			summary=summary[:240] if summary else "",
			content=content,
			author=request.user,
			is_published=is_published,
			published_at=timezone.now() if is_published else None,
		)

		# 태그 처리 (쉼표 구분)
		if tags_raw:
			for tag_name in [t.strip() for t in tags_raw.split(",") if t.strip()]:
				tag_slug = slugify(tag_name, allow_unicode=True) or tag_name[:60]
				tag, _ = Tag.objects.get_or_create(
					slug=tag_slug,
					defaults={"name": tag_name[:40]},
				)
				post.tags.add(tag)

		messages.success(request, f'"{post.title}" 글이 등록되었습니다.')
		return redirect("blog:index")

	return render(request, "blog/write.html", {
		"categories": Post.CATEGORY_CHOICES,
		"form_data": {},
	})
