from pathlib import Path
from uuid import uuid4

from django.contrib import messages
from django.core.files.base import ContentFile
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.text import get_valid_filename

from studio.models import Certification

from .common import admin_view, apply_reorder, get_next_order, parse_month_input, parse_reorder_payload


def build_safe_certification_upload_name(original_name, folder="certification", stem_limit=60):
    original = Path(original_name or "file")
    ext = original.suffix.lower() or ""
    raw_stem = original.stem or "file"
    safe_stem = get_valid_filename(raw_stem).replace(" ", "_")
    if not safe_stem:
        safe_stem = "file"
    safe_stem = safe_stem[:stem_limit]
    return f"{folder}/{safe_stem}-{uuid4().hex[:10]}{ext}"


def sync_certification_preview_image(cert_item, regenerate=False):
    attachment = cert_item.attachment
    has_pdf = bool(attachment and Path(attachment.name).suffix.lower() == ".pdf")

    if not has_pdf:
        if cert_item.preview_image:
            cert_item.preview_image.delete(save=False)
            cert_item.preview_image = None
        return

    if not regenerate and cert_item.preview_image:
        return

    try:
        import fitz
    except ImportError as exc:
        raise RuntimeError("PyMuPDF 패키지가 필요합니다. (pip install pymupdf)") from exc

    attachment.open("rb")
    try:
        pdf_bytes = attachment.read()
    finally:
        attachment.close()

    try:
        with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
            if doc.page_count < 1:
                raise RuntimeError("PDF 페이지를 찾을 수 없습니다.")
            page = doc.load_page(0)
            pixmap = page.get_pixmap(matrix=fitz.Matrix(1.6, 1.6), alpha=False)
            preview_bytes = pixmap.tobytes("png")
    except Exception as exc:
        raise RuntimeError(f"PDF 미리보기 생성 실패: {exc}") from exc

    if cert_item.preview_image:
        cert_item.preview_image.delete(save=False)

    preview_name = build_safe_certification_upload_name(
        Path(attachment.name).name,
        folder="certification/previews",
        stem_limit=50,
    )
    preview_name = Path(preview_name).with_suffix(".png").as_posix()
    cert_item.preview_image.save(preview_name, ContentFile(preview_bytes), save=False)


@admin_view
def certification(request):
    certifications = Certification.objects.all()

    editing_id_raw = request.GET.get("edit", "").strip()
    editing_id = int(editing_id_raw) if editing_id_raw.isdigit() else None
    editing_certification = Certification.objects.filter(id=editing_id).first() if editing_id else None

    return render(
        request,
        "studio/certification.html",
        {
            "certifications": certifications,
            "editing_certification": editing_certification,
            "editing_certification_id": editing_id,
        },
    )


@admin_view
def certification_create(request):
    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        issuer = request.POST.get("issuer", "").strip()
        score = request.POST.get("score", "").strip()
        acquired_date = parse_month_input(request.POST.get("acquired_date", "").strip())
        expiration_date = parse_month_input(request.POST.get("expiration_date", "").strip())
        url = request.POST.get("url", "").strip()
        description = request.POST.get("description", "").strip()
        is_visible = request.POST.get("is_visible") == "true"
        order = get_next_order(Certification)
        attachment = request.FILES.get("attachment")
        if attachment:
            attachment.name = build_safe_certification_upload_name(attachment.name, folder="certification")

        if not name:
            messages.error(request, "자격증명은 필수입니다.")
            return redirect("studio:certification")

        if acquired_date and expiration_date and expiration_date < acquired_date:
            messages.error(request, "만료일은 취득일보다 빠를 수 없습니다.")
            return redirect("studio:certification")

        cert = Certification.objects.create(
            name=name,
            issuer=issuer,
            score=score,
            acquired_date=acquired_date,
            expiration_date=expiration_date,
            credential_id="",
            url=url,
            description=description,
            attachment=attachment,
            is_visible=is_visible,
            order=order,
        )

        if attachment:
            try:
                sync_certification_preview_image(cert, regenerate=True)
                cert.save(update_fields=["preview_image", "updated_at"])
            except RuntimeError as exc:
                messages.warning(request, str(exc))

        messages.success(request, "자격증이 추가되었습니다.")

    return redirect("studio:certification")


@admin_view
def certification_update(request, id):
    certification_item = get_object_or_404(Certification, id=id)

    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        issuer = request.POST.get("issuer", "").strip()
        score = request.POST.get("score", "").strip()
        acquired_date = parse_month_input(request.POST.get("acquired_date", "").strip())
        expiration_date = parse_month_input(request.POST.get("expiration_date", "").strip())
        url = request.POST.get("url", "").strip()
        description = request.POST.get("description", "").strip()
        is_visible = request.POST.get("is_visible") == "true"
        attachment = request.FILES.get("attachment")
        if attachment:
            attachment.name = build_safe_certification_upload_name(attachment.name, folder="certification")
        remove_attachment = request.POST.get("remove_attachment") == "true"
        should_sync_preview = False

        if not name:
            messages.error(request, "자격증명은 필수입니다.")
            return redirect(f"{reverse('studio:certification')}?edit={id}#certification-{id}")

        if acquired_date and expiration_date and expiration_date < acquired_date:
            messages.error(request, "만료일은 취득일보다 빠를 수 없습니다.")
            return redirect(f"{reverse('studio:certification')}?edit={id}#certification-{id}")

        certification_item.name = name
        certification_item.issuer = issuer
        certification_item.score = score
        certification_item.acquired_date = acquired_date
        certification_item.expiration_date = expiration_date
        certification_item.credential_id = ""
        certification_item.url = url
        certification_item.description = description
        certification_item.is_visible = is_visible

        if remove_attachment and certification_item.attachment:
            certification_item.attachment.delete(save=False)
            certification_item.attachment = None
            if certification_item.preview_image:
                certification_item.preview_image.delete(save=False)
                certification_item.preview_image = None

        if attachment:
            if certification_item.attachment:
                certification_item.attachment.delete(save=False)
            certification_item.attachment = attachment
            should_sync_preview = True

        certification_item.save()

        if should_sync_preview:
            try:
                sync_certification_preview_image(certification_item, regenerate=True)
                certification_item.save(update_fields=["preview_image", "updated_at"])
            except RuntimeError as exc:
                messages.warning(request, str(exc))

        messages.success(request, "자격증이 수정되었습니다.")

    return redirect(f"{reverse('studio:certification')}#certification-{id}")


@admin_view
def certification_delete(request, id):
    certification_item = get_object_or_404(Certification, id=id)

    if request.method == "POST":
        if certification_item.attachment:
            certification_item.attachment.delete(save=False)
        if certification_item.preview_image:
            certification_item.preview_image.delete(save=False)
        certification_item.delete()
        messages.success(request, "자격증이 삭제되었습니다.")

    return redirect("studio:certification")


@admin_view
def certification_toggle_visibility(request, id):
    certification_item = get_object_or_404(Certification, id=id)

    if request.method == "POST":
        certification_item.is_visible = request.POST.get("is_visible") == "true"
        certification_item.save()
        messages.success(request, "공개 여부가 변경되었습니다.")

    return redirect("studio:certification")


@admin_view
def certification_reorder(request):
    if request.method != "POST":
        return JsonResponse({"ok": False}, status=405)

    ordered_ids, error = parse_reorder_payload(request)
    if error:
        return error

    if not apply_reorder(Certification, ordered_ids):
        return JsonResponse({"ok": False, "message": "정렬 저장에 실패했습니다."}, status=400)

    return JsonResponse({"ok": True})
