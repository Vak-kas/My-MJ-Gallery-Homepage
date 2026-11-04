from django.conf import settings


def webmail(request):
	user = getattr(request, "user", None)
	if not (user and user.is_authenticated and user.is_superuser):
		return {}
	return {"webmail_enabled": settings.WEBMAIL_ENABLED}
