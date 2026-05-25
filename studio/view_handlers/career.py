from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render

from studio.models import Education, Internship, Leadership, Research, Teaching

from .common import (
    admin_view,
    apply_reorder,
    get_next_order,
    parse_gpa_input,
    parse_month_input,
    parse_reorder_payload,
)


@admin_view
def career(request):
    educations = Education.objects.all()
    internships = Internship.objects.all()
    researches = Research.objects.all()
    teachings = Teaching.objects.all()

    edit_type = request.GET.get("edit_type", "").strip()
    edit_id_raw = request.GET.get("edit_id", "").strip()
    edit_id = int(edit_id_raw) if edit_id_raw.isdigit() else None

    model_map = {
        "education": Education,
        "internship": Internship,
        "research": Research,
        "teaching": Teaching,
    }

    editing_type = edit_type if edit_type in model_map else None
    editing_item = None
    if editing_type and edit_id:
        editing_item = model_map[editing_type].objects.filter(id=edit_id).first()
        if editing_item is None:
            editing_type = None

    def month_or_empty(value):
        return value.strftime("%Y-%m") if value else ""

    editing_data = {}
    if editing_type and editing_item:
        editing_data = {
            "is_editing": True,
            "type": editing_type,
            "id": editing_item.id,
            "is_visible": bool(getattr(editing_item, "is_visible", True)),
            "description": getattr(editing_item, "description", "") or "",
        }

        if editing_type == "education":
            editing_data.update({
                "school_name": editing_item.school_name,
                "major": editing_item.major,
                "degree": editing_item.degree,
                "status": editing_item.status,
                "start_date": month_or_empty(editing_item.start_date),
                "end_date": month_or_empty(editing_item.end_date),
                "gpa": editing_item.gpa or "",
            })
        elif editing_type == "internship":
            editing_data.update({
                "country": editing_item.country or "",
                "company_name": editing_item.company_name,
                "department": editing_item.department or "",
                "position": editing_item.position or "",
                "start_date": month_or_empty(editing_item.start_date),
                "end_date": month_or_empty(editing_item.end_date),
                "is_current": bool(editing_item.is_current),
            })
        elif editing_type == "research":
            editing_data.update({
                "lab_name": editing_item.lab_name or "",
                "project_name": editing_item.project_name,
                "role": editing_item.role or "",
                "start_date": month_or_empty(editing_item.start_date),
                "end_date": month_or_empty(editing_item.end_date),
                "is_current": bool(editing_item.is_current),
                "output": editing_item.output or "",
            })
        elif editing_type == "teaching":
            editing_data.update({
                "course_name": editing_item.course_name,
                "institution": editing_item.institution,
                "role": editing_item.role,
                "start_date": month_or_empty(editing_item.start_date),
                "end_date": month_or_empty(editing_item.end_date),
                "is_current": bool(editing_item.is_current),
            })

    context = {
        "educations": educations,
        "internships": internships,
        "researches": researches,
        "teachings": teachings,
        "editing_type": editing_type,
        "editing_id": editing_item.id if editing_item else None,
        "editing_data": editing_data,
    }

    return render(request, "studio/career.html", context)


@admin_view
def education_create(request):
    if request.method == "POST":
        school_name = request.POST.get("school_name", "").strip()
        major = request.POST.get("major", "").strip()
        degree = request.POST.get("degree", "none").strip() or "none"
        status = request.POST.get("status", "graduated").strip()
        start_date = parse_month_input(request.POST.get("start_date", "").strip())
        end_date = parse_month_input(request.POST.get("end_date", "").strip())
        gpa = parse_gpa_input(request)
        description = request.POST.get("description", "").strip()
        is_visible = request.POST.get("is_visible") == "true"
        order = get_next_order(Education)

        if not school_name or not major:
            messages.error(request, "학교명과 전공은 필수입니다.")
            return redirect("studio:career")

        if start_date and end_date and end_date < start_date:
            messages.error(request, "졸업일은 입학일보다 빠를 수 없습니다.")
            return redirect("studio:career")

        Education.objects.create(
            school_name=school_name,
            major=major,
            degree=degree,
            status=status,
            start_date=start_date,
            end_date=end_date,
            gpa=gpa,
            description=description,
            is_visible=is_visible,
            order=order,
        )
        messages.success(request, "학력이 추가되었습니다.")

    return redirect("studio:career")


@admin_view
def education_update(request, id):
    education = get_object_or_404(Education, id=id)

    if request.method == "POST":
        school_name = request.POST.get("school_name", "").strip()
        major = request.POST.get("major", "").strip()
        degree = request.POST.get("degree", "none").strip() or "none"
        status = request.POST.get("status", "graduated").strip()
        start_date = parse_month_input(request.POST.get("start_date", "").strip())
        end_date = parse_month_input(request.POST.get("end_date", "").strip())
        gpa = parse_gpa_input(request)
        description = request.POST.get("description", "").strip()
        is_visible = request.POST.get("is_visible") == "true"

        if not school_name or not major:
            messages.error(request, "학교명과 전공은 필수입니다.")
            return redirect("studio:career")

        if start_date and end_date and end_date < start_date:
            messages.error(request, "졸업일은 입학일보다 빠를 수 없습니다.")
            return redirect("studio:career")

        education.school_name = school_name
        education.major = major
        education.degree = degree
        education.status = status
        education.start_date = start_date
        education.end_date = end_date
        education.gpa = gpa
        education.description = description
        education.is_visible = is_visible
        education.save()
        messages.success(request, "학력이 수정되었습니다.")

    return redirect("studio:career")


@admin_view
def education_delete(request, id):
    education = get_object_or_404(Education, id=id)

    if request.method == "POST":
        education.delete()
        messages.success(request, "학력이 삭제되었습니다.")

    return redirect("studio:career")


@admin_view
def education_toggle_visibility(request, id):
    education = get_object_or_404(Education, id=id)

    if request.method == "POST":
        education.is_visible = request.POST.get("is_visible") == "true"
        education.save()
        messages.success(request, "공개 여부가 변경되었습니다.")

    return redirect("studio:career")


@admin_view
def education_reorder(request):
    if request.method != "POST":
        return JsonResponse({"ok": False}, status=405)

    ordered_ids, error = parse_reorder_payload(request)
    if error:
        return error

    if not apply_reorder(Education, ordered_ids):
        return JsonResponse({"ok": False, "message": "정렬 저장에 실패했습니다."}, status=400)

    return JsonResponse({"ok": True})


@admin_view
def internship_create(request):
    if request.method == "POST":
        country = request.POST.get("country", "").strip()
        company_name = request.POST.get("company_name", "").strip()
        department = request.POST.get("department", "").strip()
        position = request.POST.get("position", "").strip()
        if position == "-":
            position = ""
        start_date = parse_month_input(request.POST.get("start_date", "").strip())
        is_current = request.POST.get("is_current") == "true"
        end_date = parse_month_input(request.POST.get("end_date", "").strip())
        description = request.POST.get("description", "").strip()
        is_visible = request.POST.get("is_visible") == "true"
        order = get_next_order(Internship)

        if not company_name:
            messages.error(request, "기관/회사명은 필수입니다.")
            return redirect("studio:career")

        if start_date and end_date and end_date < start_date:
            messages.error(request, "종료일은 시작일보다 빠를 수 없습니다.")
            return redirect("studio:career")

        Internship.objects.create(
            country=country,
            company_name=company_name,
            department=department,
            position=position,
            start_date=start_date,
            end_date=end_date,
            is_current=is_current,
            description=description,
            is_visible=is_visible,
            order=order,
        )
        messages.success(request, "인턴십이 추가되었습니다.")

    return redirect("studio:career")


@admin_view
def internship_update(request, id):
    internship = get_object_or_404(Internship, id=id)

    if request.method == "POST":
        country = request.POST.get("country", "").strip()
        company_name = request.POST.get("company_name", "").strip()
        department = request.POST.get("department", "").strip()
        position = request.POST.get("position", "").strip()
        if position == "-":
            position = ""
        start_date = parse_month_input(request.POST.get("start_date", "").strip())
        is_current = request.POST.get("is_current") == "true"
        end_date = parse_month_input(request.POST.get("end_date", "").strip())
        description = request.POST.get("description", "").strip()
        is_visible = request.POST.get("is_visible") == "true"

        if not company_name:
            messages.error(request, "기관/회사명은 필수입니다.")
            return redirect("studio:career")

        if start_date and end_date and end_date < start_date:
            messages.error(request, "종료일은 시작일보다 빠를 수 없습니다.")
            return redirect("studio:career")

        internship.country = country
        internship.company_name = company_name
        internship.department = department
        internship.position = position
        internship.start_date = start_date
        internship.end_date = end_date
        internship.is_current = is_current
        internship.description = description
        internship.is_visible = is_visible
        internship.save()
        messages.success(request, "인턴십이 수정되었습니다.")

    return redirect("studio:career")


@admin_view
def internship_delete(request, id):
    internship = get_object_or_404(Internship, id=id)

    if request.method == "POST":
        internship.delete()
        messages.success(request, "인턴십이 삭제되었습니다.")

    return redirect("studio:career")


@admin_view
def internship_toggle_visibility(request, id):
    internship = get_object_or_404(Internship, id=id)

    if request.method == "POST":
        internship.is_visible = request.POST.get("is_visible") == "true"
        internship.save()
        messages.success(request, "공개 여부가 변경되었습니다.")

    return redirect("studio:career")


@admin_view
def internship_reorder(request):
    if request.method != "POST":
        return JsonResponse({"ok": False}, status=405)

    ordered_ids, error = parse_reorder_payload(request)
    if error:
        return error

    if not apply_reorder(Internship, ordered_ids):
        return JsonResponse({"ok": False, "message": "정렬 저장에 실패했습니다."}, status=400)

    return JsonResponse({"ok": True})


@admin_view
def research_create(request):
    if request.method == "POST":
        lab_name = request.POST.get("lab_name", "").strip()
        project_name = request.POST.get("project_name", "").strip()
        role = request.POST.get("role", "").strip()
        start_date = parse_month_input(request.POST.get("start_date", "").strip())
        is_current = request.POST.get("is_current") == "true"
        end_date = parse_month_input(request.POST.get("end_date", "").strip())
        output = request.POST.get("output", "").strip()
        description = request.POST.get("description", "").strip()
        is_visible = request.POST.get("is_visible") == "true"
        order = get_next_order(Research)

        if not project_name:
            messages.error(request, "활동명은 필수입니다.")
            return redirect("studio:career")

        if start_date and end_date and end_date < start_date:
            messages.error(request, "종료일은 시작일보다 빠를 수 없습니다.")
            return redirect("studio:career")

        Research.objects.create(
            lab_name=lab_name,
            project_name=project_name,
            role=role,
            start_date=start_date,
            end_date=end_date,
            is_current=is_current,
            output=output,
            description=description,
            is_visible=is_visible,
            order=order,
        )
        messages.success(request, "소속/역할 항목이 추가되었습니다.")

    return redirect("studio:career")


@admin_view
def research_update(request, id):
    research = get_object_or_404(Research, id=id)

    if request.method == "POST":
        lab_name = request.POST.get("lab_name", "").strip()
        project_name = request.POST.get("project_name", "").strip()
        role = request.POST.get("role", "").strip()
        start_date = parse_month_input(request.POST.get("start_date", "").strip())
        is_current = request.POST.get("is_current") == "true"
        end_date = parse_month_input(request.POST.get("end_date", "").strip())
        output = request.POST.get("output", "").strip()
        description = request.POST.get("description", "").strip()
        is_visible = request.POST.get("is_visible") == "true"

        if not project_name:
            messages.error(request, "활동명은 필수입니다.")
            return redirect("studio:career")

        if start_date and end_date and end_date < start_date:
            messages.error(request, "종료일은 시작일보다 빠를 수 없습니다.")
            return redirect("studio:career")

        research.lab_name = lab_name
        research.project_name = project_name
        research.role = role
        research.start_date = start_date
        research.end_date = end_date
        research.is_current = is_current
        research.output = output
        research.description = description
        research.is_visible = is_visible
        research.save()
        messages.success(request, "소속/역할 항목이 수정되었습니다.")

    return redirect("studio:career")


@admin_view
def research_delete(request, id):
    research = get_object_or_404(Research, id=id)

    if request.method == "POST":
        research.delete()
        messages.success(request, "소속/역할 항목이 삭제되었습니다.")

    return redirect("studio:career")


@admin_view
def research_toggle_visibility(request, id):
    research = get_object_or_404(Research, id=id)

    if request.method == "POST":
        research.is_visible = request.POST.get("is_visible") == "true"
        research.save()
        messages.success(request, "공개 여부가 변경되었습니다.")

    return redirect("studio:career")


@admin_view
def research_reorder(request):
    if request.method != "POST":
        return JsonResponse({"ok": False}, status=405)

    ordered_ids, error = parse_reorder_payload(request)
    if error:
        return error

    if not apply_reorder(Research, ordered_ids):
        return JsonResponse({"ok": False, "message": "정렬 저장에 실패했습니다."}, status=400)

    return JsonResponse({"ok": True})


@admin_view
def leadership_create(request):
    if request.method == "POST":
        organization_name = request.POST.get("organization_name", "").strip()
        position = request.POST.get("position", "").strip()
        start_date = parse_month_input(request.POST.get("start_date", "").strip())
        is_current = request.POST.get("is_current") == "true"
        end_date = None if is_current else parse_month_input(request.POST.get("end_date", "").strip())
        description = request.POST.get("description", "").strip()
        is_visible = request.POST.get("is_visible") == "true"
        order = get_next_order(Leadership)

        if not organization_name or not position:
            messages.error(request, "단체명과 직책은 필수입니다.")
            return redirect("studio:career")

        if start_date and end_date and end_date < start_date:
            messages.error(request, "종료일은 시작일보다 빠를 수 없습니다.")
            return redirect("studio:career")

        Leadership.objects.create(
            organization_name=organization_name,
            position=position,
            start_date=start_date,
            end_date=end_date,
            is_current=is_current,
            description=description,
            is_visible=is_visible,
            order=order,
        )
        messages.success(request, "리더십이 추가되었습니다.")

    return redirect("studio:career")


@admin_view
def leadership_update(request, id):
    leadership = get_object_or_404(Leadership, id=id)

    if request.method == "POST":
        organization_name = request.POST.get("organization_name", "").strip()
        position = request.POST.get("position", "").strip()
        start_date = parse_month_input(request.POST.get("start_date", "").strip())
        is_current = request.POST.get("is_current") == "true"
        end_date = None if is_current else parse_month_input(request.POST.get("end_date", "").strip())
        description = request.POST.get("description", "").strip()
        is_visible = request.POST.get("is_visible") == "true"

        if not organization_name or not position:
            messages.error(request, "단체명과 직책은 필수입니다.")
            return redirect("studio:career")

        if start_date and end_date and end_date < start_date:
            messages.error(request, "종료일은 시작일보다 빠를 수 없습니다.")
            return redirect("studio:career")

        leadership.organization_name = organization_name
        leadership.position = position
        leadership.start_date = start_date
        leadership.end_date = end_date
        leadership.is_current = is_current
        leadership.description = description
        leadership.is_visible = is_visible
        leadership.save()
        messages.success(request, "리더십이 수정되었습니다.")

    return redirect("studio:career")


@admin_view
def leadership_delete(request, id):
    leadership = get_object_or_404(Leadership, id=id)

    if request.method == "POST":
        leadership.delete()
        messages.success(request, "리더십이 삭제되었습니다.")

    return redirect("studio:career")


@admin_view
def leadership_toggle_visibility(request, id):
    leadership = get_object_or_404(Leadership, id=id)

    if request.method == "POST":
        leadership.is_visible = request.POST.get("is_visible") == "true"
        leadership.save()
        messages.success(request, "공개 여부가 변경되었습니다.")

    return redirect("studio:career")


@admin_view
def leadership_reorder(request):
    if request.method != "POST":
        return JsonResponse({"ok": False}, status=405)

    ordered_ids, error = parse_reorder_payload(request)
    if error:
        return error

    if not apply_reorder(Leadership, ordered_ids):
        return JsonResponse({"ok": False, "message": "정렬 저장에 실패했습니다."}, status=400)

    return JsonResponse({"ok": True})


@admin_view
def teaching_create(request):
    if request.method == "POST":
        course_name = request.POST.get("course_name", "").strip()
        institution = request.POST.get("institution", "").strip()
        role = request.POST.get("role", "ta").strip()
        start_date = parse_month_input(request.POST.get("start_date", "").strip())
        is_current = request.POST.get("is_current") == "true"
        end_date = None if is_current else parse_month_input(request.POST.get("end_date", "").strip())
        year = request.POST.get("year", "").strip()
        semester = request.POST.get("semester", "").strip()
        description = request.POST.get("description", "").strip()
        is_visible = request.POST.get("is_visible") == "true"
        order = get_next_order(Teaching)

        if not course_name or not institution:
            messages.error(request, "과목명과 기관은 필수입니다.")
            return redirect("studio:career")

        if start_date and end_date and end_date < start_date:
            messages.error(request, "종료일은 시작일보다 빠를 수 없습니다.")
            return redirect("studio:career")

        Teaching.objects.create(
            course_name=course_name,
            institution=institution,
            role=role,
            start_date=start_date,
            end_date=end_date,
            is_current=is_current,
            year=int(year) if year else None,
            semester=semester,
            description=description,
            is_visible=is_visible,
            order=order,
        )
        messages.success(request, "강의 경험이 추가되었습니다.")

    return redirect("studio:career")


@admin_view
def teaching_update(request, id):
    teaching = get_object_or_404(Teaching, id=id)

    if request.method == "POST":
        course_name = request.POST.get("course_name", "").strip()
        institution = request.POST.get("institution", "").strip()
        role = request.POST.get("role", "ta").strip()
        start_date = parse_month_input(request.POST.get("start_date", "").strip())
        is_current = request.POST.get("is_current") == "true"
        end_date = None if is_current else parse_month_input(request.POST.get("end_date", "").strip())
        year = request.POST.get("year", "").strip()
        semester = request.POST.get("semester", "").strip()
        description = request.POST.get("description", "").strip()
        is_visible = request.POST.get("is_visible") == "true"

        if not course_name or not institution:
            messages.error(request, "과목명과 기관은 필수입니다.")
            return redirect("studio:career")

        if start_date and end_date and end_date < start_date:
            messages.error(request, "종료일은 시작일보다 빠를 수 없습니다.")
            return redirect("studio:career")

        teaching.course_name = course_name
        teaching.institution = institution
        teaching.role = role
        teaching.start_date = start_date
        teaching.end_date = end_date
        teaching.is_current = is_current
        teaching.year = int(year) if year else None
        teaching.semester = semester
        teaching.description = description
        teaching.is_visible = is_visible
        teaching.save()
        messages.success(request, "강의 경험이 수정되었습니다.")

    return redirect("studio:career")


@admin_view
def teaching_delete(request, id):
    teaching = get_object_or_404(Teaching, id=id)

    if request.method == "POST":
        teaching.delete()
        messages.success(request, "강의 경험이 삭제되었습니다.")

    return redirect("studio:career")


@admin_view
def teaching_toggle_visibility(request, id):
    teaching = get_object_or_404(Teaching, id=id)

    if request.method == "POST":
        teaching.is_visible = request.POST.get("is_visible") == "true"
        teaching.save()
        messages.success(request, "공개 여부가 변경되었습니다.")

    return redirect("studio:career")


@admin_view
def teaching_reorder(request):
    if request.method != "POST":
        return JsonResponse({"ok": False}, status=405)

    ordered_ids, error = parse_reorder_payload(request)
    if error:
        return error

    if not apply_reorder(Teaching, ordered_ids):
        return JsonResponse({"ok": False, "message": "정렬 저장에 실패했습니다."}, status=400)

    return JsonResponse({"ok": True})
