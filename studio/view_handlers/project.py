from pathlib import Path
from uuid import uuid4

from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.text import get_valid_filename

from studio.models import Project

from .common import admin_view, apply_reorder, get_next_order, parse_month_input, parse_reorder_payload


def _safe_upload_name(original_name, folder, stem_limit=60):
    original = Path(original_name or "file")
    ext = original.suffix.lower() or ""
    safe_stem = get_valid_filename(original.stem or "file").replace(" ", "_")[:stem_limit] or "file"
    return f"{folder}/{safe_stem}-{uuid4().hex[:10]}{ext}"


def _collect_fields(post, files):
    """POST/FILES에서 Project 필드 딕셔너리 반환."""
    return {
        "title":          post.get("title", "").strip(),
        "subtitle":       post.get("subtitle", "").strip(),
        "project_type":   post.get("project_type", "team").strip() or "team",
        "status":         post.get("status", "in_progress").strip() or "in_progress",
        "github_url":     post.get("github_url", "").strip(),
        "deploy_url":     post.get("deploy_url", "").strip(),
        "period_start":   parse_month_input(post.get("period_start", "").strip()),
        "period_end":     parse_month_input(post.get("period_end", "").strip()),
        "is_current":     (post.get("status", "in_progress").strip() or "in_progress") == "in_progress",
        "team_size":      int(post["team_size"]) if post.get("team_size", "").strip().isdigit() else None,
        "contribution":   post.get("contribution", "").strip(),
        "tech_stack":     post.get("tech_stack", "").strip(),
        "description":    post.get("description", "").strip(),
        "role":           post.get("role", "").strip(),
        "key_points":     post.get("key_points", "").strip(),
        "lessons_learned": post.get("lessons_learned", "").strip(),
        "results":        post.get("results", "").strip(),
        "is_visible":     post.get("is_visible") == "true",
        "thumbnail":      files.get("thumbnail"),
        "detail_image_1": files.get("detail_image_1"),
        "detail_image_2": files.get("detail_image_2"),
        "detail_image_3": files.get("detail_image_3"),
        "attachment":     files.get("attachment"),
    }


@admin_view
def project(request):
    projects = Project.objects.all()

    editing_id_raw = request.GET.get("edit", "").strip()
    editing_id = int(editing_id_raw) if editing_id_raw.isdigit() else None
    editing_project = Project.objects.filter(id=editing_id).first() if editing_id else None

    return render(request, "studio/project.html", {
        "projects": projects,
        "editing_project": editing_project,
        "editing_project_id": editing_id,
    })


@admin_view
def project_create(request):
    if request.method == "POST":
        f = _collect_fields(request.POST, request.FILES)

        if not f["title"]:
            messages.error(request, "프로젝트명은 필수입니다.")
            return redirect("studio:project")

        thumbnail = f.pop("thumbnail")
        detail_image_1 = f.pop("detail_image_1")
        detail_image_2 = f.pop("detail_image_2")
        detail_image_3 = f.pop("detail_image_3")
        attachment = f.pop("attachment")

        if thumbnail:
            thumbnail.name = _safe_upload_name(thumbnail.name, "project")
        if detail_image_1:
            detail_image_1.name = _safe_upload_name(detail_image_1.name, "project")
        if detail_image_2:
            detail_image_2.name = _safe_upload_name(detail_image_2.name, "project")
        if detail_image_3:
            detail_image_3.name = _safe_upload_name(detail_image_3.name, "project")
        if attachment:
            attachment.name = _safe_upload_name(attachment.name, "project/attachments")

        proj = Project.objects.create(
            **f,
            thumbnail=thumbnail,
            detail_image_1=detail_image_1,
            detail_image_2=detail_image_2,
            detail_image_3=detail_image_3,
            attachment=attachment,
            order=get_next_order(Project),
        )
        messages.success(request, f"프로젝트 '{proj.title}'이(가) 추가되었습니다.")

    return redirect("studio:project")


@admin_view
def project_update(request, id):
    proj = get_object_or_404(Project, id=id)

    if request.method == "POST":
        f = _collect_fields(request.POST, request.FILES)

        if not f["title"]:
            messages.error(request, "프로젝트명은 필수입니다.")
            return redirect(f"{reverse('studio:project')}?edit={id}#project-{id}")

        thumbnail = f.pop("thumbnail")
        detail_image_1 = f.pop("detail_image_1")
        detail_image_2 = f.pop("detail_image_2")
        detail_image_3 = f.pop("detail_image_3")
        attachment = f.pop("attachment")

        # 썸네일 처리
        remove_thumbnail = request.POST.get("remove_thumbnail") == "true"
        if remove_thumbnail and proj.thumbnail:
            proj.thumbnail.delete(save=False)
            proj.thumbnail = None
        if thumbnail:
            if proj.thumbnail:
                proj.thumbnail.delete(save=False)
            thumbnail.name = _safe_upload_name(thumbnail.name, "project")
            proj.thumbnail = thumbnail

        # 상세 이미지 처리
        if request.POST.get("remove_detail_image_1") == "true" and proj.detail_image_1:
            proj.detail_image_1.delete(save=False)
            proj.detail_image_1 = None
        if detail_image_1:
            if proj.detail_image_1:
                proj.detail_image_1.delete(save=False)
            detail_image_1.name = _safe_upload_name(detail_image_1.name, "project")
            proj.detail_image_1 = detail_image_1

        if request.POST.get("remove_detail_image_2") == "true" and proj.detail_image_2:
            proj.detail_image_2.delete(save=False)
            proj.detail_image_2 = None
        if detail_image_2:
            if proj.detail_image_2:
                proj.detail_image_2.delete(save=False)
            detail_image_2.name = _safe_upload_name(detail_image_2.name, "project")
            proj.detail_image_2 = detail_image_2

        if request.POST.get("remove_detail_image_3") == "true" and proj.detail_image_3:
            proj.detail_image_3.delete(save=False)
            proj.detail_image_3 = None
        if detail_image_3:
            if proj.detail_image_3:
                proj.detail_image_3.delete(save=False)
            detail_image_3.name = _safe_upload_name(detail_image_3.name, "project")
            proj.detail_image_3 = detail_image_3

        # 첨부파일 처리
        remove_attachment = request.POST.get("remove_attachment") == "true"
        if remove_attachment and proj.attachment:
            proj.attachment.delete(save=False)
            proj.attachment = None
        if attachment:
            if proj.attachment:
                proj.attachment.delete(save=False)
            attachment.name = _safe_upload_name(attachment.name, "project/attachments")
            proj.attachment = attachment

        for key, val in f.items():
            setattr(proj, key, val)

        proj.save()
        messages.success(request, "프로젝트가 수정되었습니다.")

    return redirect(f"{reverse('studio:project')}#project-{id}")


@admin_view
def project_delete(request, id):
    proj = get_object_or_404(Project, id=id)

    if request.method == "POST":
        if proj.thumbnail:
            proj.thumbnail.delete(save=False)
        if proj.detail_image_1:
            proj.detail_image_1.delete(save=False)
        if proj.detail_image_2:
            proj.detail_image_2.delete(save=False)
        if proj.detail_image_3:
            proj.detail_image_3.delete(save=False)
        if proj.attachment:
            proj.attachment.delete(save=False)
        proj.delete()
        messages.success(request, "프로젝트가 삭제되었습니다.")

    return redirect("studio:project")


@admin_view
def project_toggle_visibility(request, id):
    proj = get_object_or_404(Project, id=id)

    if request.method == "POST":
        proj.is_visible = request.POST.get("is_visible") == "true"
        proj.save()
        messages.success(request, "공개 여부가 변경되었습니다.")

    return redirect("studio:project")


@admin_view
def project_reorder(request):
    if request.method != "POST":
        return JsonResponse({"ok": False}, status=405)

    ordered_ids, error = parse_reorder_payload(request)
    if error:
        return error

    if not apply_reorder(Project, ordered_ids):
        return JsonResponse({"ok": False, "message": "정렬 저장에 실패했습니다."}, status=400)

    return JsonResponse({"ok": True})
