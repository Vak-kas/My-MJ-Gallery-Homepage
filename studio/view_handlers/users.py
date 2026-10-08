from django.contrib import messages
from django.contrib.auth import get_user_model
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.shortcuts import redirect, render
from django.urls import reverse

from blog.models import Comment, GuestbookEntry, Post

from .common import admin_view

STATES = [
    ("", "전체"),
    ("active", "활성"),
    ("inactive", "정지·승인 대기"),
    ("admin", "관리자"),
]


def _purge_user_content(user):
    counts = {
        "posts": Post.objects.filter(author=user).count(),
        "comments": Comment.objects.filter(author=user).count(),
        "guestbook": GuestbookEntry.objects.filter(author=user).count(),
    }
    Post.objects.filter(author=user).delete()
    Comment.objects.filter(author=user).delete()
    GuestbookEntry.objects.filter(author=user).delete()
    return counts


@admin_view
def users(request):
    User = get_user_model()
    base = reverse("studio:users")

    if request.method == "POST":
        return_qs = (request.POST.get("return_qs") or "").strip()
        back = redirect(f"{base}?{return_qs}") if return_qs else redirect(base)
        action = (request.POST.get("action") or "").strip()
        ids = [int(v) for v in request.POST.getlist("ids") if v.isdigit()]
        # 나 자신과 관리자 계정은 일괄 작업 대상에서 제외
        targets = User.objects.filter(id__in=ids, is_superuser=False).exclude(id=request.user.id)
        skipped = len(ids) - targets.count()
        if not targets.exists():
            messages.error(request, "적용할 수 있는 회원이 없습니다. (본인·관리자 계정은 제외됩니다)")
            return back

        names = ", ".join(targets.values_list("username", flat=True)[:5])
        count = targets.count()
        if action == "activate":
            targets.update(is_active=True)
            messages.success(request, f"{count}명 활성화(승인): {names}")
        elif action == "suspend":
            targets.update(is_active=False)
            messages.success(request, f"{count}명 정지: {names}")
        elif action in {"purge", "delete"}:
            if (request.POST.get("confirm") or "").strip() != "DELETE":
                messages.error(request, "삭제 작업은 확인 문구(DELETE) 입력이 필요합니다.")
                return back
            total = {"posts": 0, "comments": 0, "guestbook": 0}
            for user in targets:
                for key, n in _purge_user_content(user).items():
                    total[key] += n
            summary = f"글 {total['posts']}개, 댓글 {total['comments']}개, 방명록 {total['guestbook']}개 삭제"
            if action == "purge":
                targets.update(is_active=False)
                messages.success(request, f"{count}명 정지 + 작성한 {summary}: {names}")
            else:
                targets.delete()
                messages.success(request, f"{count}명 계정 삭제 + {summary}: {names}")
        else:
            messages.error(request, "작업 종류가 올바르지 않습니다.")
            return back
        if skipped:
            messages.info(request, f"본인·관리자 계정 {skipped}개는 건너뛰었습니다.")
        return back

    keyword = (request.GET.get("q") or "").strip()
    state = (request.GET.get("state") or "").strip()
    qs = User.objects.annotate(
        post_count=Count("blog_posts", distinct=True),
        comment_count=Count("blog_comments", distinct=True),
        guestbook_count=Count("guestbook_entries", distinct=True),
    )
    if keyword:
        qs = qs.filter(
            Q(username__icontains=keyword) | Q(email__icontains=keyword)
            | Q(first_name__icontains=keyword) | Q(last_name__icontains=keyword)
        )
    state_counts = {
        "": User.objects.count(),
        "active": User.objects.filter(is_active=True).count(),
        "inactive": User.objects.filter(is_active=False).count(),
        "admin": User.objects.filter(is_superuser=True).count(),
    }
    if state == "active":
        qs = qs.filter(is_active=True)
    elif state == "inactive":
        qs = qs.filter(is_active=False)
    elif state == "admin":
        qs = qs.filter(is_superuser=True)
    else:
        state = ""

    # 정지·승인 대기를 먼저, 그다음 최근 가입순
    paginator = Paginator(qs.order_by("is_active", "-date_joined", "-id"), 30)
    page_obj = paginator.get_page(request.GET.get("page"))
    query = request.GET.copy()
    query.pop("page", None)
    return render(request, "studio/users.html", {
        "users": list(page_obj.object_list),
        "page_obj": page_obj,
        "user_count": paginator.count,
        "keyword": keyword,
        "state": state,
        "states": [(k, label, state_counts[k]) for k, label in STATES],
        "current_query_string": query.urlencode(),
    })
