"""맡겨두기: 파일을 서버에 잠시 올려두고 링크로 내려받기.

nginx 요청 크기 제한(100MB)을 넘는 큰 파일도 올릴 수 있도록 브라우저가 20MB 조각으로 나눠 보내고,
서버는 offset 이 맞는 조각만 이어붙인다. 다운로드 권한은 링크(토큰) 자체.
"""

import hashlib
import json
from datetime import timedelta

from django.core.files.base import ContentFile
from django.db.models import Sum
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from .models import SharedFile
from .permissions import can_manage_streams

GB = 1024 ** 3
MAX_FILE_BYTES = 2 * GB
MAX_TOTAL_BYTES = 10 * GB
CHUNK_BYTES = 20 * 1024 * 1024
EXPIRY_HOURS = (1, 6, 24, 72, 168)
DEFAULT_HOURS = 24
INCOMPLETE_TTL = timedelta(hours=6)


def cleanup_expired():
	"""만료됐거나 오래 멈춘 미완성 업로드 삭제 (파일도 함께). 지운 개수를 돌려줌."""
	now = timezone.now()
	stale = list(SharedFile.objects.filter(expires_at__lte=now)) + list(
		SharedFile.objects.filter(completed=False, created_at__lte=now - INCOMPLETE_TTL)
	)
	for item in {s.pk: s for s in stale}.values():
		item.delete()
	return len(stale)


def _get_active(token):
	item = get_object_or_404(SharedFile, token=token)
	if item.expires_at <= timezone.now():
		item.delete()
		raise Http404("만료된 링크입니다.")
	return item


def _json_error(message, status=400):
	return JsonResponse({"error": message}, status=status)


def _require_admin(request):
	if not request.user.is_authenticated:
		return redirect(f"{reverse('accounts:login')}?next={request.get_full_path()}")
	if not can_manage_streams(request.user):
		raise Http404
	return None


def share_page(request):
	"""맡겨두기 업로드 화면 + 내가 올린 파일 목록 (관리자)."""
	denied = _require_admin(request)
	if denied:
		return denied
	cleanup_expired()
	files = SharedFile.objects.filter(created_by=request.user)
	return render(request, "tools/share_upload.html", {
		"files": files,
		"expiry_hours": EXPIRY_HOURS,
		"default_hours": DEFAULT_HOURS,
		"max_gb": MAX_FILE_BYTES // GB,
	})


@require_POST
def share_create(request):
	if not can_manage_streams(request.user):
		return _json_error("권한이 없습니다.", 403)
	cleanup_expired()
	try:
		data = json.loads(request.body or b"{}")
		size = int(data.get("size", 0))
		hours = int(data.get("hours", DEFAULT_HOURS))
	except (ValueError, TypeError, json.JSONDecodeError):
		return _json_error("요청 형식이 올바르지 않습니다.")
	name = str(data.get("name") or "file").replace("/", "_").replace("\\", "_")[:255]
	if size <= 0:
		return _json_error("빈 파일은 맡길 수 없어요.")
	if size > MAX_FILE_BYTES:
		return _json_error(f"파일은 {MAX_FILE_BYTES // GB}GB 까지 맡길 수 있어요.")
	used = SharedFile.objects.aggregate(total=Sum("size"))["total"] or 0
	if used + size > MAX_TOTAL_BYTES:
		return _json_error("서버의 맡겨두기 공간이 부족해요. 기존 파일을 지우고 다시 시도해 주세요.", 507)
	if hours not in EXPIRY_HOURS:
		hours = DEFAULT_HOURS
	item = SharedFile.objects.create(
		name=name,
		mime=str(data.get("mime") or "")[:120],
		size=size,
		created_by=request.user,
		expires_at=timezone.now() + timedelta(hours=hours),
	)
	item.file.save("upload", ContentFile(b""), save=True)  # 조각을 이어붙일 빈 파일
	return JsonResponse({
		"token": item.token,
		"chunk_size": CHUNK_BYTES,
		"chunk_url": reverse("tools:share_chunk", args=[item.token]),
		"complete_url": reverse("tools:share_complete", args=[item.token]),
		"share_url": request.build_absolute_uri(reverse("tools:share_download_page", args=[item.token])),
	}, status=201)


@require_POST
def share_chunk(request, token):
	"""offset 위치에 조각을 이어붙임. offset 이 현재 받은 크기와 다르면 거절 (재시도 시 안전)."""
	item = _get_active(token)
	if item.created_by_id != getattr(request.user, "id", None):
		return _json_error("권한이 없습니다.", 403)
	if item.completed:
		return _json_error("이미 완료된 업로드입니다.", 409)
	try:
		offset = int(request.GET.get("offset", "-1"))
		length = int(request.META.get("CONTENT_LENGTH") or 0)
	except ValueError:
		return _json_error("offset 이 올바르지 않습니다.")
	if offset != item.received:
		return JsonResponse({"error": "offset 이 맞지 않습니다.", "received": item.received}, status=409)
	if length <= 0 or length > CHUNK_BYTES or item.received + length > item.size:
		return _json_error("조각 크기가 올바르지 않습니다.")

	written = 0
	with item.file.storage.open(item.file.name, "ab") as fh:
		while True:
			piece = request.read(1024 * 1024)
			if not piece:
				break
			fh.write(piece)
			written += len(piece)
	item.received += written
	item.save(update_fields=["received"])
	return JsonResponse({"received": item.received})


@require_POST
def share_complete(request, token):
	item = _get_active(token)
	if item.created_by_id != getattr(request.user, "id", None):
		return _json_error("권한이 없습니다.", 403)
	if item.received != item.size:
		return _json_error(f"아직 다 올라가지 않았어요 ({item.received}/{item.size}).", 409)
	digest = hashlib.sha256()
	with item.file.open("rb") as fh:
		for block in iter(lambda: fh.read(4 * 1024 * 1024), b""):
			digest.update(block)
	item.sha256 = digest.hexdigest()
	item.completed = True
	item.save(update_fields=["sha256", "completed"])
	return JsonResponse({"sha256": item.sha256, "share_url": request.build_absolute_uri(reverse("tools:share_download_page", args=[item.token]))})


@require_POST
def share_delete(request, token):
	item = get_object_or_404(SharedFile, token=token)
	if item.created_by_id != getattr(request.user, "id", None) and not can_manage_streams(request.user):
		raise Http404
	item.delete()
	return redirect("tools:share")


@require_GET
def share_download_page(request, token):
	item = _get_active(token)
	if not item.completed:
		raise Http404("아직 업로드 중인 파일입니다.")
	return render(request, "tools/share_download.html", {"item": item})


@require_GET
def share_download(request, token):
	item = _get_active(token)
	if not item.completed:
		raise Http404
	SharedFile.objects.filter(pk=item.pk).update(download_count=item.download_count + 1)
	response = FileResponse(item.file.open("rb"), as_attachment=True, filename=item.name, content_type=item.mime or "application/octet-stream")
	response["X-Content-Type-Options"] = "nosniff"
	return response
