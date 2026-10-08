import secrets

from django.conf import settings
from django.contrib import messages
from django.core.paginator import Paginator
from django.urls import reverse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from studio.view_handlers.common import admin_view

from . import kakao
from .models import KakaoLink, Notification


@admin_view
def notification_list(request):
    qs = Notification.objects.all()
    kind = (request.GET.get("kind") or "").strip()
    if kind in dict(Notification.KIND_CHOICES):
        qs = qs.filter(kind=kind)
    else:
        kind = ""
    page_obj = Paginator(qs, 40).get_page(request.GET.get("page"))
    return render(request, "notifications/list.html", {
        "page_obj": page_obj,
        "items": list(page_obj.object_list),
        "kind": kind,
        "kinds": Notification.KIND_CHOICES,
        "unread_total": Notification.objects.filter(is_read=False).count(),
        "kakao_configured": kakao.is_configured(),
        "kakao_link": KakaoLink.objects.select_related("connected_by").first(),
    })


@admin_view
@require_POST
def notification_open(request, id):
    item = get_object_or_404(Notification, id=id)
    if not item.is_read:
        item.is_read = True
        item.save(update_fields=["is_read"])
    if item.url and url_has_allowed_host_and_scheme(item.url, allowed_hosts={request.get_host()}):
        return redirect(item.url)
    return redirect("notifications:list")


@admin_view
@require_POST
def notification_read_all(request):
    Notification.objects.filter(is_read=False).update(is_read=True)
    return redirect("notifications:list")


@admin_view
@require_POST
def notification_clear_read(request):
    Notification.objects.filter(is_read=True).delete()
    return redirect("notifications:list")


def _kakao_redirect_uri(request):
    # 카카오 콘솔에 등록한 주소와 글자 하나까지 같아야 함. 서버(nginx 뒤)에서는 SITE_URL 기준
    path = reverse("notifications:kakao_callback")
    if request.get_host().split(":")[0] in {"127.0.0.1", "localhost"}:
        return request.build_absolute_uri(path)
    return settings.SITE_URL.rstrip("/") + path


@admin_view
@require_POST
def kakao_connect(request):
    if not kakao.is_configured():
        messages.error(request, "서버 .env 에 KAKAO_REST_API_KEY 가 없습니다.")
        return redirect("notifications:list")
    state = secrets.token_urlsafe(24)
    request.session["kakao_oauth_state"] = state
    return redirect(kakao.authorize_url(_kakao_redirect_uri(request), state))


@admin_view
def kakao_callback(request):
    expected = request.session.pop("kakao_oauth_state", None)
    if not expected or request.GET.get("state") != expected:
        messages.error(request, "카카오 연결 요청이 올바르지 않습니다. 다시 시도해 주세요.")
        return redirect("notifications:list")
    if request.GET.get("error") or not request.GET.get("code"):
        messages.error(request, "카카오 연결이 취소됐습니다.")
        return redirect("notifications:list")
    try:
        kakao.connect(request.GET["code"], _kakao_redirect_uri(request), request.user)
    except kakao.KakaoError as exc:
        messages.error(request, f"카카오 연결 실패: {exc}")
        return redirect("notifications:list")
    if kakao.send_text("✅ 서민재 갤러리 알림이 카카오톡에 연결됐어요.", reverse("notifications:list")):
        messages.success(request, "카카오톡이 연결됐어요. 나와의 채팅에 테스트 메시지를 보냈어요.")
    else:
        messages.error(request, "연결은 됐지만 테스트 메시지 전송에 실패했어요: " + (KakaoLink.objects.first().last_error or ""))
    return redirect("notifications:list")


@admin_view
@require_POST
def kakao_test(request):
    if kakao.send_text("🔔 서민재 갤러리 테스트 알림입니다.", reverse("notifications:list")):
        messages.success(request, "테스트 메시지를 보냈어요.")
    else:
        link = KakaoLink.objects.first()
        messages.error(request, "전송 실패: " + (link.last_error if link else "연결돼 있지 않아요."))
    return redirect("notifications:list")


@admin_view
@require_POST
def kakao_disconnect(request):
    KakaoLink.objects.all().delete()
    messages.success(request, "카카오톡 연결을 해제했어요.")
    return redirect("notifications:list")
