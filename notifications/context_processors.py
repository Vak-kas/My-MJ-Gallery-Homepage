from .models import Notification


def admin_notifications(request):
    user = getattr(request, "user", None)
    if not (user and user.is_authenticated and user.is_superuser):
        return {}
    return {"notif_unread_count": Notification.objects.filter(is_read=False).count()}
