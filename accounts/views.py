from urllib.parse import urlparse

from django.shortcuts import render, redirect
from django.contrib import messages
from django.contrib.auth.models import User
from django.contrib.auth import login, logout, authenticate
from django.contrib.auth.tokens import default_token_generator
from django.http import HttpResponse
from django.urls import reverse
from django.utils.encoding import force_str
from django.utils.http import url_has_allowed_host_and_scheme, urlsafe_base64_decode
from django.views.decorators.http import require_POST
from accounts.forms import UserForm
from accounts.verification import can_resend, mask_email, send_verification_email

VERIFY_SESSION_KEY = "accounts:pending_verify_user_id"


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
            # 이메일 인증 전까지는 로그인할 수 없는 비활성 계정으로 만듦
            user = form.save(commit=False)
            user.is_active = False
            user.save()
            sent = send_verification_email(request, user)
            request.session[VERIFY_SESSION_KEY] = user.pk
            return redirect(f"{reverse('accounts:verify_sent')}{'' if sent else '?failed=1'}")
    else:
        form = UserForm()
    return render(request, 'accounts/signup.html', {'form': form})


def _pending_user(request):
    user_id = request.session.get(VERIFY_SESSION_KEY)
    if not user_id:
        return None
    return User.objects.filter(pk=user_id, is_active=False).first()


def verify_sent_view(request):
    """인증 메일을 보냈다는 안내 + 다시 보내기."""
    user = _pending_user(request)
    if user is None:
        return redirect('accounts:login')
    return render(request, 'accounts/verify_sent.html', {
        'masked_email': mask_email(user.email),
        'send_failed': request.GET.get('failed') == '1',
    })


@require_POST
def resend_verification_view(request):
    user = _pending_user(request)
    if user is None:
        return redirect('accounts:login')
    if not can_resend(user):
        messages.error(request, "인증 메일은 1분에 한 번만 다시 보낼 수 있습니다.")
    elif send_verification_email(request, user):
        messages.success(request, "인증 메일을 다시 보냈습니다.")
    else:
        messages.error(request, "메일을 보내지 못했습니다. 잠시 후 다시 시도해 주세요.")
    return redirect('accounts:verify_sent')


def verify_email_view(request, uidb64, token):
    try:
        user = User.objects.get(pk=force_str(urlsafe_base64_decode(uidb64)))
    except (TypeError, ValueError, OverflowError, User.DoesNotExist):
        user = None

    if user is not None and user.is_active:
        messages.info(request, "이미 인증된 계정입니다. 로그인해 주세요.")
        return redirect('accounts:login')

    if user is None or not default_token_generator.check_token(user, token):
        return render(request, 'accounts/verify_invalid.html', status=400)

    user.is_active = True
    user.save(update_fields=["is_active"])
    request.session.pop(VERIFY_SESSION_KEY, None)
    login(request, user, backend="django.contrib.auth.backends.ModelBackend")
    return render(request, 'accounts/verify_done.html', {'username': user.get_username()})


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
        if user is None:
            # 비밀번호는 맞지만 이메일 인증을 안 한 계정이면 인증 안내로 보냄
            pending = User.objects.filter(username=username, is_active=False).first()
            if pending is not None and pending.check_password(password or ""):
                request.session[VERIFY_SESSION_KEY] = pending.pk
                messages.info(request, "이메일 인증 후 로그인할 수 있습니다. 메일함을 확인해 주세요.")
                return redirect('accounts:verify_sent')
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