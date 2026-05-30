from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify
from urllib.parse import urlencode

from .models import Comment, GuestbookEntry, Post, PostLike, Tag


def _published_posts_qs():
	return Post.objects.filter(is_published=True).prefetch_related("tags")


def _accessible_posts_qs(request):
	qs = _published_posts_qs()
	if request.user.is_superuser:
		return qs
	return qs.exclude(category=Post.CATEGORY_SECRET)


def _single_post_qs(request):
	qs = Post.objects.select_related("author").prefetch_related("tags", "comments")
	if request.user.is_superuser:
		return qs
	return qs.filter(is_published=True).exclude(category=Post.CATEGORY_SECRET)


def _can_manage_post(request, post: Post) -> bool:
	return request.user.is_authenticated and (
		request.user.is_superuser or post.author_id == request.user.id
	)


def _serialize_post_form_data(post: Post):
	return {
		"draft_id": str(post.id),
		"title": post.title,
		"category": post.category,
		"summary": post.summary,
		"content": post.content,
		"cover_image": post.cover_image.url if post.cover_image else "",
		"tags": ", ".join(tag.name for tag in post.tags.all()),
		"is_published": "1" if post.is_published else "0",
	}


def _apply_post_tags(post: Post, tags_raw: str):
	post.tags.clear()
	if tags_raw:
		for tag_name in [t.strip() for t in tags_raw.split(",") if t.strip()]:
			tag_slug = slugify(tag_name, allow_unicode=True) or tag_name[:60]
			tag, _ = Tag.objects.get_or_create(
				slug=tag_slug,
				defaults={"name": tag_name[:40]},
			)
			post.tags.add(tag)


def _write_page_context(request, form_data=None, selected_draft=None, editing_post=None):
	draft_posts_qs = Post.objects.filter(author=request.user, is_published=False)
	if editing_post:
		draft_posts_qs = draft_posts_qs.exclude(id=editing_post.id)

	return {
		"categories": Post.CATEGORY_CHOICES,
		"form_data": form_data or {},
		"draft_posts": list(draft_posts_qs.order_by("-updated_at", "-id")[:20]),
		"selected_draft": selected_draft,
		"editor_mode": "edit" if editing_post else "create",
		"form_action_url": reverse("blog:post_edit", args=[editing_post.slug]) if editing_post else reverse("blog:post_create"),
		"editor_heading": "글 수정" if editing_post else "새 글 작성",
		"editor_submit_label": "수정 완료" if editing_post else "완료",
		"editing_post": editing_post,
	}


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


def post_detail(request, slug: str):
	post = get_object_or_404(_single_post_qs(request), slug=slug)
	if not post.is_published and not request.user.is_superuser:
		raise Http404("Not found")

	if request.method == "POST":
		action = (request.POST.get("action") or "").strip()

		if action == "comment":
			author_name = (request.POST.get("author_name") or "").strip()
			content = (request.POST.get("content") or "").strip()
			if not author_name and request.user.is_authenticated:
				author_name = request.user.get_username()
			if author_name and content:
				Comment.objects.create(post=post, author_name=author_name[:60], content=content[:1200])
				messages.success(request, "댓글이 등록되었습니다.")
			else:
				messages.error(request, "이름과 댓글 내용을 모두 입력해 주세요.")
			return redirect("blog:post_detail", slug=post.slug)

		if action == "like":
			if not request.user.is_authenticated:
				messages.error(request, "좋아요는 로그인 후 사용할 수 있습니다.")
				return redirect("accounts:login")

			like, created = PostLike.objects.get_or_create(post=post, user=request.user)
			if not created:
				like.delete()
				messages.success(request, "좋아요를 취소했습니다.")
			else:
				messages.success(request, "좋아요를 눌렀습니다.")
			return redirect("blog:post_detail", slug=post.slug)

	Post.objects.filter(id=post.id).update(views=post.views + 1)
	post.views += 1

	visible_comments = post.comments.filter(is_visible=True).select_related(None)
	likes_count = post.likes.count()
	user_liked = request.user.is_authenticated and post.likes.filter(user=request.user).exists()

	context = {
		"post": post,
		"visible_comments": visible_comments,
		"comment_count": visible_comments.count(),
		"likes_count": likes_count,
		"user_liked": user_liked,
		"can_manage_post": _can_manage_post(request, post),
		"comment_form_author": request.user.get_username() if request.user.is_authenticated else "",
	}
	context.update(_sidebar_context(request))
	return render(request, "blog/post_detail.html", context)


def _build_unique_slug(title: str, exclude_post_id=None):
	base_slug = slugify(title, allow_unicode=True) or "post"
	slug = base_slug
	counter = 1
	qs = Post.objects.all()
	if exclude_post_id:
		qs = qs.exclude(id=exclude_post_id)
	while qs.filter(slug=slug).exists():
		slug = f"{base_slug}-{counter}"
		counter += 1
	return slug


@login_required
def post_create(request):
	draft_id_param = (request.GET.get("draft") or "").strip()
	selected_draft = None
	if draft_id_param.isdigit():
		selected_draft = Post.objects.filter(
			id=int(draft_id_param),
			author=request.user,
			is_published=False,
		).prefetch_related("tags").first()

	draft_posts = list(
		Post.objects.filter(author=request.user, is_published=False)
		.order_by("-updated_at", "-id")[:20]
	)

	if request.method == "POST":
		draft_id = (request.POST.get("draft_id") or "").strip()
		existing_draft = None
		if draft_id.isdigit():
			existing_draft = Post.objects.filter(
				id=int(draft_id),
				author=request.user,
				is_published=False,
			).first()

		title = (request.POST.get("title") or "").strip()
		category = (request.POST.get("category") or "").strip()
		summary = (request.POST.get("summary") or "").strip()
		content = (request.POST.get("content") or "").strip()
		cover_image = request.FILES.get("cover_image")
		tags_raw = (request.POST.get("tags") or "").strip()
		submit_action = (request.POST.get("submit_action") or "publish").strip()
		is_published = submit_action != "draft" and request.POST.get("is_published") == "1"

		if not title or category not in dict(Post.CATEGORY_CHOICES):
			messages.error(request, "제목과 카테고리는 필수입니다.")
			form_data = dict(request.POST)
			form_data = {key: value[-1] if isinstance(value, list) else value for key, value in form_data.items()}
			return render(request, "blog/write.html", _write_page_context(request, form_data, selected_draft=selected_draft))

		if category == Post.CATEGORY_SECRET and not request.user.is_superuser:
			messages.error(request, "Secret 카테고리는 관리자만 작성할 수 있습니다.")
			form_data = dict(request.POST)
			form_data = {key: value[-1] if isinstance(value, list) else value for key, value in form_data.items()}
			return render(request, "blog/write.html", _write_page_context(request, form_data, selected_draft=selected_draft))

		if existing_draft:
			post = existing_draft
			post.title = title
			post.category = category
			if cover_image:
				post.cover_image = cover_image
			if post.slug:
				post.slug = _build_unique_slug(title, exclude_post_id=post.id)
			else:
				post.slug = _build_unique_slug(title, exclude_post_id=post.id)
			post.summary = summary[:240] if summary else ""
			post.content = content
			post.is_published = is_published
			if is_published and not post.published_at:
				post.published_at = timezone.now()
			if not is_published:
				post.published_at = None
			post.save()
		else:
			post = Post.objects.create(
				title=title,
				category=category,
				cover_image=cover_image,
				slug=_build_unique_slug(title),
				summary=summary[:240] if summary else "",
				content=content,
				author=request.user,
				is_published=is_published,
				published_at=timezone.now() if is_published else None,
			)

		_apply_post_tags(post, tags_raw)

		if submit_action == "draft" or not is_published:
			messages.success(request, f'"{post.title}" 글이 임시저장되었습니다.')
			return redirect(f"{reverse('blog:post_create')}?draft={post.id}")
		else:
			messages.success(request, f'"{post.title}" 글이 등록되었습니다.')
		return redirect("blog:index")

	if selected_draft:
		form_data = {
			"draft_id": str(selected_draft.id),
			"title": selected_draft.title,
			"category": selected_draft.category,
			"summary": selected_draft.summary,
			"content": selected_draft.content,
			"cover_image": selected_draft.cover_image.url if selected_draft.cover_image else "",
			"tags": ", ".join(tag.name for tag in selected_draft.tags.all()),
			"is_published": "0",
		}
	else:
		form_data = {}

	return render(request, "blog/write.html", _write_page_context(request, form_data, selected_draft=selected_draft))


@login_required
def post_edit(request, slug: str):
	post = get_object_or_404(Post.objects.prefetch_related("tags"), slug=slug)
	if not _can_manage_post(request, post):
		raise Http404("Not found")

	if request.method == "POST":
		title = (request.POST.get("title") or "").strip()
		category = (request.POST.get("category") or "").strip()
		summary = (request.POST.get("summary") or "").strip()
		content = (request.POST.get("content") or "").strip()
		cover_image = request.FILES.get("cover_image")
		tags_raw = (request.POST.get("tags") or "").strip()
		submit_action = (request.POST.get("submit_action") or "publish").strip()
		is_published = submit_action != "draft" and request.POST.get("is_published") == "1"

		form_data = dict(request.POST)
		form_data = {key: value[-1] if isinstance(value, list) else value for key, value in form_data.items()}
		form_data["cover_image"] = post.cover_image.url if post.cover_image else ""

		if not title or category not in dict(Post.CATEGORY_CHOICES):
			messages.error(request, "제목과 카테고리는 필수입니다.")
			return render(request, "blog/write.html", _write_page_context(request, form_data, editing_post=post))

		if category == Post.CATEGORY_SECRET and not request.user.is_superuser:
			messages.error(request, "Secret 카테고리는 관리자만 작성할 수 있습니다.")
			return render(request, "blog/write.html", _write_page_context(request, form_data, editing_post=post))

		post.title = title
		post.category = category
		post.summary = summary[:240] if summary else ""
		post.content = content
		post.slug = _build_unique_slug(title, exclude_post_id=post.id)
		post.is_published = is_published
		if cover_image:
			post.cover_image = cover_image
		if is_published and not post.published_at:
			post.published_at = timezone.now()
		if not is_published:
			post.published_at = None
		post.save()
		_apply_post_tags(post, tags_raw)

		if submit_action == "draft" or not is_published:
			messages.success(request, f'"{post.title}" 글이 임시저장되었습니다.')
			return redirect("blog:post_edit", slug=post.slug)

		messages.success(request, f'"{post.title}" 글이 수정되었습니다.')
		return redirect("blog:post_detail", slug=post.slug)

	return render(request, "blog/write.html", _write_page_context(request, _serialize_post_form_data(post), editing_post=post))


@login_required
def post_delete(request, slug: str):
	post = get_object_or_404(Post.objects.all(), slug=slug)
	if not _can_manage_post(request, post):
		raise Http404("Not found")
	if request.method != "POST":
		return redirect("blog:post_detail", slug=post.slug)

	title = post.title
	post.delete()
	messages.success(request, f'"{title}" 글이 삭제되었습니다.')
	return redirect("blog:index")
