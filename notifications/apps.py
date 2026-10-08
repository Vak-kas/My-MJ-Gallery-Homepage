from django.apps import AppConfig


class NotificationsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "notifications"
    verbose_name = "관리자 알림"

    def ready(self):
        from . import signals  # noqa: F401
