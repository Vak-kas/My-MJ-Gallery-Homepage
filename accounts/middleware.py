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
