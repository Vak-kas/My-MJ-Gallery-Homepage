import unicodedata
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
from accounts.forms import DeleteAccountForm, FindIdForm, ProfileForm, UserForm
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
    from accounts.models import two_factor_enabled

    return render(request, "accounts/account.html", {"mail_enabled": settings.MAIL_ENABLED, "two_factor_on": two_factor_enabled(request.user)})


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
    if settings.MAIL_ENABLED:
        # 메일이 켜져 있으면: 인증 링크를 누른 뒤에야 관리자에게 알리고 승인 대기에 들어감
        _send_verify_mail(signup)
        return render(request, "accounts/signup_pending.html", {"pending_user": user, "verify": True})
    _notify_signup(signup)
    return render(request, "accounts/signup_pending.html", {"pending_user": user, "verify": False})


def _notify_signup(signup):
    user, flags = signup.user, signup.flag_list
    notify(
        Notification.KIND_SIGNUP,
        f"{'🤖 의심 · ' if flags else ''}{user.first_name}({user.username}) 님이 가입을 요청했어요",
        (f"[{' · '.join(flags)}] " if flags else "") + (signup.message or user.email),
        reverse("studio:users") + "?state=pending",
    )


def _send_verify_mail(signup):
    token = signup.issue_verify_token()
    link = f"{settings.SITE_URL}{reverse('accounts:verify_email', args=[signup.user_id, token])}"
    send_mail(
        "[MJ Gallery] 가입 이메일 인증",
        f"{signup.user.first_name or signup.user.username} 님, MJ Gallery 가입 신청 고마워요.\n\n"
        f"아래 링크를 눌러 이메일을 인증해 주세요 ({SignupRequest.VERIFY_HOURS}시간 안에).\n\n{link}\n\n"
        f"인증이 끝나면 관리자가 확인한 뒤 승인해요. 본인이 신청한 게 아니면 이 메일은 무시해도 돼요 "
        f"({SignupRequest.UNVERIFIED_KEEP_DAYS}일 뒤 자동으로 지워져요).",
        None, [signup.user.email], fail_silently=True,
    )


def verify_email_view(request, user_id: int, token: str):
    signup = SignupRequest.objects.filter(user_id=user_id).select_related("user").first()
    if signup and signup.email_verified_at:
        return render(request, "accounts/verify_done.html", {"pending_user": signup.user, "already": True})
    if not signup or not signup.verify_link_valid(token):
        return render(request, "accounts/verify_invalid.html", {"form": None}, status=400)
    signup.mark_verified()
    _notify_signup(signup)
    return render(request, "accounts/verify_done.html", {"pending_user": signup.user, "already": False})


@require_http_methods(["GET", "POST"])
def verify_resend_view(request):
    """인증 메일 다시 보내기. 계정이 있든 없든 같은 화면 (있는지 떠보기 방지)."""
    sent = False
    if request.method == "POST":
        if not settings.MAIL_ENABLED:
            messages.error(request, "지금은 메일을 보낼 수 없어요. 관리자에게 문의해 주세요.")
        elif _recovery_limited(request, "verify-resend", limit=5):
            messages.error(request, "요청이 너무 많아요. 1시간 뒤에 다시 시도해 주세요.")
        else:
            email = (request.POST.get("email") or "").strip()
            signup = SignupRequest.objects.filter(
                user__email__iexact=email, status=SignupRequest.STATUS_PENDING, email_verified_at__isnull=True,
            ).exclude(verify_token="").select_related("user").first()
            if signup:
                _send_verify_mail(signup)
            sent = True
    return render(request, "accounts/verify_resend.html", {"sent": sent, "mail_enabled": settings.MAIL_ENABLED})


def _inactive_reason(username, password):
    """비밀번호는 맞는데 비활성인 계정이면 이유를 알려줌 (승인 대기 / 거절 / 정지)."""
    candidate = User.objects.filter(username=username, is_active=False).first()
    if not candidate or not candidate.check_password(password or ""):
        return None
    signup = SignupRequest.objects.filter(user=candidate).first()
    if signup and signup.needs_verification:
        return "이메일 인증이 아직 안 됐어요. 가입할 때 받은 메일의 링크를 눌러 주세요."
    if signup and signup.status == SignupRequest.STATUS_PENDING:
        return "아직 관리자 승인 대기 중이에요. 승인되면 로그인할 수 있어요."
    if signup and signup.status == SignupRequest.STATUS_REJECTED:
        return "가입 요청이 승인되지 않았어요."
    return "이용이 정지된 계정입니다."


def login_view(request):
    next_url = _safe_next_url(request)

    if request.method == "POST":
        # 가입 폼(UsernameField)이 아이디를 NFKC 로 정규화해 저장하므로 로그인도 똑같이 — 'ㅎㅇ'(호환 자모) 와 'ᄒᄋ'(조합형) 가 같은 계정이 되게
        username = unicodedata.normalize("NFKC", (request.POST.get('username') or "").strip())
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
            # 2단계 인증이 켜진 계정이면 코드 단계로 (기억한 브라우저는 생략)
            from accounts.models import two_factor_enabled

            if two_factor_enabled(user) and not _trusted_browser(request, user):
                request.session[PENDING_2FA_KEY] = {"u": user.id, "next": next_url or "", "t": timezone.now().timestamp()}
                return redirect("accounts:two_factor_verify")
            return _finish_login(request, user, next_url)
        else:
            record_failure(ip, username)
            reason = _inactive_reason(username, password)
            return render(request, 'accounts/login.html', {
                'error': reason or '아이디 또는 비밀번호가 올바르지 않습니다.',
                'show_resend': bool(reason and "이메일 인증" in reason),
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


@login_required
@require_http_methods(["GET", "POST"])
def profile_edit_view(request):
    """회원정보 수정: 이름·이메일 (지금 비밀번호 확인)."""
    user = request.user
    initial = {"real_name": user.first_name, "email": user.email}
    form = ProfileForm(user, request.POST or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        user.first_name = form.cleaned_data["real_name"]
        user.email = form.cleaned_data["email"]
        user.save(update_fields=["first_name", "email"])
        messages.success(request, "회원정보를 바꿨어요.")
        return redirect("accounts:index")
    return render(request, "accounts/profile_edit.html", {"form": form})


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


# ── 2단계 인증 (TOTP) ────────────────────────────────────────

PENDING_2FA_KEY = "pending_2fa"
TRUST_COOKIE = "mj2fa"
TRUST_DAYS = 30


def _trusted_browser(request, user) -> bool:
	"""'이 브라우저 30일 기억' 쿠키(서명됨)가 이 계정 것이면 코드 생략."""
	from django.core import signing

	raw = request.COOKIES.get(TRUST_COOKIE)
	if not raw:
		return False
	try:
		data = signing.loads(raw, salt="accounts.2fa.trust", max_age=TRUST_DAYS * 24 * 3600)
	except signing.BadSignature:
		return False
	return data.get("u") == user.id and data.get("p") == user.password[-12:]


def _finish_login(request, user, next_url, remember=False):
	from django.core import signing

	login(request, user)
	if MustChangePassword.objects.filter(user=user).exists():
		request.session[MUST_CHANGE_KEY] = True
		messages.info(request, "임시 비밀번호로 로그인했어요. 새 비밀번호를 정해 주세요.")
		response = redirect("accounts:password_change")
	elif next_url:
		response = redirect(next_url)
	elif user.is_superuser:
		response = redirect("studio:index")
	else:
		response = redirect("main:home")
	if remember:
		token = signing.dumps({"u": user.id, "p": user.password[-12:]}, salt="accounts.2fa.trust")
		response.set_cookie(TRUST_COOKIE, token, max_age=TRUST_DAYS * 24 * 3600, httponly=True, samesite="Lax", secure=request.is_secure())
	return response


def two_factor_verify_view(request):
	"""비밀번호는 맞았고 코드만 남은 단계."""
	from accounts.models import TwoFactor

	pending = request.session.get(PENDING_2FA_KEY) or {}
	user = User.objects.filter(id=pending.get("u"), is_active=True).first() if pending else None
	if not user or timezone.now().timestamp() - pending.get("t", 0) > 10 * 60:
		request.session.pop(PENDING_2FA_KEY, None)
		messages.error(request, "로그인을 처음부터 다시 해 주세요.")
		return redirect("accounts:login")
	ip = client_ip(request)
	if request.method == "POST":
		if is_locked(ip, user.username):
			return render(request, "accounts/two_factor_verify.html", {"error": "시도가 너무 많아 잠시 잠겼어요. 15분 뒤에 다시 해 주세요."})
		tf = TwoFactor.objects.filter(user=user, enabled=True).first()
		if tf and tf.verify_code(request.POST.get("code") or ""):
			clear_failures(ip, user.username)
			request.session.pop(PENDING_2FA_KEY, None)
			return _finish_login(request, user, pending.get("next") or "", remember=request.POST.get("remember") == "1")
		record_failure(ip, user.username)
		LoginEvent.objects.create(user=user, username=user.username, ip=ip, user_agent=user_agent(request), result=LoginEvent.RESULT_FAILED, is_admin=user.is_superuser)
		return render(request, "accounts/two_factor_verify.html", {"error": "코드가 맞지 않아요. 인증 앱의 지금 코드(6자리)나 백업 코드(8자리)를 넣어 주세요."})
	return render(request, "accounts/two_factor_verify.html", {})


@login_required
def two_factor_view(request):
	"""내 계정 › 2단계 인증: 켜기(QR → 코드 확인 → 백업 코드), 끄기(비밀번호 + 코드), 백업 코드 다시 만들기."""
	from django.core import signing

	from accounts import totp
	from accounts.models import TwoFactor

	tf = TwoFactor.objects.filter(user=request.user).first()
	ctx = {"tf": tf, "enabled": bool(tf and tf.enabled)}
	if request.method == "POST":
		action = request.POST.get("action")
		if action == "start":  # 새 비밀키 — 아직 켜진 건 아님
			if tf and tf.enabled:
				messages.error(request, "이미 켜져 있어요. 다시 설정하려면 먼저 끄세요.")
				return redirect("accounts:two_factor")
			secret = totp.generate_secret()
			tf, _ = TwoFactor.objects.update_or_create(user=request.user, defaults={"secret": secret, "enabled": False, "backup_codes": [], "last_counter": 0})
			ctx.update({"tf": tf, "setup": True})
		elif action == "confirm":  # 앱에 넣은 뒤 지금 코드로 확인 → 켜짐 + 백업 코드
			if not tf or tf.enabled:
				return redirect("accounts:two_factor")
			counter = totp.verify(tf.secret, request.POST.get("code") or "")
			if counter is None:
				ctx.update({"setup": True, "error": "코드가 맞지 않아요. 앱에 QR 을 다시 넣고 지금 코드를 입력해 주세요."})
			else:
				tf.enabled, tf.confirmed_at, tf.last_counter = True, timezone.now(), counter
				tf.save(update_fields=["enabled", "confirmed_at", "last_counter", "updated_at"])
				codes = tf.issue_backup_codes()
				ctx.update({"enabled": True, "backup_codes": codes, "just_enabled": True})
				response = render(request, "accounts/two_factor.html", ctx)
				token = signing.dumps({"u": request.user.id, "p": request.user.password[-12:]}, salt="accounts.2fa.trust")
				response.set_cookie(TRUST_COOKIE, token, max_age=TRUST_DAYS * 24 * 3600, httponly=True, samesite="Lax", secure=request.is_secure())
				return response
		elif action == "disable":  # 비밀번호 + 코드
			if not tf or not tf.enabled:
				return redirect("accounts:two_factor")
			if not request.user.check_password(request.POST.get("password") or ""):
				ctx["error"] = "비밀번호가 맞지 않아요."
			elif not tf.verify_code(request.POST.get("code") or ""):
				ctx["error"] = "코드가 맞지 않아요."
			else:
				tf.delete()
				messages.success(request, "2단계 인증을 껐어요.")
				response = redirect("accounts:two_factor")
				response.delete_cookie(TRUST_COOKIE)
				return response
		elif action == "backup":  # 백업 코드 새로 (코드 확인)
			if tf and tf.enabled and tf.verify_code(request.POST.get("code") or ""):
				ctx.update({"backup_codes": tf.issue_backup_codes()})
			else:
				ctx["error"] = "코드가 맞지 않아요."
		elif action == "cancel":
			if tf and not tf.enabled:
				tf.delete()
			return redirect("accounts:two_factor")
	if ctx.get("setup") and tf:
		ctx["otpauth"] = totp.otpauth_uri(tf.secret, request.user.username)
		ctx["secret_groups"] = " ".join(tf.secret[i:i + 4] for i in range(0, len(tf.secret), 4))
	ctx["backup_left"] = len(tf.backup_codes) if tf and tf.enabled else 0
	ctx["trusted"] = _trusted_browser(request, request.user) if tf and tf.enabled else False
	return render(request, "accounts/two_factor.html", ctx)
