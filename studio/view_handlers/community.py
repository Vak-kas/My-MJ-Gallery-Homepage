from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import QueryDict
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.dateparse import parse_date

from blog.models import Comment, GuestbookEntry, Post

from .common import admin_view

# 탭별 모델과 검색 대상 필드
TABS = {
    "guestbook": {"model": GuestbookEntry, "text": "message", "label": "방명록"},
    "comments": {"model": Comment, "text": "content", "label": "댓글"},
}
FILTER_KEYS = {"q", "author", "visible", "created_from", "created_to"}


def _date(raw):
    try:
        return parse_date((raw or "").strip()) if raw else None
    except ValueError:
        return None


def _filtered_items(tab, params):
    conf = TABS[tab]
    qs = conf["model"].objects.select_related("author")
    if tab == "comments":
        qs = qs.select_related("post")

    keyword = (params.get("q") or "").strip()
    author = (params.get("author") or "").strip()
    visible = (params.get("visible") or "").strip()
    created_from = _date(params.get("created_from"))
    created_to = _date(params.get("created_to"))

    if keyword:
        qs = qs.filter(**{f"{conf['text']}__icontains": keyword})
    if author:
        qs = qs.filter(Q(author_name__icontains=author) | Q(author__username__icontains=author))
    if visible == "shown":
        qs = qs.filter(is_visible=True)
    elif visible == "hidden":
        qs = qs.filter(is_visible=False)
    if created_from:
        qs = qs.filter(created_at__date__gte=created_from)
    if created_to:
        qs = qs.filter(created_at__date__lte=created_to)

    filters = {
        "q": keyword, "author": author, "visible": visible,
        "created_from": params.get("created_from") or "", "created_to": params.get("created_to") or "",
    }
    return qs.order_by("-created_at", "-id"), filters


def _purge_targets(keyword, fields):
    """키워드 일괄 정리 대상. fields: post_title, post_content, comments, guestbook"""
    targets = {}
    if not keyword:
        return targets
    if "post_title" in fields or "post_content" in fields:
        cond = Q()
        if "post_title" in fields:
            cond |= Q(title__icontains=keyword)
        if "post_content" in fields:
            cond |= Q(content__icontains=keyword) | Q(summary__icontains=keyword)
        targets["posts"] = Post.objects.filter(cond)
    if "comments" in fields:
        targets["comments"] = Comment.objects.filter(Q(content__icontains=keyword) | Q(author_name__icontains=keyword))
    if "guestbook" in fields:
        targets["guestbook"] = GuestbookEntry.objects.filter(Q(message__icontains=keyword) | Q(author_name__icontains=keyword))
    return targets


PURGE_FIELDS = [
    ("post_title", "글 제목"),
    ("post_content", "글 본문·요약"),
    ("comments", "댓글 (내용·작성자 이름)"),
    ("guestbook", "방명록 (내용·작성자 이름)"),
]
DEFAULT_PURGE_FIELDS = ["post_title", "comments", "guestbook"]


@admin_view
def community(request):
    tab = (request.GET.get("tab") or "guestbook").strip()
    if tab not in TABS and tab != "cleanup":
        tab = "guestbook"
    base = reverse("studio:community")

    if request.method == "POST":
        return _handle_post(request, base)

    context = {"tab": tab, "tabs": [(k, v["label"]) for k, v in TABS.items()],
               "counts": {
                   "guestbook": GuestbookEntry.objects.count(),
                   "comments": Comment.objects.count(),
               }}

    if tab == "cleanup":
        keyword = (request.GET.get("keyword") or "").strip()
        fields = request.GET.getlist("fields") or DEFAULT_PURGE_FIELDS
        targets = _purge_targets(keyword, fields)
        preview = []
        for key, qs in targets.items():
            label = {"posts": "글", "comments": "댓글", "guestbook": "방명록"}[key]
            sample = list(qs.order_by("-created_at")[:20])
            preview.append({"key": key, "label": label, "count": qs.count(), "sample": sample})
        context.update({
            "keyword": keyword, "fields": fields, "purge_fields": PURGE_FIELDS, "preview": preview,
            "preview_total": sum(p["count"] for p in preview),
            "current_query_string": request.GET.urlencode(),
        })
        return render(request, "studio/community.html", context)

    qs, filters = _filtered_items(tab, request.GET)
    paginator = Paginator(qs, 30)
    page_obj = paginator.get_page(request.GET.get("page"))
    query = request.GET.copy()
    query.pop("page", None)
    context.update({
        "filters": filters, "items": list(page_obj.object_list), "page_obj": page_obj,
        "item_count": paginator.count, "current_query_string": query.urlencode(),
        "has_filter": any(filters.values()),
    })
    return render(request, "studio/community.html", context)


def _handle_post(request, base):
    return_qs = (request.POST.get("return_qs") or "").strip()
    back = redirect(f"{base}?{return_qs}") if return_qs else redirect(base)
    params = QueryDict(return_qs)
    action = (request.POST.get("action") or "").strip()
    confirm_text = (request.POST.get("confirm") or "").strip()

    if action == "purge":
        keyword = (params.get("keyword") or "").strip()
        if len(keyword) < 2:
            messages.error(request, "키워드는 2글자 이상이어야 합니다.")
            return back
        if confirm_text != "DELETE":
            messages.error(request, "일괄 삭제는 확인 문구(DELETE) 입력이 필요합니다.")
            return back
        targets = _purge_targets(keyword, params.getlist("fields") or DEFAULT_PURGE_FIELDS)
        done = []
        for key, qs in targets.items():
            label = {"posts": "글", "comments": "댓글", "guestbook": "방명록"}[key]
            n = qs.count()
            qs.delete()
            done.append(f"{label} {n}개")
        messages.success(request, f'"{keyword}" 포함 항목 삭제: ' + (", ".join(done) or "없음"))
        return back

    tab = (params.get("tab") or "guestbook").strip()
    if tab not in TABS:
        messages.error(request, "대상이 올바르지 않습니다.")
        return back
    model = TABS[tab]["model"]
    if request.POST.get("scope") == "filtered":
        filtered, filters = _filtered_items(tab, params)
        if not any(filters.values()):
            messages.error(request, "필터 결과 전체에 적용하려면 검색 조건을 먼저 걸어 주세요.")
            return back
        target = model.objects.filter(id__in=filtered.values("id"))
    else:
        ids = [int(v) for v in request.POST.getlist("ids") if v.isdigit()]
        target = model.objects.filter(id__in=ids)
    count = target.count()
    if count == 0:
        messages.error(request, "선택된 항목이 없습니다.")
        return back

    label = TABS[tab]["label"]
    if action == "hide":
        target.update(is_visible=False)
        messages.success(request, f"{label} {count}개를 숨겼습니다.")
    elif action == "show":
        target.update(is_visible=True)
        messages.success(request, f"{label} {count}개를 다시 보이게 했습니다.")
    elif action == "delete":
        if confirm_text != "DELETE":
            messages.error(request, "일괄 삭제는 확인 문구(DELETE) 입력이 필요합니다.")
            return back
        target.delete()
        messages.success(request, f"{label} {count}개를 삭제했습니다.")
    else:
        messages.error(request, "작업 종류가 올바르지 않습니다.")
    return back
