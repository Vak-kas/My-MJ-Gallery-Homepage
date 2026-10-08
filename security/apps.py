from django.apps import AppConfig


class SecurityConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "security"
    verbose_name = "보안"

    def ready(self):
        from . import signals  # noqa: F401
