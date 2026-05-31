from urllib.parse import urlparse

from django.shortcuts import render, redirect
from django.contrib.auth.models import User
from django.contrib.auth import login, logout, authenticate
from django.http import HttpResponse
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from accounts.forms import UserForm


def _safe_next_url(request):
    next_url = (request.POST.get("next") or request.GET.get("next") or "").strip()

    if not next_url:
        referer = (request.META.get("HTTP_REFERER") or "").strip()
        if referer:
            parsed = urlparse(referer)
            next_url = parsed.path or "/"
            if parsed.query:
                next_url = f"{next_url}?{parsed.query}"
            if parsed.fragment:
                next_url = f"{next_url}#{parsed.fragment}"

    if not next_url:
        return ""

    if not url_has_allowed_host_and_scheme(
        next_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return ""

    auth_paths = {
        reverse("accounts:login"),
        reverse("accounts:logout"),
        reverse("accounts:signup"),
    }
    if urlparse(next_url).path in auth_paths:
        return ""

    return next_url

def index(request):
    return HttpResponse("안녕하세요. 오신것을 환영합니다.")


def signup_view(request):
    if request.method == "POST":
        form = UserForm(request.POST)
        if form.is_valid():
            form.save()
            username = form.cleaned_data.get('username')
            raw_password = form.cleaned_data.get('password1')
            user = authenticate(username=username, password=raw_password)  # 사용자 인증
            login(request, user)  # 로그인
            return redirect('accounts:index')
    else:
        form = UserForm()
    return render(request, 'accounts/signup.html', {'form': form})


def login_view(request):
    next_url = _safe_next_url(request)

    if request.method == "POST":
        username = request.POST.get('username')
        password = request.POST.get('password')
        user = authenticate(
            request,
            username=username,
            password=password
        )
        if user is not None:
            login(request, user)

            if next_url:
                return redirect(next_url)
            
            # superuser면 studio로
            if user.is_superuser:
                return redirect('studio:index')
            return redirect('accounts:index')
        else:
            return render(request, 'accounts/login.html', {
                'error': '아이디 또는 비밀번호가 올바르지 않습니다.',
                'next_url': next_url,
            })
    return render(request, 'accounts/login.html', {'next_url': next_url})


def logout_view(request):
    next_url = _safe_next_url(request)
    logout(request)
    if next_url:
        return redirect(next_url)
    return redirect('main:home')