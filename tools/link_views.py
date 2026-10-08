"""단축 URL · 1회용 비밀 메모 (만들기는 회원, 링크 열기는 누구나)."""

import json
from datetime import timedelta
from urllib.parse import urlparse

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.db import IntegrityError, transaction
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from .models import SecretNote, ShortLink, short_code

MAX_LINKS_PER_USER = 200
LINK_TTL_DAYS = {"": None, "1": 1, "7": 7, "30": 30}
MAX_NOTE_CHARS = 20_000          # 암호문(base64) 기준, 평문 약 14KB
MAX_ACTIVE_NOTES = 50
NOTE_TTL_HOURS = {"1": 1, "24": 24, "168": 168}


def _absolute(request, path):
	# 서버(nginx 뒤)에서는 SITE_URL 기준, 로컬 개발은 요청 주소 기준
	if request.get_host().split(":")[0] in {"127.0.0.1", "localhost"}:
		return request.build_absolute_uri(path)
	return settings.SITE_URL.rstrip("/") + path


# ── 단축 URL ─────────────────────────────

def _clean_target(raw, request):
	url = (raw or "").strip()
	if url and "://" not in url:
		url = "https://" + url
	try:
		URLValidator(schemes=["http", "https"])(url)
	except ValidationError:
		raise ValueError("http:// 또는 https:// 로 시작하는 올바른 주소를 넣어 주세요.")
	parsed = urlparse(url)
	own_hosts = {request.get_host().split(":")[0], urlparse(settings.SITE_URL).hostname}
	if parsed.hostname in own_hosts and parsed.path.startswith("/s/"):
		raise ValueError("단축 링크를 다시 줄일 수는 없어요.")
	return url


@login_required
def shortlink(request):
	links = ShortLink.objects.filter(owner=request.user)
	if request.method == "POST":
		try:
			target = _clean_target(request.POST.get("url"), request)
			if links.count() >= MAX_LINKS_PER_USER:
				raise ValueError(f"단축 링크는 {MAX_LINKS_PER_USER}개까지 만들 수 있어요. 안 쓰는 링크를 지워 주세요.")
		except ValueError as exc:
			messages.error(request, str(exc))
			return redirect("tools:shortlink")
		days = LINK_TTL_DAYS.get(request.POST.get("ttl", ""), None)
		expires = timezone.now() + timedelta(days=days) if days else None
		for _ in range(5):
			try:
				link = ShortLink.objects.create(code=short_code(), target_url=target, owner=request.user, expires_at=expires)
				break
			except IntegrityError:
				continue
		else:
			messages.error(request, "잠시 뒤 다시 시도해 주세요.")
			return redirect("tools:shortlink")
		messages.success(request, _absolute(request, reverse("short_redirect", args=[link.code])))
		return redirect("tools:shortlink")

	now = timezone.now()
	rows = [{
		"obj": link,
		"short_url": _absolute(request, reverse("short_redirect", args=[link.code])),
		"expired": bool(link.expires_at and link.expires_at <= now),
	} for link in links[:MAX_LINKS_PER_USER]]
	return render(request, "tools/shortlink.html", {"rows": rows, "max_links": MAX_LINKS_PER_USER})


@login_required
@require_POST
def shortlink_delete(request, code):
	link = get_object_or_404(ShortLink, code=code)
	if link.owner_id != request.user.id and not request.user.is_superuser:
		raise Http404
	link.delete()
	messages.success(request, "단축 링크를 지웠어요.")
	return redirect("tools:shortlink")


def short_redirect(request, code):
	link = ShortLink.objects.filter(code=code).first()
	if not link or (link.expires_at and link.expires_at <= timezone.now()):
		return render(request, "tools/link_gone.html", {"what": "단축 링크"}, status=404)
	ShortLink.objects.filter(pk=link.pk).update(click_count=link.click_count + 1, last_clicked_at=timezone.now())
	return redirect(link.target_url)


# ── 1회용 비밀 메모 ─────────────────────────────

def _cleanup_notes():
	now = timezone.now()
	SecretNote.objects.filter(expires_at__lte=now - timedelta(days=7)).delete()  # 만료 1주 뒤 기록까지 정리
	SecretNote.objects.filter(expires_at__lte=now).exclude(ciphertext="").update(ciphertext="")


@login_required
def secret(request):
	_cleanup_notes()
	notes = SecretNote.objects.filter(created_by=request.user)[:50]
	return render(request, "tools/secret.html", {"notes": notes, "now": timezone.now()})


@login_required
@require_POST
def secret_create(request):
	try:
		data = json.loads(request.body or b"{}")
	except ValueError:
		return JsonResponse({"error": "요청 형식이 올바르지 않아요."}, status=400)
	ciphertext = (data.get("ciphertext") or "").strip()
	if not ciphertext:
		return JsonResponse({"error": "내용이 비어 있어요."}, status=400)
	if len(ciphertext) > MAX_NOTE_CHARS:
		return JsonResponse({"error": "메모가 너무 길어요. (약 1만 4천 자까지)"}, status=400)
	active = SecretNote.objects.filter(created_by=request.user, opened_at__isnull=True, expires_at__gt=timezone.now()).count()
	if active >= MAX_ACTIVE_NOTES:
		return JsonResponse({"error": f"아직 안 열린 메모는 {MAX_ACTIVE_NOTES}개까지 둘 수 있어요."}, status=400)
	hours = NOTE_TTL_HOURS.get(str(data.get("ttl")), 24)
	note = SecretNote.objects.create(
		ciphertext=ciphertext,
		label=(data.get("label") or "").strip()[:60],
		created_by=request.user,
		expires_at=timezone.now() + timedelta(hours=hours),
	)
	return JsonResponse({"url": _absolute(request, reverse("tools:secret_view", args=[note.note_id])), "expires_at": note.expires_at.isoformat()})


@login_required
@require_POST
def secret_delete(request, note_id):
	note = get_object_or_404(SecretNote, note_id=note_id, created_by=request.user)
	note.delete()
	messages.success(request, "메모를 지웠어요.")
	return redirect("tools:secret")


def _note_state(note):
	if not note:
		return "gone"
	if note.opened_at:
		return "opened"
	if note.expires_at <= timezone.now() or not note.ciphertext:
		return "expired"
	return "ready"


def secret_view(request, note_id):
	"""받는 사람 화면. 링크 미리보기(카톡 등)가 먼저 열어 버리지 않도록 '열기' 버튼을 눌러야 내용을 받음."""
	note = SecretNote.objects.filter(note_id=note_id).first()
	return render(request, "tools/secret_view.html", {"note_id": note_id, "state": _note_state(note), "note": note})


@require_POST
def secret_reveal(request, note_id):
	with transaction.atomic():
		note = SecretNote.objects.select_for_update().filter(note_id=note_id).first()
		state = _note_state(note)
		if state != "ready":
			return JsonResponse({"error": {
				"opened": "이미 열어 본 메모예요. 한 번만 볼 수 있어요.",
				"expired": "유효 시간이 지나 사라진 메모예요.",
			}.get(state, "없는 메모예요.")}, status=410)
		ciphertext = note.ciphertext
		note.ciphertext = ""
		note.opened_at = timezone.now()
		note.save(update_fields=["ciphertext", "opened_at"])
	return JsonResponse({"ciphertext": ciphertext})
