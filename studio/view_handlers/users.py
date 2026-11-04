from django.contrib import messages
from django.contrib.auth import get_user_model
from django.core.paginator import Paginator
from django.db.models import Count, Exists, OuterRef, Q
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone

import secrets

from accounts.models import MustChangePassword, SignupRequest
from blog.models import Comment, GuestbookEntry, Post
from tools.models import SecretNote, ShortLink
from tools.permissions import VIP_GROUP, set_vip

from .common import admin_view

STATES = [
    ("", "전체"),
    ("pending", "🙋 승인 대기"),
    ("unverified", "📧 이메일 미인증"),
    ("active", "활성"),
    ("vip", "⭐ VIP 회원"),
    ("inactive", "정지·거절"),
    ("admin", "관리자"),
]
UNVERIFIED = Q(signup_request__status=SignupRequest.STATUS_PENDING, signup_request__email_verified_at__isnull=True) & ~Q(signup_request__verify_token="")
PENDING = Q(signup_request__status=SignupRequest.STATUS_PENDING) & ~UNVERIFIED   # 인증을 마친 사람만 "승인 대기"


def _purge_user_content(user):
    counts = {
        "posts": Post.objects.filter(author=user).count(),
        "comments": Comment.objects.filter(author=user).count(),
        "guestbook": GuestbookEntry.objects.filter(author=user).count(),
        "links": ShortLink.objects.filter(owner=user).count(),
    }
    Post.objects.filter(author=user).delete()
    Comment.objects.filter(author=user).delete()
    GuestbookEntry.objects.filter(author=user).delete()
    ShortLink.objects.filter(owner=user).delete()
    SecretNote.objects.filter(created_by=user).delete()
    return counts


def _decide(targets, status, admin):
    """대기 중인 가입 요청에 승인/거절 결과를 기록."""
    SignupRequest.objects.filter(user__in=targets, status=SignupRequest.STATUS_PENDING).update(
        status=status, decided_at=timezone.now(), decided_by=admin,
    )


@admin_view
def users(request):
    User = get_user_model()
    base = reverse("studio:users")

    if request.method == "POST":
        return_qs = (request.POST.get("return_qs") or "").strip()
        back = redirect(f"{base}?{return_qs}") if return_qs else redirect(base)
        action = (request.POST.get("action") or "").strip()
        if action == "block_ip":  # 가입한 IP 를 30일 차단 (보안 화면과 같은 규칙: 내 IP·너무 넓은 대역은 거부)
            from .security import _add_block

            _add_block(request, request.POST.get("ip"), f"가입 봇 의심 ({request.POST.get('username', '')[:40]})", "30d")
            return back
        if action == "reset_password":  # 임시 비밀번호 발급 — 한 번만 보여 주고, 그 회원은 다음 로그인 때 바로 바꿔야 함
            target = User.objects.filter(id=(request.POST.get("ids") or "0"), is_superuser=False).exclude(id=request.user.id).first()
            if not target:
                messages.error(request, "본인·관리자 계정의 비밀번호는 여기서 초기화할 수 없어요.")
                return back
            if (request.POST.get("confirm") or "").strip() != target.username:   # 잘못 누름 방지: 아이디를 그대로 입력해야 함
                messages.error(request, f"비밀번호 초기화는 확인 칸에 아이디({target.username})를 똑같이 입력해야 해요.")
                return back
            temp = secrets.token_urlsafe(9)   # 12자 정도, 영숫자·-_
            target.set_password(temp)
            target.save(update_fields=["password"])
            MustChangePassword.objects.update_or_create(user=target, defaults={"issued_by": request.user})
            messages.success(request, f"{target.username} 님 임시 비밀번호: {temp}  — 본인에게만 전해 주세요. 로그인하면 바로 새 비밀번호를 정하게 돼요. (이 화면을 닫으면 다시 볼 수 없어요)")
            return back
        ids = [int(v) for v in request.POST.getlist("ids") if v.isdigit()]
        # 나 자신과 관리자 계정은 일괄 작업 대상에서 제외
        targets = User.objects.filter(id__in=ids, is_superuser=False).exclude(id=request.user.id)
        skipped = len(ids) - targets.count()
        if not targets.exists():
            messages.error(request, "적용할 수 있는 회원이 없습니다. (본인·관리자 계정은 제외됩니다)")
            return back

        names = ", ".join(targets.values_list("username", flat=True)[:5])
        count = targets.count()
        if action == "activate":
            targets.update(is_active=True)
            _decide(targets, SignupRequest.STATUS_APPROVED, request.user)
            messages.success(request, f"{count}명 활성화(승인): {names}")
        elif action == "reject":
            targets.update(is_active=False)
            _decide(targets, SignupRequest.STATUS_REJECTED, request.user)
            messages.success(request, f"{count}명 가입 거절: {names}")
        elif action in {"vip_on", "vip_off"}:
            on = action == "vip_on"
            for user in targets:
                set_vip(user, on)
            messages.success(request, f"{count}명 {'⭐ VIP 회원으로 지정' if on else 'VIP 회원 해제'}: {names}")
        elif action == "suspend":
            targets.update(is_active=False)
            messages.success(request, f"{count}명 정지: {names}")
        elif action in {"purge", "delete"}:
            if (request.POST.get("confirm") or "").strip() != "DELETE":
                messages.error(request, "삭제 작업은 확인 문구(DELETE) 입력이 필요합니다.")
                return back
            total = {"posts": 0, "comments": 0, "guestbook": 0, "links": 0}
            for user in targets:
                for key, n in _purge_user_content(user).items():
                    total[key] += n
            summary = f"글 {total['posts']}개, 댓글 {total['comments']}개, 방명록 {total['guestbook']}개, 단축 링크 {total['links']}개 삭제"
            if action == "purge":
                targets.update(is_active=False)
                messages.success(request, f"{count}명 정지 + 작성한 {summary}: {names}")
            else:
                targets.delete()
                messages.success(request, f"{count}명 계정 삭제 + {summary}: {names}")
        else:
            messages.error(request, "작업 종류가 올바르지 않습니다.")
            return back
        if skipped:
            messages.info(request, f"본인·관리자 계정 {skipped}개는 건너뛰었습니다.")
        return back

    keyword = (request.GET.get("q") or "").strip()
    state = (request.GET.get("state") or "").strip()
    vip_q = Q(groups__name=VIP_GROUP)
    qs = User.objects.select_related("signup_request").annotate(
        is_vip=Exists(User.groups.through.objects.filter(user_id=OuterRef("pk"), group__name=VIP_GROUP)),
        post_count=Count("blog_posts", distinct=True),
        comment_count=Count("blog_comments", distinct=True),
        guestbook_count=Count("guestbook_entries", distinct=True),
    )
    if keyword:
        qs = qs.filter(
            Q(username__icontains=keyword) | Q(email__icontains=keyword)
            | Q(first_name__icontains=keyword) | Q(last_name__icontains=keyword)
        )
    state_counts = {
        "": User.objects.count(),
        "pending": User.objects.filter(PENDING).count(),
        "unverified": User.objects.filter(UNVERIFIED).count(),
        "active": User.objects.filter(is_active=True).count(),
        "vip": User.objects.filter(vip_q).distinct().count(),
        "inactive": User.objects.filter(is_active=False).exclude(PENDING).exclude(UNVERIFIED).count(),
        "admin": User.objects.filter(is_superuser=True).count(),
    }
    if state == "pending":
        qs = qs.filter(PENDING)
    elif state == "unverified":
        qs = qs.filter(UNVERIFIED)
    elif state == "active":
        qs = qs.filter(is_active=True)
    elif state == "vip":
        qs = qs.filter(is_vip=True)
    elif state == "inactive":
        qs = qs.filter(is_active=False).exclude(PENDING).exclude(UNVERIFIED)
    elif state == "admin":
        qs = qs.filter(is_superuser=True)
    else:
        state = ""

    # 정지·승인 대기를 먼저, 그다음 최근 가입순
    paginator = Paginator(qs.order_by("is_active", "-date_joined", "-id"), 30)
    page_obj = paginator.get_page(request.GET.get("page"))
    query = request.GET.copy()
    query.pop("page", None)
    return render(request, "studio/users.html", {
        "users": list(page_obj.object_list),
        "page_obj": page_obj,
        "user_count": paginator.count,
        "keyword": keyword,
        "state": state,
        "states": [(k, label, state_counts[k]) for k, label in STATES],
        "current_query_string": query.urlencode(),
        "pending_count": state_counts["pending"],
    })


@admin_view
def user_detail(request, id):
    """회원 한 명: 정보·가입 기록·활동·로그인 기록 + 승인/정지/VIP/비밀번호/정보 수정/삭제."""
    from security.models import LoginEvent
    from tools.models import AIUsage, ClipItem, HookBin, Meeting, Paste, SavedPaper, SharedFile, StdDoc
    from tools.permissions import is_vip

    User = get_user_model()
    target = User.objects.select_related("signup_request").filter(id=id).first()
    if not target:
        messages.error(request, "그런 회원이 없어요.")
        return redirect("studio:users")
    here = redirect("studio:user_detail", id=target.id)
    protected = target.is_superuser or target.id == request.user.id

    if request.method == "POST":
        action = (request.POST.get("action") or "").strip()
        if action == "edit":  # 아이디·이름·이메일 고치기 (본인·관리자도 가능)
            from django.contrib.auth.validators import UnicodeUsernameValidator
            from django.core.exceptions import ValidationError

            username = (request.POST.get("username") or target.username).strip()[:150]
            first_name = (request.POST.get("first_name") or "").strip()[:150]
            email = (request.POST.get("email") or "").strip()[:254]
            if username != target.username:
                try:
                    UnicodeUsernameValidator()(username)
                except ValidationError:
                    messages.error(request, "아이디는 글자·숫자·@ . + - _ 만 쓸 수 있어요.")
                    return here
                if User.objects.filter(username__iexact=username).exclude(id=target.id).exists():
                    messages.error(request, "그 아이디를 쓰는 다른 회원이 있어요.")
                    return here
            if email and User.objects.filter(email__iexact=email).exclude(id=target.id).exists():
                messages.error(request, "그 이메일을 쓰는 다른 회원이 있어요.")
                return here
            old_username = target.username
            target.username, target.first_name, target.email = username, first_name, email
            target.save(update_fields=["username", "first_name", "email"])
            if username != old_username:
                from security.models import LoginEvent

                LoginEvent.objects.filter(user=target).update(username=username)  # 기록도 새 아이디로
                messages.success(request, f"아이디를 {old_username} → {username} 로 바꿨어요. 회원에게 알려 주세요 (로그인 아이디가 바뀜).")
            else:
                messages.success(request, "회원 정보를 고쳤어요.")
            return here
        if action == "block_ip":
            from .security import _add_block

            _add_block(request, request.POST.get("ip"), f"가입 봇 의심 ({target.username[:40]})", "30d")
            return here
        if protected:
            messages.error(request, "본인·관리자 계정에는 이 작업을 할 수 없어요.")
            return here
        if action == "reset_password":
            if (request.POST.get("confirm") or "").strip() != target.username:
                messages.error(request, f"비밀번호 초기화는 확인 칸에 아이디({target.username})를 똑같이 입력해야 해요.")
                return here
            temp = secrets.token_urlsafe(9)
            target.set_password(temp)
            target.save(update_fields=["password"])
            MustChangePassword.objects.update_or_create(user=target, defaults={"issued_by": request.user})
            messages.success(request, f"{target.username} 님 임시 비밀번호: {temp}  — 본인에게만 전해 주세요. 로그인하면 바로 새 비밀번호를 정하게 돼요. (이 화면을 닫으면 다시 볼 수 없어요)")
            return here
        targets = User.objects.filter(id=target.id)
        if action == "activate":
            targets.update(is_active=True)
            _decide(targets, SignupRequest.STATUS_APPROVED, request.user)
            messages.success(request, "활성화(승인)했어요.")
        elif action == "reject":
            targets.update(is_active=False)
            _decide(targets, SignupRequest.STATUS_REJECTED, request.user)
            messages.success(request, "가입을 거절했어요.")
        elif action == "suspend":
            targets.update(is_active=False)
            messages.success(request, "정지했어요. 다시 쓰게 하려면 '활성화'.")
        elif action in {"vip_on", "vip_off"}:
            set_vip(target, action == "vip_on")
            messages.success(request, "⭐ VIP 회원으로 지정했어요." if action == "vip_on" else "VIP 회원을 해제했어요.")
        elif action in {"purge", "delete"}:
            if (request.POST.get("confirm") or "").strip() != "DELETE":
                messages.error(request, "삭제 작업은 확인 문구(DELETE) 입력이 필요합니다.")
                return here
            n = _purge_user_content(target)
            summary = f"글 {n['posts']}개, 댓글 {n['comments']}개, 방명록 {n['guestbook']}개, 단축 링크 {n['links']}개 삭제"
            if action == "purge":
                targets.update(is_active=False)
                messages.success(request, f"정지 + 작성한 {summary}")
            else:
                name = target.username
                target.delete()
                messages.success(request, f"{name} 계정 삭제 + {summary}")
                return redirect("studio:users")
        else:
            messages.error(request, "작업 종류가 올바르지 않습니다.")
        return here

    signup = getattr(target, "signup_request", None)
    login_events = list(LoginEvent.objects.filter(Q(user=target) | Q(username=target.username)).order_by("-created_at")[:20])
    ips = {}
    for ev in LoginEvent.objects.filter(Q(user=target) | Q(username=target.username), result=LoginEvent.RESULT_SUCCESS).exclude(ip=None).order_by("-created_at")[:200]:
        ips.setdefault(ev.ip, {"ip": ev.ip, "count": 0, "last": ev.created_at})
        ips[ev.ip]["count"] += 1
    if signup and signup.status == SignupRequest.STATUS_PENDING:
        status = ("unverified", "📧 이메일 미인증") if signup.needs_verification() else ("pending", "승인 대기")
    elif target.is_superuser:
        status = ("admin", "관리자")
    elif target.is_active:
        status = ("active", "활성")
    elif signup and signup.status == SignupRequest.STATUS_REJECTED:
        status = ("rejected", "거절됨")
    else:
        status = ("suspended", "정지")
    counts = {
        "posts": Post.objects.filter(author=target).count(), "comments": Comment.objects.filter(author=target).count(),
        "guestbook": GuestbookEntry.objects.filter(author=target).count(), "links": ShortLink.objects.filter(owner=target).count(),
        "notes": SecretNote.objects.filter(created_by=target).count(), "clips": ClipItem.objects.filter(user=target).count(),
        "papers": SavedPaper.objects.filter(user=target).count(), "stddocs": StdDoc.objects.filter(user=target).count(),
        "pastes": Paste.objects.filter(owner=target).count(), "hooks": HookBin.objects.filter(owner=target).count(),
        "meetings": Meeting.objects.filter(owner=target).count(), "shared": SharedFile.objects.filter(created_by=target).count(),
        "ai": AIUsage.objects.filter(user=target).count(),
    }
    return render(request, "studio/user_detail.html", {
        "target": target, "signup": signup, "protected": protected, "status": status, "is_vip": is_vip(target),
        "must_change": MustChangePassword.objects.filter(user=target).select_related("issued_by").first(),
        "counts": counts,
        "recent_posts": list(Post.objects.filter(author=target).order_by("-id")[:8]),
        "recent_comments": list(Comment.objects.filter(author=target).select_related("post").order_by("-id")[:8]),
        "recent_guestbook": list(GuestbookEntry.objects.filter(author=target).order_by("-id")[:5]),
        "login_events": login_events, "ips": sorted(ips.values(), key=lambda r: r["last"], reverse=True)[:10],
        "recent_views": list(__import__("analytics.models", fromlist=["PageView"]).PageView.objects.filter(user=target).order_by("-created_at")[:20]),
    })
