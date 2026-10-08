from django.contrib.auth.signals import user_logged_in, user_login_failed
from django.dispatch import receiver
from django.urls import reverse

from .models import LoginEvent
from .utils import client_ip, user_agent


@receiver(user_logged_in)
def on_login(sender, request, user, **kwargs):
    if request is None:
        return
    ip = client_ip(request)
    seen = LoginEvent.objects.filter(user=user, result=LoginEvent.RESULT_SUCCESS, ip=ip).exists()
    has_history = LoginEvent.objects.filter(user=user, result=LoginEvent.RESULT_SUCCESS).exists()
    event = LoginEvent.objects.create(
        username=user.get_username(), user=user, ip=ip, user_agent=user_agent(request),
        result=LoginEvent.RESULT_SUCCESS, is_admin=user.is_superuser, new_location=has_history and not seen,
    )
    # 관리자 계정이 처음 보는 IP 에서 로그인하면 바로 알림 (카톡 포함)
    if user.is_superuser and event.new_location:
        from notifications.models import Notification
        from notifications.service import notify

        notify(
            Notification.KIND_SECURITY,
            f"관리자 계정 {user.get_username()} 이(가) 새 IP 에서 로그인했어요",
            f"IP {ip} · {event.user_agent[:120]}\n본인이 아니면 바로 비밀번호를 바꾸고 이 IP 를 차단하세요.",
            reverse("studio:security") + "?tab=logins",
        )


@receiver(user_login_failed)
def on_login_failed(sender, credentials, request=None, **kwargs):
    if request is None:
        return
    LoginEvent.objects.create(
        username=(credentials.get("username") or "")[:150], ip=client_ip(request),
        user_agent=user_agent(request), result=LoginEvent.RESULT_FAILED,
    )
