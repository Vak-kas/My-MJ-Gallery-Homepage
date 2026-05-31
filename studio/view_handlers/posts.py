from django.contrib import messages
from django.contrib.auth import get_user_model
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_date

from blog.models import Post

from .common import admin_view


@admin_view
def posts(request):
    keyword = (request.GET.get("q") or "").strip()
    author_id = (request.GET.get("author") or "").strip()
    created_from = (request.GET.get("created_from") or "").strip()
    created_to = (request.GET.get("created_to") or "").strip()

    User = get_user_model()
    author_choices = User.objects.filter(is_active=True).order_by("username")

    post_qs = Post.objects.select_related("author").prefetch_related("tags").order_by("-updated_at", "-id")

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

    if request.method == "POST":
        action = (request.POST.get("bulk_action") or "").strip()
        selected_ids = [int(v) for v in request.POST.getlist("selected_ids") if v.isdigit()]
        selected_qs = Post.objects.filter(id__in=selected_ids)
        selected_count = selected_qs.count()

        if selected_count == 0:
            messages.error(request, "선택된 글이 없습니다.")
            return redirect("studio:posts")

        if action == "delete":
            selected_qs.delete()
            messages.success(request, f"{selected_count}개 글을 삭제했습니다.")
            return redirect("studio:posts")

        if action == "set_private":
            selected_qs.update(visibility=Post.VISIBILITY_PRIVATE, access_password="")
            messages.success(request, f"{selected_count}개 글을 비공개로 변경했습니다.")
            return redirect("studio:posts")

        if action == "set_public":
            selected_qs.update(visibility=Post.VISIBILITY_PUBLIC, access_password="")
            messages.success(request, f"{selected_count}개 글을 전체공개로 변경했습니다.")
            return redirect("studio:posts")

        if action == "set_protected":
            raw_password = (request.POST.get("bulk_access_password") or "").strip()
            if not raw_password:
                messages.error(request, "일부공개로 바꾸려면 비밀번호를 입력해 주세요.")
                return redirect("studio:posts")

            updated = 0
            for post in selected_qs:
                post.visibility = Post.VISIBILITY_PROTECTED
                post.set_access_password(raw_password)
                post.save(update_fields=["visibility", "access_password", "updated_at"])
                updated += 1

            messages.success(request, f"{updated}개 글을 일부공개(비밀번호)로 변경했습니다.")
            return redirect("studio:posts")

        if action == "publish":
            now = timezone.now()
            for post in selected_qs:
                post.is_published = True
                if not post.published_at:
                    post.published_at = now
                post.save(update_fields=["is_published", "published_at", "updated_at"])
            messages.success(request, f"{selected_count}개 글을 발행 상태로 변경했습니다.")
            return redirect("studio:posts")

        if action == "unpublish":
            selected_qs.update(is_published=False, published_at=None)
            messages.success(request, f"{selected_count}개 글을 비발행 상태로 변경했습니다.")
            return redirect("studio:posts")

        messages.error(request, "일괄 작업 종류가 올바르지 않습니다.")
        return redirect("studio:posts")

    posts_list = list(post_qs[:300])

    return render(
        request,
        "studio/posts.html",
        {
            "posts": posts_list,
            "post_count": len(posts_list),
            "search_query": keyword,
            "selected_author": author_id,
            "created_from": created_from,
            "created_to": created_to,
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
    return redirect("studio:posts")


@admin_view
def post_delete(request, id):
    post = get_object_or_404(Post, id=id)

    if request.method != "POST":
        return redirect("studio:posts")

    title = post.title
    post.delete()
    messages.success(request, f'"{title}" 글을 삭제했습니다.')
    return redirect("studio:posts")
