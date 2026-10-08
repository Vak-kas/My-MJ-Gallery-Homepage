from urllib.parse import urlencode

from django.http import Http404
from django.shortcuts import redirect
from django.urls import reverse

from . import site_settings


class SectionAccessMiddleware:
    """Settings 에서 숨기거나 회원 전용으로 바꾼 메뉴(블로그·Tool·갤러리)의 페이지 접근을 막음. 관리자는 항상 통과."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        key, is_share_link = site_settings.section_for_path(request.path)
        if key:
            state = site_settings.nav_state(key)
            user = request.user
            if state == "members" and is_share_link:
                pass  # 회원 전용이어도 받은 링크(데이터 전송·맡겨두기·비밀 메모)는 비로그인도 열 수 있음
            elif not site_settings.can_see(state, user):
                if state == "members" and not user.is_authenticated:
                    return redirect(f"{reverse('accounts:login')}?{urlencode({'next': request.get_full_path()})}")
                raise Http404("이 메뉴는 지금 열려 있지 않습니다.")
        return self.get_response(request)
