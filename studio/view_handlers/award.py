from pathlib import Path
from uuid import uuid4

from django.contrib import messages
from django.core.files.base import ContentFile
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.text import get_valid_filename

from studio.models import Award

from .common import admin_view, apply_reorder, get_next_order, parse_reorder_payload


def build_safe_award_upload_name(original_name, folder="award", forced_ext=None, stem_limit=60):
    original = Path(original_name or "file")
    ext = (forced_ext or original.suffix or "").lower()
    raw_stem = original.stem or "file"
    safe_stem = get_valid_filename(raw_stem).replace(" ", "_")
    if not safe_stem:
        safe_stem = "file"
    safe_stem = safe_stem[:stem_limit]
    return f"{folder}/{safe_stem}-{uuid4().hex[:10]}{ext}"


def sync_award_preview_image(award_item, regenerate=False):
    attachment = award_item.attachment
    has_pdf = bool(attachment and Path(attachment.name).suffix.lower() == ".pdf")

    if not has_pdf:
        if award_item.preview_image:
            award_item.preview_image.delete(save=False)
            award_item.preview_image = None
        return

    if not regenerate and award_item.preview_image:
        return

    try:
        import fitz  # PyMuPDF
    except ImportError as exc:
        raise RuntimeError("PyMuPDF 패키지가 필요합니다. (pip install pymupdf)") from exc

    attachment.open("rb")
    try:
        pdf_bytes = attachment.read()
    finally:
        attachment.close()

    try:
        with fitz.open(stream=pdf_bytes, filetype="pdf") as document:
            if document.page_count < 1:
                raise RuntimeError("PDF 페이지를 찾을 수 없습니다.")

            page = document.load_page(0)
            pixmap = page.get_pixmap(matrix=fitz.Matrix(1.6, 1.6), alpha=False)
            preview_bytes = pixmap.tobytes("png")
    except Exception as exc:
        raise RuntimeError(f"PDF 미리보기 생성 실패: {exc}") from exc

    if award_item.preview_image:
        award_item.preview_image.delete(save=False)

    preview_name = build_safe_award_upload_name(
        Path(attachment.name).name,
        folder="award/previews",
        forced_ext=".png",
        stem_limit=50,
    )
    award_item.preview_image.save(preview_name, ContentFile(preview_bytes), save=False)


@admin_view
def award(request):
    awards = Award.objects.all()
    editing_award_id = request.GET.get("edit", "").strip()
    editing_award_id = int(editing_award_id) if editing_award_id.isdigit() else None
    editing_award = Award.objects.filter(id=editing_award_id).first() if editing_award_id else None

    return render(
        request,
        "studio/award.html",
        {
            "awards": awards,
            "editing_award_id": editing_award_id,
            "editing_award": editing_award,
        },
    )


@admin_view
def award_create(request):
    if request.method == "POST":
        title = request.POST.get("title", "").strip()
        organizer = request.POST.get("organizer", "").strip()
        award_name = request.POST.get("award_name", "").strip()
        date_str = request.POST.get("date", "").strip()
        date = None
        if date_str:
            try:
                from datetime import datetime
                date = datetime.strptime(date_str, "%Y-%m").date().replace(day=1)
            except ValueError:
                pass
        description = request.POST.get("description", "").strip()
        url = request.POST.get("url", "").strip()
        attachment = request.FILES.get("attachment")
        if attachment:
            attachment.name = build_safe_award_upload_name(attachment.name, folder="award", stem_limit=70)
        is_visible = request.POST.get("is_visible") == "true"
        order = get_next_order(Award)

        if not title:
            messages.error(request, "수상명은 필수입니다.")
            return redirect("studio:award")

        award_item = Award.objects.create(
            title=title,
            organizer=organizer,
            award_name=award_name,
            date=date,
            description=description,
            url=url,
            attachment=attachment,
            is_visible=is_visible,
            order=order,
        )

        if attachment:
            try:
                sync_award_preview_image(award_item, regenerate=True)
                award_item.save(update_fields=["preview_image", "updated_at"])
            except RuntimeError as exc:
                messages.warning(request, str(exc))

        messages.success(request, "수상 이력이 추가되었습니다.")

    return redirect("studio:award")


@admin_view
def award_update(request, id):
    award_item = get_object_or_404(Award, id=id)

    if request.method == "POST":
        title = request.POST.get("title", "").strip()
        organizer = request.POST.get("organizer", "").strip()
        award_name = request.POST.get("award_name", "").strip()
        date_str = request.POST.get("date", "").strip()
        date = None
        if date_str:
            try:
                from datetime import datetime
                date = datetime.strptime(date_str, "%Y-%m").date().replace(day=1)
            except ValueError:
                pass
        description = request.POST.get("description", "").strip()
        url = request.POST.get("url", "").strip()
        attachment = request.FILES.get("attachment")
        if attachment:
            attachment.name = build_safe_award_upload_name(attachment.name, folder="award", stem_limit=70)
        remove_attachment = request.POST.get("remove_attachment") == "true"
        is_visible = request.POST.get("is_visible") == "true"
        should_sync_preview = False

        if not title:
            messages.error(request, "수상명은 필수입니다.")
            return redirect(f"{reverse('studio:award')}?edit={id}#award-{id}")

        award_item.title = title
        award_item.organizer = organizer
        award_item.award_name = award_name
        award_item.date = date
        award_item.description = description
        award_item.url = url

        if remove_attachment and award_item.attachment:
            award_item.attachment.delete(save=False)
            award_item.attachment = None
            if award_item.preview_image:
                award_item.preview_image.delete(save=False)
                award_item.preview_image = None

        if attachment:
            if award_item.attachment:
                award_item.attachment.delete(save=False)
            award_item.attachment = attachment
            should_sync_preview = True
        elif remove_attachment:
            award_item.preview_image = None

        award_item.is_visible = is_visible
        award_item.save()

        if should_sync_preview:
            try:
                sync_award_preview_image(award_item, regenerate=True)
                award_item.save(update_fields=["preview_image", "updated_at"])
            except RuntimeError as exc:
                if award_item.preview_image:
                    award_item.preview_image.delete(save=False)
                    award_item.preview_image = None
                    award_item.save(update_fields=["preview_image", "updated_at"])
                messages.warning(request, str(exc))

        messages.success(request, "수정 완료되었습니다.")

    return redirect(f"{reverse('studio:award')}#award-{id}")


@admin_view
def award_delete(request, id):
    award_item = get_object_or_404(Award, id=id)

    if request.method == "POST":
        if award_item.attachment:
            award_item.attachment.delete(save=False)
        if award_item.preview_image:
            award_item.preview_image.delete(save=False)
        award_item.delete()
        messages.success(request, "수상 이력이 삭제되었습니다.")

    return redirect("studio:award")


@admin_view
def award_toggle_visibility(request, id):
    award_item = get_object_or_404(Award, id=id)

    if request.method == "POST":
        award_item.is_visible = request.POST.get("is_visible") == "true"
        award_item.save()
        messages.success(request, "공개 여부가 변경되었습니다.")

    return redirect("studio:award")


@admin_view
def award_reorder(request):
    if request.method != "POST":
        return JsonResponse({"ok": False}, status=405)

    ordered_ids, error = parse_reorder_payload(request)
    if error:
        return error

    if not apply_reorder(Award, ordered_ids):
        return JsonResponse({"ok": False, "message": "정렬 저장에 실패했습니다."}, status=400)

    return JsonResponse({"ok": True})
