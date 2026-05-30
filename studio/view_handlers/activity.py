from pathlib import Path
from uuid import uuid4

from django.contrib import messages
from django.core.files.base import ContentFile
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.text import get_valid_filename

from studio.models import Activity

from .common import admin_view, apply_reorder, get_next_order, parse_month_input, parse_reorder_payload


def build_safe_upload_name(original_name, folder="activity", forced_ext=None, stem_limit=60):
    original = Path(original_name or "file")
    ext = (forced_ext or original.suffix or "").lower()
    raw_stem = original.stem or "file"
    safe_stem = get_valid_filename(raw_stem).replace(" ", "_")
    if not safe_stem:
        safe_stem = "file"
    safe_stem = safe_stem[:stem_limit]
    return f"{folder}/{safe_stem}-{uuid4().hex[:10]}{ext}"


def sync_activity_preview_image(activity_item, regenerate=False):
    attachment = activity_item.attachment
    has_pdf = bool(attachment and Path(attachment.name).suffix.lower() == ".pdf")

    if not has_pdf:
        if activity_item.preview_image:
            activity_item.preview_image.delete(save=False)
            activity_item.preview_image = None
        return

    if not regenerate and activity_item.preview_image:
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

    if activity_item.preview_image:
        activity_item.preview_image.delete(save=False)

    preview_name = build_safe_upload_name(
        Path(attachment.name).name,
        folder="activity/previews",
        forced_ext=".png",
        stem_limit=50,
    )
    activity_item.preview_image.save(preview_name, ContentFile(preview_bytes), save=False)


@admin_view
def activity(request):
    activities = Activity.objects.all()
    editing_activity_id = request.GET.get("edit", "").strip()
    editing_activity_id = int(editing_activity_id) if editing_activity_id.isdigit() else None
    editing_activity = Activity.objects.filter(id=editing_activity_id).first() if editing_activity_id else None
    activity_types = [
        ("external_program", "대외활동 (External Program)"),
        ("seminar", "세미나 (Seminar)"),
        ("community", "커뮤니티 (Community)"),
        ("volunteer", "봉사 (Volunteer)"),
        ("challenge", "대회 (Challenge)"),
        ("other", "기타 (Other)"),
    ]
    section_icons = {
        "external_program": "🌍",
        "seminar": "🎤",
        "community": "🤝",
        "volunteer": "🌿",
        "challenge": "🏆",
        "other": "🗂",
    }
    activity_sections = [
        {
            "key": value,
            "title": label,
            "icon": section_icons[value],
            "items": activities.filter(activity_type=value),
            "count": activities.filter(activity_type=value).count(),
        }
        for value, label in activity_types
    ]

    return render(
        request,
        "studio/activity.html",
        {
            "activities": activities,
            "activity_types": activity_types,
            "activity_sections": activity_sections,
            "editing_activity_id": editing_activity_id,
            "editing_activity": editing_activity,
        },
    )


@admin_view
def activity_create(request):
    if request.method == "POST":
        activity_type = request.POST.get("activity_type", "external_program").strip() or "external_program"
        title = request.POST.get("title", "").strip()
        organization_name = request.POST.get("organization_name", "").strip()
        role = request.POST.get("role", "").strip()
        start_date = parse_month_input(request.POST.get("start_date", "").strip())
        is_current = request.POST.get("is_current") == "true"
        end_date = None if is_current else parse_month_input(request.POST.get("end_date", "").strip())
        description = request.POST.get("description", "").strip()
        url = request.POST.get("url", "").strip()
        attachment = request.FILES.get("attachment")
        if attachment:
            attachment.name = build_safe_upload_name(attachment.name, folder="activity", stem_limit=70)
        is_attachment_public = request.POST.get("is_attachment_public") in ("true", "on")
        is_visible = request.POST.get("is_visible") == "true"
        order = get_next_order(Activity)

        if not title:
            messages.error(request, "활동명은 필수입니다.")
            return redirect("studio:activity")

        if start_date and end_date and end_date < start_date:
            messages.error(request, "종료일은 시작일보다 빠를 수 없습니다.")
            return redirect("studio:activity")

        activity_item = Activity.objects.create(
            activity_type=activity_type,
            title=title,
            organization_name=organization_name,
            role=role,
            start_date=start_date,
            end_date=end_date,
            is_current=is_current,
            description=description,
            url=url,
            attachment=attachment,
            is_attachment_public=is_attachment_public,
            is_visible=is_visible,
            order=order,
        )

        if attachment:
            try:
                sync_activity_preview_image(activity_item, regenerate=True)
                activity_item.save(update_fields=["preview_image", "updated_at"])
            except RuntimeError as exc:
                messages.warning(request, str(exc))

        messages.success(request, "활동이 추가되었습니다.")

    return redirect("studio:activity")


@admin_view
def activity_update(request, id):
    activity_item = get_object_or_404(Activity, id=id)

    if request.method == "POST":
        activity_type = request.POST.get("activity_type", "external_program").strip() or "external_program"
        title = request.POST.get("title", "").strip()
        organization_name = request.POST.get("organization_name", "").strip()
        role = request.POST.get("role", "").strip()
        start_date = parse_month_input(request.POST.get("start_date", "").strip())
        is_current = request.POST.get("is_current") == "true"
        end_date = None if is_current else parse_month_input(request.POST.get("end_date", "").strip())
        description = request.POST.get("description", "").strip()
        url = request.POST.get("url", "").strip()
        attachment = request.FILES.get("attachment")
        if attachment:
            attachment.name = build_safe_upload_name(attachment.name, folder="activity", stem_limit=70)
        remove_attachment = request.POST.get("remove_attachment") == "true"
        is_attachment_public = request.POST.get("is_attachment_public") in ("true", "on")
        is_visible = request.POST.get("is_visible") == "true"
        should_sync_preview = False

        if not title:
            messages.error(request, "활동명은 필수입니다.")
            return redirect(f"{reverse('studio:activity')}?edit={id}#activity-{id}")

        if start_date and end_date and end_date < start_date:
            messages.error(request, "종료일은 시작일보다 빠를 수 없습니다.")
            return redirect(f"{reverse('studio:activity')}?edit={id}#activity-{id}")

        activity_item.activity_type = activity_type
        activity_item.title = title
        activity_item.organization_name = organization_name
        activity_item.role = role
        activity_item.start_date = start_date
        activity_item.end_date = end_date
        activity_item.is_current = is_current
        activity_item.description = description
        activity_item.url = url
        activity_item.is_attachment_public = is_attachment_public

        if remove_attachment and activity_item.attachment:
            activity_item.attachment.delete(save=False)
            activity_item.attachment = None
            if activity_item.preview_image:
                activity_item.preview_image.delete(save=False)
                activity_item.preview_image = None

        if attachment:
            if activity_item.attachment:
                activity_item.attachment.delete(save=False)
            activity_item.attachment = attachment
            should_sync_preview = True
        elif remove_attachment:
            activity_item.preview_image = None

        activity_item.is_visible = is_visible
        activity_item.save()

        if should_sync_preview:
            try:
                sync_activity_preview_image(activity_item, regenerate=True)
                activity_item.save(update_fields=["preview_image", "updated_at"])
            except RuntimeError as exc:
                if activity_item.preview_image:
                    activity_item.preview_image.delete(save=False)
                    activity_item.preview_image = None
                    activity_item.save(update_fields=["preview_image", "updated_at"])
                messages.warning(request, str(exc))

        messages.success(request, "수정 완료되었습니다.")

    return redirect(f"{reverse('studio:activity')}#activity-{id}")


@admin_view
def activity_delete(request, id):
    activity_item = get_object_or_404(Activity, id=id)

    if request.method == "POST":
        if activity_item.attachment:
            activity_item.attachment.delete(save=False)
        if activity_item.preview_image:
            activity_item.preview_image.delete(save=False)
        activity_item.delete()
        messages.success(request, "활동이 삭제되었습니다.")

    return redirect("studio:activity")


@admin_view
def activity_toggle_visibility(request, id):
    activity_item = get_object_or_404(Activity, id=id)

    if request.method == "POST":
        activity_item.is_visible = request.POST.get("is_visible") == "true"
        activity_item.save()
        messages.success(request, "공개 여부가 변경되었습니다.")

    return redirect("studio:activity")


@admin_view
def activity_reorder(request):
    if request.method != "POST":
        return JsonResponse({"ok": False}, status=405)

    ordered_ids, error = parse_reorder_payload(request)
    if error:
        return error

    if not apply_reorder(Activity, ordered_ids):
        return JsonResponse({"ok": False, "message": "정렬 저장에 실패했습니다."}, status=400)

    return JsonResponse({"ok": True})