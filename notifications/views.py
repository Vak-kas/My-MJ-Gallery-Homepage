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
from .models import AlertMail, KakaoLink, Notification


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
        "alert_mail": AlertMail.get(),
        "mail_enabled": settings.MAIL_ENABLED,
    })


@admin_view
@require_POST
def alert_mail_save(request):
    """메일 알림 설정: 주소 · 종류 · 켜기/끄기."""
    pref = AlertMail.get()
    email = (request.POST.get("email") or "").strip()[:254]
    kinds = [k for k in request.POST.getlist("kinds") if k in dict(Notification.KIND_CHOICES)]
    enabled = request.POST.get("enabled") == "1"
    if enabled and not email:
        messages.error(request, "받을 메일 주소를 적어 주세요.")
        return redirect("notifications:list")
    pref.email, pref.kinds, pref.enabled = email, kinds, enabled
    pref.save(update_fields=["email", "kinds", "enabled", "updated_at"])
    messages.success(request, "메일 알림을 켰어요." if enabled else "메일 알림 설정을 저장했어요 (꺼짐).")
    return redirect("notifications:list")


@admin_view
@require_POST
def alert_mail_test(request):
    from .service import _push_mail

    pref = AlertMail.get()
    if not pref.email:
        messages.error(request, "받을 메일 주소를 먼저 저장해 주세요.")
        return redirect("notifications:list")
    item = Notification(kind=Notification.KIND_MONITOR, title="메일 알림 테스트", body="이 메일이 보이면 알림 메일이 잘 가요.", url="/notifications/")
    try:
        _push_mail(item, pref)
        messages.success(request, f"{pref.email} 로 테스트 메일을 보냈어요.")
    except Exception as exc:  # noqa: BLE001
        messages.error(request, f"보내지 못했어요: {exc}")
    return redirect("notifications:list")


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


@admin_view
def notification_recent(request):
    """사이트 이용 중 토스트용: since(알림 id) 뒤에 생긴 안 읽은 알림 + 안 읽은 수."""
    from django.http import JsonResponse

    try:
        since = int(request.GET.get("since") or 0)
    except ValueError:
        since = 0
    qs = Notification.objects.filter(is_read=False)
    latest = Notification.objects.order_by("-id").values_list("id", flat=True).first() or 0
    items = []
    if since:
        items = [{"id": n.id, "icon": n.icon, "title": n.title, "body": n.body, "kind": n.get_kind_display()} for n in qs.filter(id__gt=since).order_by("id")[:5]]
    return JsonResponse({"ok": True, "latest": latest, "unread": qs.count(), "items": items})
