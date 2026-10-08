"""계정별 클립보드: 한 기기에서 저장한 텍스트·이미지·파일을 다른 기기에서 복사/다운로드."""

import hashlib

from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from .models import ClipItem

MAX_TEXT_CHARS = 100_000
MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_USER_BYTES = 200 * 1024 * 1024
MAX_USER_ITEMS = 200
IMAGE_MIMES = {"image/png", "image/jpeg", "image/gif", "image/webp", "image/bmp"}


def _serialize(item):
	data = {
		"id": item.id,
		"kind": item.kind,
		"pinned": item.pinned,
		"created_at": timezone.localtime(item.created_at).isoformat(),
		"size": item.size,
	}
	if item.kind == ClipItem.KIND_TEXT:
		data["text"] = item.text
	else:
		data.update(
			filename=item.filename,
			mime=item.mime,
			url=reverse("tools:clipboard_file", args=[item.id]),
		)
	return data


def _items(user):
	return list(ClipItem.objects.filter(user=user))


def _version(items):
	"""목록이 바뀌었는지 비교하는 짧은 값 (항목 id·고정 여부가 같으면 같음)."""
	raw = ",".join(f"{i.id}:{int(i.pinned)}" for i in items)
	return hashlib.sha1(raw.encode()).hexdigest()[:16]


def _usage(user):
	qs = ClipItem.objects.filter(user=user)
	return qs.count(), qs.aggregate(total=Sum("size"))["total"] or 0


def _error(message, status=400):
	return JsonResponse({"error": message}, status=status)


@login_required
def clipboard_page(request):
	return render(request, "tools/clipboard.html", {
		"max_file_mb": MAX_FILE_BYTES // (1024 * 1024),
		"max_user_mb": MAX_USER_BYTES // (1024 * 1024),
	})


@login_required
@require_GET
def clipboard_list(request):
	items = _items(request.user)
	version = _version(items)
	if request.GET.get("since") == version:
		return JsonResponse({"unchanged": True, "version": version})
	count, total = _usage(request.user)
	return JsonResponse({
		"version": version,
		"items": [_serialize(i) for i in items],
		"usage": {"count": count, "bytes": total, "max_count": MAX_USER_ITEMS, "max_bytes": MAX_USER_BYTES},
	})


@login_required
@require_POST
def clipboard_add(request):
	count, total = _usage(request.user)
	if count >= MAX_USER_ITEMS:
		return _error(f"클립보드는 최대 {MAX_USER_ITEMS}개까지 저장할 수 있어요. 오래된 항목을 지워 주세요.")

	upload = request.FILES.get("file")
	if upload:
		if upload.size > MAX_FILE_BYTES:
			return _error(f"파일·이미지는 {MAX_FILE_BYTES // (1024 * 1024)}MB 까지 저장할 수 있어요.")
		if total + upload.size > MAX_USER_BYTES:
			return _error(f"계정 용량({MAX_USER_BYTES // (1024 * 1024)}MB)을 넘어요. 오래된 항목을 지워 주세요.")
		mime = (upload.content_type or "application/octet-stream")[:120]
		item = ClipItem(
			user=request.user,
			kind=ClipItem.KIND_IMAGE if mime in IMAGE_MIMES else ClipItem.KIND_FILE,
			filename=(upload.name or "clipboard")[:255],
			mime=mime,
			size=upload.size,
		)
		item.file.save("upload", upload, save=False)
		item.save()
		return JsonResponse({"item": _serialize(item)}, status=201)

	text = request.POST.get("text", "")
	if not text.strip():
		return _error("저장할 내용이 없어요.")
	if len(text) > MAX_TEXT_CHARS:
		return _error(f"텍스트는 {MAX_TEXT_CHARS:,}자까지 저장할 수 있어요.")
	size = len(text.encode("utf-8"))
	if total + size > MAX_USER_BYTES:
		return _error("계정 용량을 넘어요. 오래된 항목을 지워 주세요.")
	item = ClipItem.objects.create(user=request.user, kind=ClipItem.KIND_TEXT, text=text, size=size)
	return JsonResponse({"item": _serialize(item)}, status=201)


@login_required
@require_POST
def clipboard_pin(request, item_id):
	item = get_object_or_404(ClipItem, pk=item_id, user=request.user)
	item.pinned = not item.pinned
	item.save(update_fields=["pinned"])
	return JsonResponse({"item": _serialize(item)})


@login_required
@require_POST
def clipboard_delete(request, item_id):
	get_object_or_404(ClipItem, pk=item_id, user=request.user).delete()
	return JsonResponse({"deleted": item_id})


@login_required
@require_POST
def clipboard_clear(request):
	"""고정하지 않은 항목 전부 삭제 (파일도 함께 지우려고 하나씩 delete)."""
	deleted = 0
	for item in ClipItem.objects.filter(user=request.user, pinned=False):
		item.delete()
		deleted += 1
	return JsonResponse({"deleted": deleted})


@login_required
@require_GET
def clipboard_file(request, item_id):
	"""본인 항목의 이미지·파일만 내려줌. ?inline=1 이면 브라우저에서 바로 표시(이미지 미리보기)."""
	item = get_object_or_404(ClipItem, pk=item_id, user=request.user)
	if not item.file:
		raise Http404
	inline = request.GET.get("inline") == "1" and item.kind == ClipItem.KIND_IMAGE
	response = FileResponse(item.file.open("rb"), as_attachment=not inline, filename=item.filename or "clipboard", content_type=item.mime or None)
	response["Cache-Control"] = "private, max-age=3600"
	response["X-Content-Type-Options"] = "nosniff"
	return response
