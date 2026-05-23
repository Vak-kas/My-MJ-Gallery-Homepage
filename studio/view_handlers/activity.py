from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from studio.models import Activity

from .common import admin_view, apply_reorder, get_next_order, parse_month_input, parse_reorder_payload


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
        ("other", "기타 (Other)"),
    ]
    section_icons = {
        "external_program": "🌍",
        "seminar": "🎤",
        "community": "🤝",
        "volunteer": "🌿",
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
        is_visible = request.POST.get("is_visible") == "true"
        order = get_next_order(Activity)

        if not title:
            messages.error(request, "활동명은 필수입니다.")
            return redirect("studio:activity")

        if start_date and end_date and end_date < start_date:
            messages.error(request, "종료일은 시작일보다 빠를 수 없습니다.")
            return redirect("studio:activity")

        Activity.objects.create(
            activity_type=activity_type,
            title=title,
            organization_name=organization_name,
            role=role,
            start_date=start_date,
            end_date=end_date,
            is_current=is_current,
            description=description,
            url=url,
            is_visible=is_visible,
            order=order,
        )
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
        is_visible = request.POST.get("is_visible") == "true"

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
        activity_item.is_visible = is_visible
        activity_item.save()
        messages.success(request, "수정 완료되었습니다.")

    return redirect(f"{reverse('studio:activity')}#activity-{id}")


@admin_view
def activity_delete(request, id):
    activity_item = get_object_or_404(Activity, id=id)

    if request.method == "POST":
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