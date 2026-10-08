from . import site_settings


def site_nav(request):
    user = getattr(request, "user", None)
    if user is None:
        return {}
    return {"site_nav": site_settings.visible_nav(user)}
