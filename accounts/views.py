from urllib.parse import urlparse

from django.shortcuts import render, redirect
from django.contrib.auth.models import User
from django.contrib.auth import login, logout, authenticate
from django.http import HttpResponse
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.db import transaction
from django.utils import timezone

from accounts.forms import UserForm
from accounts.models import SignupRequest
from security.models import LoginEvent
from security.utils import clear_failures, client_ip, is_locked, record_failure, user_agent
from notifications.models import Notification
from notifications.service import notify


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
            # 관리자 승인 전까지는 비활성 계정 (로그인 불가)
            with transaction.atomic():
                user = form.save(commit=False)
                user.is_active = False
                user.first_name = form.cleaned_data["real_name"]  # 실명은 first_name 에 통째로 저장
                user.save()
                signup = SignupRequest.objects.create(
                    user=user, message=(form.cleaned_data.get("message") or "").strip(),
                    privacy_agreed_at=timezone.now(),
                )
            notify(
                Notification.KIND_SIGNUP,
                f"{user.first_name}({user.username}) 님이 가입을 요청했어요",
                signup.message or user.email,
                reverse("studio:users") + "?state=pending",
            )
            return render(request, "accounts/signup_pending.html", {"pending_user": user})
    else:
        form = UserForm()
    return render(request, 'accounts/signup.html', {'form': form})


def _inactive_reason(username, password):
    """비밀번호는 맞는데 비활성인 계정이면 이유를 알려줌 (승인 대기 / 거절 / 정지)."""
    candidate = User.objects.filter(username=username, is_active=False).first()
    if not candidate or not candidate.check_password(password or ""):
        return None
    signup = SignupRequest.objects.filter(user=candidate).first()
    if signup and signup.status == SignupRequest.STATUS_PENDING:
        return "아직 관리자 승인 대기 중이에요. 승인되면 로그인할 수 있어요."
    if signup and signup.status == SignupRequest.STATUS_REJECTED:
        return "가입 요청이 승인되지 않았어요."
    return "이용이 정지된 계정입니다."


def login_view(request):
    next_url = _safe_next_url(request)

    if request.method == "POST":
        username = request.POST.get('username')
        password = request.POST.get('password')
        ip = client_ip(request)
        if is_locked(ip, username):
            LoginEvent.objects.create(
                username=(username or "")[:150], ip=ip, user_agent=user_agent(request), result=LoginEvent.RESULT_LOCKED,
            )
            return render(request, 'accounts/login.html', {
                'error': '로그인 실패가 너무 많아 잠시 잠겼어요. 15분 뒤에 다시 시도해 주세요.',
                'next_url': next_url,
            })
        user = authenticate(
            request,
            username=username,
            password=password
        )
        if user is not None:
            clear_failures(ip, username)
            login(request, user)

            if next_url:
                return redirect(next_url)
            
            # superuser면 studio로
            if user.is_superuser:
                return redirect('studio:index')
            return redirect('main:home')
        else:
            record_failure(ip, username)
            return render(request, 'accounts/login.html', {
                'error': _inactive_reason(username, password) or '아이디 또는 비밀번호가 올바르지 않습니다.',
                'next_url': next_url,
            })
    return render(request, 'accounts/login.html', {'next_url': next_url})


def logout_view(request):
    next_url = _safe_next_url(request)
    logout(request)
    if next_url:
        return redirect(next_url)
    return redirect('main:home')