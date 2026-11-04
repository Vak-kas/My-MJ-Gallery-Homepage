from urllib.parse import urlparse

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login, logout, authenticate, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm, SetPasswordForm
from django.contrib.auth.models import User
from django.contrib.auth.views import PasswordResetCompleteView, PasswordResetConfirmView, PasswordResetDoneView, PasswordResetView
from django.core.cache import cache
from django.core.mail import send_mail
from django.db import transaction
from django.shortcuts import render, redirect
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_http_methods

from accounts import antibot
from accounts.forms import DeleteAccountForm, FindIdForm, UserForm
from accounts.middleware import SESSION_KEY as MUST_CHANGE_KEY
from accounts.models import MustChangePassword, SignupRequest
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

@login_required
def index(request):
    """내 계정: 가입 정보, 비밀번호 변경, 회원탈퇴."""
    return render(request, "accounts/account.html", {"mail_enabled": settings.MAIL_ENABLED})


class _FakeUser:
    def __init__(self, username):
        self.username = username


def _signup_page(request, form):
    return render(request, 'accounts/signup.html', {'form': form, 'form_token': antibot.make_token(), 'honeypot': antibot.HONEYPOT_FIELD})


def signup_view(request):
    if request.method != "POST":
        return _signup_page(request, UserForm())
    ip, ua = client_ip(request), user_agent(request)
    username = (request.POST.get("username") or "")[:150]
    # 1) 봇: 가입된 척 화면만 보여 주고 아무것도 저장하지 않음 (기록만 남김)
    reason = antibot.bot_reason(request.POST)
    if reason:
        LoginEvent.objects.create(username=username, ip=ip, user_agent=ua, result=LoginEvent.RESULT_BOT)
        return render(request, "accounts/signup_pending.html", {"pending_user": _FakeUser(username or "회원")})
    form = UserForm(request.POST)
    # 2) 같은 IP 에서 너무 자주
    if antibot.rate_limited(ip):
        form.add_error(None, "같은 곳에서 가입 요청이 너무 많아요. 1시간 뒤에 다시 시도해 주세요.")
        return _signup_page(request, form)
    if not form.is_valid():
        return _signup_page(request, form)
    message = (form.cleaned_data.get("message") or "").strip()
    flags = antibot.suspicion(form.cleaned_data["username"], form.cleaned_data["real_name"], message, form.cleaned_data["email"], ua)
    # 관리자 승인 전까지는 비활성 계정 (로그인 불가)
    with transaction.atomic():
        user = form.save(commit=False)
        user.is_active = False
        user.first_name = form.cleaned_data["real_name"]  # 실명은 first_name 에 통째로 저장
        user.save()
        signup = SignupRequest.objects.create(
            user=user, message=message, privacy_agreed_at=timezone.now(),
            ip=ip, user_agent=ua, flags=" · ".join(flags),
        )
    antibot.note_signup(ip)
    notify(
        Notification.KIND_SIGNUP,
        f"{'🤖 의심 · ' if flags else ''}{user.first_name}({user.username}) 님이 가입을 요청했어요",
        (f"[{' · '.join(flags)}] " if flags else "") + (signup.message or user.email),
        reverse("studio:users") + "?state=pending",
    )
    return render(request, "accounts/signup_pending.html", {"pending_user": user})


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
            # 관리자가 임시 비밀번호를 준 계정이면 먼저 비밀번호부터 바꾸게
            if MustChangePassword.objects.filter(user=user).exists():
                request.session[MUST_CHANGE_KEY] = True
                messages.info(request, "임시 비밀번호로 로그인했어요. 새 비밀번호를 정해 주세요.")
                return redirect("accounts:password_change")

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

# ── 아이디 찾기 ──────────────────────────────────────────────

def mask_username(username: str) -> str:
    """minjae → mi***e, ab → a*. 전체 아이디는 메일로만."""
    if len(username) <= 2:
        return username[0] + "*" * (len(username) - 1)
    if len(username) <= 4:
        return username[:1] + "*" * (len(username) - 2) + username[-1]
    return username[:2] + "*" * (len(username) - 3) + username[-1]


def _recovery_limited(request, what: str, limit: int = 10) -> bool:
    """같은 IP 에서 한 시간에 limit 번까지만 (아이디 찾기·비밀번호 재설정)."""
    key = f"recovery:{what}:{client_ip(request)}"
    n = cache.get(key, 0) + 1
    cache.set(key, n, 3600)
    return n > limit


@require_http_methods(["GET", "POST"])
def find_id_view(request):
    form = FindIdForm(request.POST or None)
    found, limited = None, False
    if request.method == "POST" and form.is_valid():
        if _recovery_limited(request, "find-id"):
            limited = True
        else:
            name = " ".join(form.cleaned_data["real_name"].split())
            users = list(User.objects.filter(email__iexact=form.cleaned_data["email"].strip(), first_name__iexact=name, is_active=True))
            if users:
                found = [mask_username(u.username) for u in users]
                if settings.MAIL_ENABLED:
                    send_mail(
                        "[MJ Gallery] 찾으신 아이디",
                        f"{name} 님의 아이디는 다음과 같아요.\n\n" + "\n".join(f"  - {u.username} (가입 {u.date_joined:%Y-%m-%d})" for u in users)
                        + f"\n\n로그인: {settings.SITE_URL}{reverse('accounts:login')}\n본인이 요청한 게 아니면 이 메일은 무시해도 돼요.",
                        None, [users[0].email], fail_silently=True,
                    )
            else:
                form.add_error(None, "이름과 이메일이 같은 계정이 없어요. 가입할 때 쓴 이름·이메일인지 확인해 주세요.")
    return render(request, "accounts/find_id.html", {"form": form, "found": found, "limited": limited, "mail_enabled": settings.MAIL_ENABLED})


# ── 비밀번호 재설정 (메일로 온 링크 = 본인 확인) ─────────────────

class PasswordResetStart(PasswordResetView):
    template_name = "accounts/password_reset_form.html"
    email_template_name = "accounts/password_reset_email.txt"
    subject_template_name = "accounts/password_reset_subject.txt"
    success_url = reverse_lazy("accounts:password_reset_done")
    extra_email_context = {"site_url": settings.SITE_URL}

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["mail_enabled"] = settings.MAIL_ENABLED
        return ctx

    def post(self, request, *args, **kwargs):
        if not settings.MAIL_ENABLED:
            messages.error(request, "지금은 메일을 보낼 수 없어서 관리자에게 초기화를 부탁해야 해요.")
            return redirect("accounts:password_reset")
        if _recovery_limited(request, "password-reset", limit=5):
            messages.error(request, "요청이 너무 많아요. 1시간 뒤에 다시 시도해 주세요.")
            return redirect("accounts:password_reset")
        return super().post(request, *args, **kwargs)


class PasswordResetSent(PasswordResetDoneView):
    template_name = "accounts/password_reset_done.html"


class PasswordResetConfirm(PasswordResetConfirmView):
    template_name = "accounts/password_reset_confirm.html"
    success_url = reverse_lazy("accounts:password_reset_complete")
    form_class = SetPasswordForm

    def form_valid(self, form):
        MustChangePassword.objects.filter(user=form.user).delete()
        return super().form_valid(form)


class PasswordResetComplete(PasswordResetCompleteView):
    template_name = "accounts/password_reset_complete.html"


# ── 비밀번호 변경 · 회원탈퇴 ─────────────────────────────────────

@login_required
def password_change_view(request):
    form = PasswordChangeForm(request.user, request.POST or None)
    forced = bool(request.session.get(MUST_CHANGE_KEY))
    if request.method == "POST" and form.is_valid():
        user = form.save()
        update_session_auth_hash(request, user)   # 바꾼 뒤에도 로그인 유지
        MustChangePassword.objects.filter(user=user).delete()
        request.session.pop(MUST_CHANGE_KEY, None)
        messages.success(request, "비밀번호를 바꿨어요.")
        return redirect("accounts:index")
    return render(request, "accounts/password_change.html", {"form": form, "forced": forced})


def _content_counts(user):
    from blog.models import Comment, GuestbookEntry, Post
    from tools.models import ClipItem, SavedPaper, ShortLink

    return {
        "글": Post.objects.filter(author=user).count(),
        "댓글": Comment.objects.filter(author=user).count(),
        "방명록": GuestbookEntry.objects.filter(author=user).count(),
        "클립보드": ClipItem.objects.filter(user=user).count(),
        "저장한 논문": SavedPaper.objects.filter(user=user).count(),
        "단축 링크": ShortLink.objects.filter(owner=user).count(),
    }


@login_required
@require_http_methods(["GET", "POST"])
def delete_account_view(request):
    if request.user.is_superuser:
        messages.error(request, "관리자 계정은 여기서 탈퇴할 수 없어요. 다른 관리자가 Studio 에서 정리해야 해요.")
        return redirect("accounts:index")
    form = DeleteAccountForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        if not request.user.check_password(form.cleaned_data["password"]):
            form.add_error("password", "비밀번호가 맞지 않아요.")
        else:
            from studio.view_handlers.users import _purge_user_content

            user = request.user
            username = user.username
            with transaction.atomic():
                _purge_user_content(user)
                user.delete()   # 좋아요·클립보드·저장 논문 등은 CASCADE, 로그 기록은 SET_NULL
            logout(request)
            return render(request, "accounts/deleted.html", {"username": username})
    return render(request, "accounts/delete.html", {"form": form, "counts": _content_counts(request.user)})
