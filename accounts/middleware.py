"""임시 비밀번호로 로그인한 회원은 비밀번호를 바꿀 때까지 비밀번호 변경·로그아웃 화면만 쓸 수 있게."""

from django.shortcuts import redirect
from django.urls import reverse

SESSION_KEY = "must_change_password"


class MustChangePasswordMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.session.get(SESSION_KEY) and getattr(request, "user", None) and request.user.is_authenticated:
            allowed = {reverse("accounts:password_change"), reverse("accounts:logout")}
            if request.path not in allowed and not request.path.startswith("/static/"):
                return redirect(reverse("accounts:password_change"))
        return self.get_response(request)


class RestrictedUserMiddleware:
    """⚠ 위험 회원: 읽기는 되지만 쓰기(POST 등)는 로그아웃 빼고 전부 막음. 이유는 알려 주지 않음."""

    ALLOWED_PATHS = ("/accounts/logout/", "/accounts/login/")

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if request.method in ("POST", "PUT", "PATCH", "DELETE") and user and user.is_authenticated and not user.is_superuser \
                and not request.path.startswith(self.ALLOWED_PATHS):
            from accounts.models import is_restricted

            if is_restricted(user):
                wants_json = request.headers.get("X-Requested-With") == "fetch" or "application/json" in (request.headers.get("Accept") or "") \
                    or request.content_type == "application/json"
                if wants_json:
                    from django.http import JsonResponse

                    return JsonResponse({"ok": False, "error": "지금은 이 작업을 할 수 없어요. 잠시 뒤 다시 시도해 주세요."}, status=403)
                from django.contrib import messages
                from django.shortcuts import redirect
                from django.utils.http import url_has_allowed_host_and_scheme

                messages.error(request, "지금은 이 작업을 할 수 없어요. 잠시 뒤 다시 시도해 주세요.")
                back = request.META.get("HTTP_REFERER") or "/"
                if not url_has_allowed_host_and_scheme(back, allowed_hosts={request.get_host()}):
                    back = "/"
                return redirect(back)
        return self.get_response(request)
