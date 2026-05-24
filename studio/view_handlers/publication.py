from pathlib import Path
from uuid import uuid4

from django.contrib import messages
from django.core.files.base import ContentFile
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.text import get_valid_filename

from studio.models import Publication

from .common import admin_view, apply_reorder, get_next_order, parse_month_input, parse_reorder_payload


def build_safe_publication_upload_name(original_name, folder="publication", forced_ext=None, stem_limit=60):
    original = Path(original_name or "file")
    ext = (forced_ext or original.suffix or "").lower()
    raw_stem = original.stem or "file"
    safe_stem = get_valid_filename(raw_stem).replace(" ", "_")
    if not safe_stem:
        safe_stem = "file"
    safe_stem = safe_stem[:stem_limit]
    return f"{folder}/{safe_stem}-{uuid4().hex[:10]}{ext}"


def sync_publication_preview_image(publication_item, regenerate=False):
    attachment = publication_item.attachment
    has_pdf = bool(attachment and Path(attachment.name).suffix.lower() == ".pdf")

    if not has_pdf:
        if publication_item.preview_image:
            publication_item.preview_image.delete(save=False)
            publication_item.preview_image = None
        return

    if not regenerate and publication_item.preview_image:
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

    if publication_item.preview_image:
        publication_item.preview_image.delete(save=False)

    preview_name = build_safe_publication_upload_name(
        Path(attachment.name).name,
        folder="publication/previews",
        forced_ext=".png",
        stem_limit=50,
    )
    publication_item.preview_image.save(preview_name, ContentFile(preview_bytes), save=False)


@admin_view
def publication(request):
    publications = Publication.objects.all()
    editing_publication_id = request.GET.get("edit", "").strip()
    editing_publication_id = int(editing_publication_id) if editing_publication_id.isdigit() else None
    editing_publication = Publication.objects.filter(id=editing_publication_id).first() if editing_publication_id else None

    publication_types = [
        ("international", "국제지/국제학회"),
        ("domestic", "국내지/국내학회"),
    ]
    publication_kinds = [
        ("journal", "저널"),
        ("conference", "학술지"),
    ]

    return render(
        request,
        "studio/publication.html",
        {
            "publications": publications,
            "publication_types": publication_types,
            "publication_kinds": publication_kinds,
            "editing_publication_id": editing_publication_id,
            "editing_publication": editing_publication,
        },
    )


@admin_view
def publication_create(request):
    if request.method == "POST":
        publication_type = request.POST.get("publication_type", "international").strip() or "international"
        publication_kind = request.POST.get("publication_kind", "journal").strip() or "journal"
        title = request.POST.get("title", "").strip()
        venue = request.POST.get("venue", "").strip()
        authors = request.POST.get("authors", "").strip()
        date = parse_month_input(request.POST.get("date", "").strip())
        doi = request.POST.get("doi", "").strip()
        url = request.POST.get("url", "").strip()
        abstract = request.POST.get("abstract", "").strip()
        attachment = request.FILES.get("attachment")
        if attachment:
            attachment.name = build_safe_publication_upload_name(attachment.name, folder="publication", stem_limit=70)
        is_visible = request.POST.get("is_visible") == "true"
        order = get_next_order(Publication)

        if not title:
            messages.error(request, "제목은 필수입니다.")
            return redirect("studio:publication")

        publication_item = Publication.objects.create(
            publication_type=publication_type,
            publication_kind=publication_kind,
            title=title,
            venue=venue,
            authors=authors,
            date=date,
            doi=doi,
            url=url,
            abstract=abstract,
            attachment=attachment,
            is_visible=is_visible,
            order=order,
        )

        if attachment:
            try:
                sync_publication_preview_image(publication_item, regenerate=True)
                publication_item.save(update_fields=["preview_image", "updated_at"])
            except RuntimeError as exc:
                messages.warning(request, str(exc))

        messages.success(request, "출판물이 추가되었습니다.")

    return redirect("studio:publication")


@admin_view
def publication_update(request, id):
    publication_item = get_object_or_404(Publication, id=id)

    if request.method == "POST":
        publication_type = request.POST.get("publication_type", "international").strip() or "international"
        publication_kind = request.POST.get("publication_kind", "journal").strip() or "journal"
        title = request.POST.get("title", "").strip()
        venue = request.POST.get("venue", "").strip()
        authors = request.POST.get("authors", "").strip()
        date = parse_month_input(request.POST.get("date", "").strip())
        doi = request.POST.get("doi", "").strip()
        url = request.POST.get("url", "").strip()
        abstract = request.POST.get("abstract", "").strip()
        attachment = request.FILES.get("attachment")
        if attachment:
            attachment.name = build_safe_publication_upload_name(attachment.name, folder="publication", stem_limit=70)
        remove_attachment = request.POST.get("remove_attachment") == "true"
        is_visible = request.POST.get("is_visible") == "true"
        should_sync_preview = False

        if not title:
            messages.error(request, "제목은 필수입니다.")
            return redirect(f"{reverse('studio:publication')}?edit={id}#publication-{id}")

        publication_item.publication_type = publication_type
        publication_item.publication_kind = publication_kind
        publication_item.title = title
        publication_item.venue = venue
        publication_item.authors = authors
        publication_item.date = date
        publication_item.doi = doi
        publication_item.url = url
        publication_item.abstract = abstract

        if remove_attachment and publication_item.attachment:
            publication_item.attachment.delete(save=False)
            publication_item.attachment = None
            if publication_item.preview_image:
                publication_item.preview_image.delete(save=False)
                publication_item.preview_image = None

        if attachment:
            if publication_item.attachment:
                publication_item.attachment.delete(save=False)
            publication_item.attachment = attachment
            should_sync_preview = True
        elif remove_attachment:
            publication_item.preview_image = None

        publication_item.is_visible = is_visible
        publication_item.save()

        if should_sync_preview:
            try:
                sync_publication_preview_image(publication_item, regenerate=True)
                publication_item.save(update_fields=["preview_image", "updated_at"])
            except RuntimeError as exc:
                if publication_item.preview_image:
                    publication_item.preview_image.delete(save=False)
                    publication_item.preview_image = None
                    publication_item.save(update_fields=["preview_image", "updated_at"])
                messages.warning(request, str(exc))

        messages.success(request, "수정 완료되었습니다.")

    return redirect(f"{reverse('studio:publication')}#publication-{id}")


@admin_view
def publication_delete(request, id):
    publication_item = get_object_or_404(Publication, id=id)

    if request.method == "POST":
        if publication_item.attachment:
            publication_item.attachment.delete(save=False)
        if publication_item.preview_image:
            publication_item.preview_image.delete(save=False)
        publication_item.delete()
        messages.success(request, "출판물이 삭제되었습니다.")

    return redirect("studio:publication")


@admin_view
def publication_toggle_visibility(request, id):
    publication_item = get_object_or_404(Publication, id=id)

    if request.method == "POST":
        publication_item.is_visible = request.POST.get("is_visible") == "true"
        publication_item.save()
        messages.success(request, "공개 여부가 변경되었습니다.")

    return redirect("studio:publication")


@admin_view
def publication_reorder(request):
    if request.method != "POST":
        return JsonResponse({"ok": False}, status=405)

    ordered_ids, error = parse_reorder_payload(request)
    if error:
        return error

    if not apply_reorder(Publication, ordered_ids):
        return JsonResponse({"ok": False, "message": "정렬 저장에 실패했습니다."}, status=400)

    return JsonResponse({"ok": True})
