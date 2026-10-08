import csv
import ipaddress
from datetime import timedelta

from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone

from blog.models import Comment, GuestbookEntry, Post
from security.models import IPBlock, LoginEvent
from security.utils import RETENTION_DAYS, cleanup_old_records, clear_block_cache, client_ip

from .common import admin_view

TABS = [("overview", "개요"), ("logins", "로그인 기록"), ("content", "작성 기록"), ("blocks", "IP 차단")]
DURATIONS = [("1h", "1시간", timedelta(hours=1)), ("1d", "1일", timedelta(days=1)), ("7d", "7일", timedelta(days=7)),
             ("30d", "30일", timedelta(days=30)), ("", "무기한", None)]
MIN_PREFIX = {4: 16, 6: 32}  # 너무 넓은 대역을 실수로 막지 않게


def _content_rows(params, limit=300):
    """글·댓글·방명록을 IP 와 함께 한 목록으로."""
    ip = (params.get("ip") or "").strip()
    who = (params.get("who") or "").strip()
    kind = (params.get("kind") or "").strip()
    sources = [
        ("comment", "댓글", Comment.objects.select_related("author", "post"), "content"),
        ("guestbook", "방명록", GuestbookEntry.objects.select_related("author"), "message"),
        ("post", "글", Post.objects.select_related("author"), "title"),
    ]
    rows = []
    for key, label, qs, text_field in sources:
        if kind and kind != key:
            continue
        qs = qs.exclude(author_ip=None)
        if ip:
            qs = qs.filter(author_ip__startswith=ip)
        if who:
            qs = qs.filter(author__username__icontains=who)
        for obj in qs.order_by("-created_at")[:limit]:
            rows.append({
                "kind": key, "label": label, "obj": obj, "text": getattr(obj, text_field),
                "author": obj.author.username if obj.author else getattr(obj, "author_name", ""),
                "created_at": obj.created_at, "ip": obj.author_ip, "agent": obj.author_agent,
            })
    rows.sort(key=lambda r: r["created_at"], reverse=True)
    return rows[:limit], {"ip": ip, "who": who, "kind": kind}


def _export_csv(rows):
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="evidence-{timezone.localtime():%Y%m%d-%H%M}.csv"'
    response.write("﻿")  # 엑셀에서 한글 깨짐 방지
    writer = csv.writer(response)
    writer.writerow(["작성 시각", "종류", "작성자", "내용", "IP", "브라우저"])
    for r in rows:
        writer.writerow([timezone.localtime(r["created_at"]).strftime("%Y-%m-%d %H:%M:%S"), r["label"], r["author"], r["text"], r["ip"], r["agent"]])
    return response


def _add_block(request, raw, reason, duration_key):
    raw = (raw or "").strip()
    try:
        net = ipaddress.ip_network(raw, strict=False)
    except ValueError:
        messages.error(request, "IP 또는 대역(CIDR) 형식이 올바르지 않아요. 예: 1.2.3.4 또는 1.2.3.0/24")
        return
    if net.prefixlen < MIN_PREFIX[net.version]:
        messages.error(request, f"너무 넓은 대역이에요. IPv4 는 /{MIN_PREFIX[4]} 이상, IPv6 는 /{MIN_PREFIX[6]} 이상만 막을 수 있어요.")
        return
    mine = client_ip(request)
    if mine and ipaddress.ip_address(mine) in net:
        messages.error(request, f"지금 접속 중인 내 IP({mine})가 포함돼 있어 막을 수 없어요.")
        return
    delta = next((d for k, _, d in DURATIONS if k == duration_key), None)
    IPBlock.objects.create(
        network=str(net) if net.num_addresses > 1 else str(net.network_address),
        reason=(reason or "").strip()[:200], created_by=request.user,
        expires_at=timezone.now() + delta if delta else None,
    )
    clear_block_cache()
    messages.success(request, f"{net} 을(를) 차단했어요.")


@admin_view
def security(request):
    tab = request.GET.get("tab") or "overview"
    if tab not in dict(TABS):
        tab = "overview"
    base = reverse("studio:security")

    if request.method == "POST":
        action = request.POST.get("action")
        back_qs = (request.POST.get("return_qs") or "").strip()
        back = redirect(f"{base}?{back_qs}") if back_qs else redirect(base)
        if action == "block":
            _add_block(request, request.POST.get("network"), request.POST.get("reason"), request.POST.get("duration", "7d"))
        elif action == "unblock":
            IPBlock.objects.filter(pk=request.POST.get("id")).delete()
            clear_block_cache()
            messages.success(request, "차단을 풀었어요.")
        elif action == "cleanup":
            result = cleanup_old_records()
            messages.success(request, f"정리 완료: 로그인 기록 {result['login_events']}건 삭제, 작성 IP {result['content_ip_cleared']}건 비움")
        return back

    now = timezone.now()
    day_ago = now - timedelta(days=1)
    context = {"tab": tab, "tabs": TABS, "retention_days": RETENTION_DAYS, "my_ip": client_ip(request),
               "durations": [(k, label) for k, label, _ in DURATIONS], "now": now}

    if tab == "overview":
        recent = LoginEvent.objects.filter(created_at__gte=day_ago)
        context.update({
            "stats": {
                "failed": recent.filter(result=LoginEvent.RESULT_FAILED).count(),
                "locked": recent.filter(result=LoginEvent.RESULT_LOCKED).count(),
                "success": recent.filter(result=LoginEvent.RESULT_SUCCESS).count(),
                "blocks": sum(1 for b in IPBlock.objects.all() if b.is_active),
            },
            "admin_logins": LoginEvent.objects.filter(is_admin=True, result=LoginEvent.RESULT_SUCCESS)[:10],
            "top_failed": recent.exclude(result=LoginEvent.RESULT_SUCCESS).exclude(ip=None)
                .values("ip").annotate(n=Count("id")).order_by("-n")[:10],
        })
    elif tab == "logins":
        qs = LoginEvent.objects.select_related("user")
        result = request.GET.get("result") or ""
        ip = (request.GET.get("ip") or "").strip()
        username = (request.GET.get("username") or "").strip()
        if result == "fail":
            qs = qs.exclude(result=LoginEvent.RESULT_SUCCESS)
        elif result in dict(LoginEvent.RESULT_CHOICES):
            qs = qs.filter(result=result)
        if ip:
            qs = qs.filter(ip__startswith=ip)
        if username:
            qs = qs.filter(username__icontains=username)
        page_obj = Paginator(qs, 50).get_page(request.GET.get("page"))
        query = request.GET.copy()
        query.pop("page", None)
        context.update({"page_obj": page_obj, "events": list(page_obj.object_list),
                        "filters": {"result": result, "ip": ip, "username": username},
                        "results": LoginEvent.RESULT_CHOICES, "current_query_string": query.urlencode()})
    elif tab == "content":
        rows, filters = _content_rows(request.GET)
        if request.GET.get("export") == "csv":
            return _export_csv(rows)
        query = request.GET.copy()
        context.update({"rows": rows, "filters": filters, "current_query_string": query.urlencode()})
    else:
        blocks = list(IPBlock.objects.select_related("created_by"))
        context.update({"blocks": blocks})
    return render(request, "studio/security.html", context)
