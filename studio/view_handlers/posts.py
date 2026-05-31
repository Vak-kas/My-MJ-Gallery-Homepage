from django.contrib import messages
from django.contrib.auth import get_user_model
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date
from urllib.parse import urlencode

from blog.models import Post

from .common import admin_view


@admin_view
def posts(request):
    keyword = (request.GET.get("q") or "").strip()
    author_id = (request.GET.get("author") or "").strip()
    created_from = (request.GET.get("created_from") or "").strip()
    created_to = (request.GET.get("created_to") or "").strip()
    sort_key = (request.GET.get("sort") or "updated_desc").strip()
    per_page_raw = (request.GET.get("per_page") or "20").strip()

    sort_map = {
        "updated_desc": ("-updated_at", "-id"),
        "created_desc": ("-created_at", "-id"),
        "views_desc": ("-views", "-id"),
        "title_asc": ("title", "id"),
    }
    if sort_key not in sort_map:
        sort_key = "updated_desc"

    per_page = int(per_page_raw) if per_page_raw.isdigit() else 20
    if per_page not in {20, 50, 100}:
        per_page = 20

    User = get_user_model()
    author_choices = User.objects.filter(is_active=True).order_by("username")

    post_qs = Post.objects.select_related("author").prefetch_related("tags")

    if keyword:
        post_qs = post_qs.filter(
            Q(title__icontains=keyword)
            | Q(summary__icontains=keyword)
            | Q(content__icontains=keyword)
            | Q(author__username__icontains=keyword)
        ).distinct()

    if author_id.isdigit():
        post_qs = post_qs.filter(author_id=int(author_id))

    created_from_date = parse_date(created_from) if created_from else None
    created_to_date = parse_date(created_to) if created_to else None
    if created_from and created_from_date:
        post_qs = post_qs.filter(created_at__date__gte=created_from_date)
    if created_to and created_to_date:
        post_qs = post_qs.filter(created_at__date__lte=created_to_date)

    post_qs = post_qs.order_by(*sort_map[sort_key])

    def _redirect_with_qs(qs: str):
        base = reverse("studio:posts")
        return redirect(f"{base}?{qs}") if qs else redirect("studio:posts")

    if request.method == "POST":
        action = (request.POST.get("bulk_action") or "").strip()
        return_qs = (request.POST.get("return_qs") or "").strip()
        selected_ids = [int(v) for v in request.POST.getlist("selected_ids") if v.isdigit()]
        selected_qs = Post.objects.filter(id__in=selected_ids)
        selected_count = selected_qs.count()

        if selected_count == 0:
            messages.error(request, "선택된 글이 없습니다.")
            return _redirect_with_qs(return_qs)

        if action == "delete":
            confirm_text = (request.POST.get("bulk_delete_confirm") or "").strip()
            if confirm_text != "DELETE":
                messages.error(request, "일괄 삭제는 확인 문구(DELETE) 입력이 필요합니다.")
                return _redirect_with_qs(return_qs)

            selected_qs.delete()
            messages.success(request, f"{selected_count}개 글을 삭제했습니다.")
            return _redirect_with_qs(return_qs)

        if action == "set_private":
            selected_qs.update(visibility=Post.VISIBILITY_PRIVATE, access_password="")
            messages.success(request, f"{selected_count}개 글을 비공개로 변경했습니다.")
            return _redirect_with_qs(return_qs)

        if action == "set_public":
            selected_qs.update(visibility=Post.VISIBILITY_PUBLIC, access_password="")
            messages.success(request, f"{selected_count}개 글을 전체공개로 변경했습니다.")
            return _redirect_with_qs(return_qs)

        if action == "set_protected":
            raw_password = (request.POST.get("bulk_access_password") or "").strip()
            if not raw_password:
                messages.error(request, "일부공개로 바꾸려면 비밀번호를 입력해 주세요.")
                return _redirect_with_qs(return_qs)

            updated = 0
            for post in selected_qs:
                post.visibility = Post.VISIBILITY_PROTECTED
                post.set_access_password(raw_password)
                post.save(update_fields=["visibility", "access_password", "updated_at"])
                updated += 1

            messages.success(request, f"{updated}개 글을 일부공개(비밀번호)로 변경했습니다.")
            return _redirect_with_qs(return_qs)

        if action == "publish":
            now = timezone.now()
            for post in selected_qs:
                post.is_published = True
                if not post.published_at:
                    post.published_at = now
                post.save(update_fields=["is_published", "published_at", "updated_at"])
            messages.success(request, f"{selected_count}개 글을 발행 상태로 변경했습니다.")
            return _redirect_with_qs(return_qs)

        if action == "unpublish":
            selected_qs.update(is_published=False, published_at=None)
            messages.success(request, f"{selected_count}개 글을 비발행 상태로 변경했습니다.")
            return _redirect_with_qs(return_qs)

        messages.error(request, "일괄 작업 종류가 올바르지 않습니다.")
        return _redirect_with_qs(return_qs)

    paginator = Paginator(post_qs, per_page)
    page_obj = paginator.get_page(request.GET.get("page"))
    posts_list = list(page_obj.object_list)

    current_query = request.GET.copy()
    current_query.pop("page", None)
    current_query_string = current_query.urlencode()

    pagination_base_qs = current_query.copy()
    pagination_base_qs.pop("page", None)
    pagination_base_qs = pagination_base_qs.urlencode()

    return render(
        request,
        "studio/posts.html",
        {
            "posts": posts_list,
            "post_count": paginator.count,
            "page_obj": page_obj,
            "current_query_string": current_query_string,
            "pagination_base_qs": pagination_base_qs,
            "search_query": keyword,
            "selected_author": author_id,
            "created_from": created_from,
            "created_to": created_to,
            "selected_sort": sort_key,
            "selected_per_page": per_page,
            "sort_choices": [
                ("updated_desc", "최신 수정순"),
                ("created_desc", "최신 작성순"),
                ("views_desc", "조회수순"),
                ("title_asc", "제목 오름차순"),
            ],
            "per_page_choices": [20, 50, 100],
            "author_choices": author_choices,
            "visibility_choices": Post.VISIBILITY_CHOICES,
            "visibility_public": Post.VISIBILITY_PUBLIC,
            "visibility_private": Post.VISIBILITY_PRIVATE,
            "visibility_protected": Post.VISIBILITY_PROTECTED,
        },
    )


@admin_view
def post_visibility_update(request, id):
    post = get_object_or_404(Post, id=id)

    if request.method != "POST":
        return redirect("studio:posts")

    is_published = request.POST.get("is_published") == "true"
    visibility = (request.POST.get("visibility") or Post.VISIBILITY_PUBLIC).strip()
    raw_password = (request.POST.get("access_password") or "").strip()

    valid_visibility = {choice[0] for choice in Post.VISIBILITY_CHOICES}
    if visibility not in valid_visibility:
        messages.error(request, "공개 범위 값이 올바르지 않습니다.")
        return redirect("studio:posts")

    if visibility == Post.VISIBILITY_PROTECTED:
        if raw_password:
            post.set_access_password(raw_password)
        elif not post.access_password:
            messages.error(request, f'"{post.title}" 글의 일부공개 비밀번호를 입력해 주세요.')
            return redirect("studio:posts")
    else:
        post.access_password = ""

    post.is_published = is_published
    post.visibility = visibility

    if not is_published:
        post.published_at = None
    elif not post.published_at:
        post.published_at = timezone.now()

    post.save()
    messages.success(request, f'"{post.title}" 글 공개 설정이 저장되었습니다.')
    return_qs = (request.POST.get("return_qs") or "").strip()
    base = reverse("studio:posts")
    return redirect(f"{base}?{return_qs}") if return_qs else redirect("studio:posts")


@admin_view
def post_delete(request, id):
    post = get_object_or_404(Post, id=id)

    if request.method != "POST":
        return redirect("studio:posts")

    title = post.title
    post.delete()
    messages.success(request, f'"{title}" 글을 삭제했습니다.')
    return_qs = (request.POST.get("return_qs") or "").strip()
    base = reverse("studio:posts")
    return redirect(f"{base}?{return_qs}") if return_qs else redirect("studio:posts")
