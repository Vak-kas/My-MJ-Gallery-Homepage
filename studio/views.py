import json

from django.contrib import messages
from django.contrib.auth.decorators import user_passes_test
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.dateparse import parse_date

from .models import BasicInfo, Contact, Link, Education, Internship, Research, Leadership, Teaching


def superuser_required(user):
    return user.is_authenticated and user.is_superuser


def parse_month_input(value):
    if not value:
        return None
    return parse_date(f"{value}-01")


def parse_gpa_input(request):
    score = request.POST.get("gpa_score", "").strip()
    scale = request.POST.get("gpa_scale", "").strip()
    fallback = request.POST.get("gpa", "").strip()

    if score and scale:
        return f"{score} / {scale}"
    if score:
        return score
    return fallback


def get_next_order(model_cls):
    latest = model_cls.objects.order_by("-order", "-id").first()
    return (latest.order + 1) if latest else 0


def apply_reorder(model_cls, ordered_ids):
    if not ordered_ids:
        return False

    id_set = set(ordered_ids)
    if len(id_set) != len(ordered_ids):
        return False

    items = {item.id: item for item in model_cls.objects.filter(id__in=ordered_ids)}
    if len(items) != len(ordered_ids):
        return False

    updated = []
    for idx, item_id in enumerate(ordered_ids):
        item = items[item_id]
        item.order = idx
        updated.append(item)

    model_cls.objects.bulk_update(updated, ["order"])
    return True


@user_passes_test(superuser_required, login_url="accounts:login")
def index(request):
    return render(request, "studio/index.html")


@user_passes_test(superuser_required, login_url="accounts:login")
def profile(request):
    return redirect("studio:profile_basic")


@user_passes_test(superuser_required, login_url="accounts:login")
def profile_basic(request):
    info = BasicInfo.objects.first()

    if request.method == "POST":
        if info is None:
            info = BasicInfo()

        info.korean_name = request.POST.get("korean_name", "")
        info.english_name = request.POST.get("english_name", "")
        info.profile_badge = request.POST.get("profile_badge", "")
        info.affiliation = request.POST.get("affiliation", "")
        info.headline = request.POST.get("headline", "")
        info.bio = request.POST.get("bio", "")
        info.interests = request.POST.get("interests", "")
        info.keywords = request.POST.get("keywords", "")
        info.is_visible = request.POST.get("is_visible") == "true"

        if request.POST.get("remove_profile_image") == "true":
            if info.profile_image:
                info.profile_image.delete(save=False)
            info.profile_image = None

        if request.FILES.get("profile_image"):
            info.profile_image = request.FILES["profile_image"]

        info.save()
        messages.success(request, "프로필 정보가 저장되었습니다.")
        return redirect("studio:profile_basic")

    return render(request, "studio/profile_basic.html", {"info": info})


@user_passes_test(superuser_required, login_url="accounts:login")
def profile_contact(request):
    contacts = Contact.objects.all()

    if request.method == "POST":
        contact_type = request.POST.get("contact_type", "")
        label = request.POST.get("label", "").strip()
        value = request.POST.get("value", "").strip()
        generic_value = request.POST.get("generic_value", "").strip()
        is_visible = request.POST.get("is_visible") == "true"

        if contact_type == "email":
            email_local = request.POST.get("email_local", "").strip()
            email_domain = request.POST.get("email_domain", "").strip()
            email_domain_custom = request.POST.get("email_domain_custom", "").strip()
            domain = email_domain_custom if email_domain == "custom" else email_domain

            if not value and email_local and domain:
                value = f"{email_local}@{domain}"

            if not label:
                domain_label_map = {
                    "gmail.com": "Gmail",
                    "naver.com": "Naver",
                    "edu.hanbat.ac.kr": "School",
                }
                label = domain_label_map.get(domain.lower(), "Email") if domain else "Email"

        elif contact_type == "phone":
            if not value:
                value = generic_value
            if not label:
                label = "Mobile"

        elif contact_type == "address":
            if not value:
                value = generic_value
            if not label:
                label = "Home"

        if value:
            Contact.objects.create(
                contact_type=contact_type,
                label=label,
                value=value,
                is_visible=is_visible,
            )
            messages.success(request, "연락처 정보가 추가되었습니다.")

        return redirect("studio:profile_contact")

    edit_id = request.GET.get("edit", "").strip()
    editing_contact_id = int(edit_id) if edit_id.isdigit() else None

    return render(request, "studio/profile_contact.html", {
        "contacts": contacts,
        "editing_contact_id": editing_contact_id,
        "contact_sections": [
            {"title": "Email", "items": contacts.filter(contact_type="email")},
            {"title": "Phone", "items": contacts.filter(contact_type="phone")},
            {"title": "Address", "items": contacts.filter(contact_type="address")},
        ],
    })


@user_passes_test(superuser_required, login_url="accounts:login")
def profile_contact_update(request, contact_id):
    contact = get_object_or_404(Contact, id=contact_id)

    if request.method == "POST":
        label = request.POST.get("label", "").strip()
        value = request.POST.get("value", "").strip()

        if contact.contact_type == "email" and not label:
            domain = value.split("@")[-1].lower() if "@" in value else ""
            domain_label_map = {
                "gmail.com": "Gmail",
                "naver.com": "Naver",
                "edu.hanbat.ac.kr": "School",
            }
            label = domain_label_map.get(domain, "Email") if domain else "Email"

        if contact.contact_type == "phone" and not label:
            label = "Mobile"

        if contact.contact_type == "address" and not label:
            label = "Home"

        if value:
            contact.label = label
            contact.value = value
            contact.is_visible = request.POST.get("is_visible") == "true"
            contact.save()
            messages.success(request, "연락처 정보가 수정되었습니다.")
        else:
            messages.error(request, "값(Value)은 비워둘 수 없습니다.")

    return redirect("studio:profile_contact")


@user_passes_test(superuser_required, login_url="accounts:login")
def profile_contact_delete(request, contact_id):
    contact = get_object_or_404(Contact, id=contact_id)

    if request.method == "POST":
        contact.delete()
        messages.success(request, "연락처 정보가 삭제되었습니다.")

    return redirect("studio:profile_contact")


@user_passes_test(superuser_required, login_url="accounts:login")
def profile_contact_toggle_visibility(request, contact_id):
    contact = get_object_or_404(Contact, id=contact_id)

    if request.method == "POST":
        contact.is_visible = request.POST.get("is_visible") == "true"
        contact.save()

    return redirect("studio:profile_contact")


@user_passes_test(superuser_required, login_url="accounts:login")
def profile_links(request):
    links = Link.objects.all()

    if request.method == "POST":
        platform = request.POST.get("platform", "").strip()
        label = request.POST.get("label", "").strip()
        url = request.POST.get("url", "").strip()
        is_visible = request.POST.get("is_visible") == "true"
        is_primary = request.POST.get("is_primary") == "true"

        if platform and url:
            Link.objects.create(
                platform=platform,
                label=label,
                url=url,
                is_visible=is_visible,
                is_primary=is_primary,
            )
            messages.success(request, "링크가 추가되었습니다.")
        else:
            messages.error(request, "플랫폼과 URL을 입력해주세요.")

        return redirect("studio:profile_links")

    edit_id = request.GET.get("edit", "").strip()
    editing_link_id = int(edit_id) if edit_id.isdigit() else None

    return render(request, "studio/profile_links.html", {
        "links": links,
        "editing_link_id": editing_link_id,
    })


@user_passes_test(superuser_required, login_url="accounts:login")
def profile_link_update(request, link_id):
    link = get_object_or_404(Link, id=link_id)

    if request.method == "POST":
        platform = request.POST.get("platform", "").strip()
        label = request.POST.get("label", "").strip()
        url = request.POST.get("url", "").strip()
        is_visible = request.POST.get("is_visible") == "true"
        is_primary = request.POST.get("is_primary") == "true"

        if platform and url:
            link.platform = platform
            link.label = label
            link.url = url
            link.is_visible = is_visible
            link.is_primary = is_primary
            link.save()
            messages.success(request, "링크가 수정되었습니다.")
            return redirect("studio:profile_links")

        messages.error(request, "플랫폼과 URL을 입력해주세요.")
        return redirect(f"{reverse('studio:profile_links')}?edit={link_id}#link-{link_id}")

    return redirect("studio:profile_links")


@user_passes_test(superuser_required, login_url="accounts:login")
def profile_link_delete(request, link_id):
    link = get_object_or_404(Link, id=link_id)

    if request.method == "POST":
        link.delete()
        messages.success(request, "링크가 삭제되었습니다.")

    return redirect("studio:profile_links")


@user_passes_test(superuser_required, login_url="accounts:login")
def profile_link_toggle_visibility(request, link_id):
    link = get_object_or_404(Link, id=link_id)

    if request.method == "POST":
        link.is_visible = request.POST.get("is_visible") == "true"
        link.save()
        messages.success(request, "공개 여부가 변경되었습니다.")

    return redirect("studio:profile_links")


@user_passes_test(superuser_required, login_url="accounts:login")
def profile_link_toggle_primary(request, link_id):
    link = get_object_or_404(Link, id=link_id)

    if request.method == "POST":
        link.is_primary = request.POST.get("is_primary") == "true"
        link.save()
        messages.success(request, "대표 링크 여부가 변경되었습니다.")

    return redirect("studio:profile_links")


@user_passes_test(superuser_required, login_url="accounts:login")
def profile_resume(request):
    return render(request, "studio/profile_resume.html")


@user_passes_test(superuser_required, login_url="accounts:login")
def career(request):
    educations = Education.objects.all()
    internships = Internship.objects.all()
    researches = Research.objects.all()
    teachings = Teaching.objects.all()

    context = {
        "educations": educations,
        "internships": internships,
        "researches": researches,
        "teachings": teachings,
    }

    return render(request, "studio/career.html", context)


# Education
@user_passes_test(superuser_required, login_url="accounts:login")
def education_create(request):
    if request.method == "POST":
        school_name = request.POST.get("school_name", "").strip()
        major = request.POST.get("major", "").strip()
        degree = request.POST.get("degree", "none").strip() or "none"
        status = request.POST.get("status", "graduated").strip()
        start_date = parse_month_input(request.POST.get("start_date", "").strip())
        end_date = parse_month_input(request.POST.get("end_date", "").strip())
        if status == "enrolled":
            end_date = None
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


@user_passes_test(superuser_required, login_url="accounts:login")
def education_update(request, id):
    education = get_object_or_404(Education, id=id)

    if request.method == "POST":
        school_name = request.POST.get("school_name", "").strip()
        major = request.POST.get("major", "").strip()
        degree = request.POST.get("degree", "none").strip() or "none"
        status = request.POST.get("status", "graduated").strip()
        start_date = parse_month_input(request.POST.get("start_date", "").strip())
        end_date = parse_month_input(request.POST.get("end_date", "").strip())
        if status == "enrolled":
            end_date = None
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


@user_passes_test(superuser_required, login_url="accounts:login")
def education_delete(request, id):
    education = get_object_or_404(Education, id=id)

    if request.method == "POST":
        education.delete()
        messages.success(request, "학력이 삭제되었습니다.")

    return redirect("studio:career")


@user_passes_test(superuser_required, login_url="accounts:login")
def education_toggle_visibility(request, id):
    education = get_object_or_404(Education, id=id)

    if request.method == "POST":
        education.is_visible = request.POST.get("is_visible") == "true"
        education.save()
        messages.success(request, "공개 여부가 변경되었습니다.")

    return redirect("studio:career")


@user_passes_test(superuser_required, login_url="accounts:login")
def education_reorder(request):
    if request.method != "POST":
        return JsonResponse({"ok": False}, status=405)

    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (ValueError, json.JSONDecodeError):
        return JsonResponse({"ok": False, "message": "잘못된 요청입니다."}, status=400)

    ordered_ids = payload.get("ordered_ids", [])
    if not all(isinstance(v, int) for v in ordered_ids):
        return JsonResponse({"ok": False, "message": "ID 형식이 올바르지 않습니다."}, status=400)

    if not apply_reorder(Education, ordered_ids):
        return JsonResponse({"ok": False, "message": "정렬 저장에 실패했습니다."}, status=400)

    return JsonResponse({"ok": True})


# Internship
@user_passes_test(superuser_required, login_url="accounts:login")
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
        end_date = None if is_current else parse_month_input(request.POST.get("end_date", "").strip())
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


@user_passes_test(superuser_required, login_url="accounts:login")
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
        end_date = None if is_current else parse_month_input(request.POST.get("end_date", "").strip())
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


@user_passes_test(superuser_required, login_url="accounts:login")
def internship_delete(request, id):
    internship = get_object_or_404(Internship, id=id)

    if request.method == "POST":
        internship.delete()
        messages.success(request, "인턴십이 삭제되었습니다.")

    return redirect("studio:career")


@user_passes_test(superuser_required, login_url="accounts:login")
def internship_toggle_visibility(request, id):
    internship = get_object_or_404(Internship, id=id)

    if request.method == "POST":
        internship.is_visible = request.POST.get("is_visible") == "true"
        internship.save()
        messages.success(request, "공개 여부가 변경되었습니다.")

    return redirect("studio:career")


@user_passes_test(superuser_required, login_url="accounts:login")
def internship_reorder(request):
    if request.method != "POST":
        return JsonResponse({"ok": False}, status=405)

    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (ValueError, json.JSONDecodeError):
        return JsonResponse({"ok": False, "message": "잘못된 요청입니다."}, status=400)

    ordered_ids = payload.get("ordered_ids", [])
    if not all(isinstance(v, int) for v in ordered_ids):
        return JsonResponse({"ok": False, "message": "ID 형식이 올바르지 않습니다."}, status=400)

    if not apply_reorder(Internship, ordered_ids):
        return JsonResponse({"ok": False, "message": "정렬 저장에 실패했습니다."}, status=400)

    return JsonResponse({"ok": True})


# Research
@user_passes_test(superuser_required, login_url="accounts:login")
def research_create(request):
    if request.method == "POST":
        lab_name = request.POST.get("lab_name", "").strip()
        project_name = request.POST.get("project_name", "").strip()
        role = request.POST.get("role", "").strip()
        start_date = parse_month_input(request.POST.get("start_date", "").strip())
        is_current = request.POST.get("is_current") == "true"
        end_date = None if is_current else parse_month_input(request.POST.get("end_date", "").strip())
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


@user_passes_test(superuser_required, login_url="accounts:login")
def research_update(request, id):
    research = get_object_or_404(Research, id=id)

    if request.method == "POST":
        lab_name = request.POST.get("lab_name", "").strip()
        project_name = request.POST.get("project_name", "").strip()
        role = request.POST.get("role", "").strip()
        start_date = parse_month_input(request.POST.get("start_date", "").strip())
        is_current = request.POST.get("is_current") == "true"
        end_date = None if is_current else parse_month_input(request.POST.get("end_date", "").strip())
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


@user_passes_test(superuser_required, login_url="accounts:login")
def research_delete(request, id):
    research = get_object_or_404(Research, id=id)

    if request.method == "POST":
        research.delete()
        messages.success(request, "소속/역할 항목이 삭제되었습니다.")

    return redirect("studio:career")


@user_passes_test(superuser_required, login_url="accounts:login")
def research_toggle_visibility(request, id):
    research = get_object_or_404(Research, id=id)

    if request.method == "POST":
        research.is_visible = request.POST.get("is_visible") == "true"
        research.save()
        messages.success(request, "공개 여부가 변경되었습니다.")

    return redirect("studio:career")


@user_passes_test(superuser_required, login_url="accounts:login")
def research_reorder(request):
    if request.method != "POST":
        return JsonResponse({"ok": False}, status=405)

    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (ValueError, json.JSONDecodeError):
        return JsonResponse({"ok": False, "message": "잘못된 요청입니다."}, status=400)

    ordered_ids = payload.get("ordered_ids", [])
    if not all(isinstance(v, int) for v in ordered_ids):
        return JsonResponse({"ok": False, "message": "ID 형식이 올바르지 않습니다."}, status=400)

    if not apply_reorder(Research, ordered_ids):
        return JsonResponse({"ok": False, "message": "정렬 저장에 실패했습니다."}, status=400)

    return JsonResponse({"ok": True})


# Leadership
@user_passes_test(superuser_required, login_url="accounts:login")
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


@user_passes_test(superuser_required, login_url="accounts:login")
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


@user_passes_test(superuser_required, login_url="accounts:login")
def leadership_delete(request, id):
    leadership = get_object_or_404(Leadership, id=id)

    if request.method == "POST":
        leadership.delete()
        messages.success(request, "리더십이 삭제되었습니다.")

    return redirect("studio:career")


@user_passes_test(superuser_required, login_url="accounts:login")
def leadership_toggle_visibility(request, id):
    leadership = get_object_or_404(Leadership, id=id)

    if request.method == "POST":
        leadership.is_visible = request.POST.get("is_visible") == "true"
        leadership.save()
        messages.success(request, "공개 여부가 변경되었습니다.")

    return redirect("studio:career")


@user_passes_test(superuser_required, login_url="accounts:login")
def leadership_reorder(request):
    if request.method != "POST":
        return JsonResponse({"ok": False}, status=405)

    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (ValueError, json.JSONDecodeError):
        return JsonResponse({"ok": False, "message": "잘못된 요청입니다."}, status=400)

    ordered_ids = payload.get("ordered_ids", [])
    if not all(isinstance(v, int) for v in ordered_ids):
        return JsonResponse({"ok": False, "message": "ID 형식이 올바르지 않습니다."}, status=400)

    if not apply_reorder(Leadership, ordered_ids):
        return JsonResponse({"ok": False, "message": "정렬 저장에 실패했습니다."}, status=400)

    return JsonResponse({"ok": True})


# Teaching
@user_passes_test(superuser_required, login_url="accounts:login")
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


@user_passes_test(superuser_required, login_url="accounts:login")
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


@user_passes_test(superuser_required, login_url="accounts:login")
def teaching_delete(request, id):
    teaching = get_object_or_404(Teaching, id=id)

    if request.method == "POST":
        teaching.delete()
        messages.success(request, "강의 경험이 삭제되었습니다.")

    return redirect("studio:career")


@user_passes_test(superuser_required, login_url="accounts:login")
def teaching_toggle_visibility(request, id):
    teaching = get_object_or_404(Teaching, id=id)

    if request.method == "POST":
        teaching.is_visible = request.POST.get("is_visible") == "true"
        teaching.save()
        messages.success(request, "공개 여부가 변경되었습니다.")

    return redirect("studio:career")


@user_passes_test(superuser_required, login_url="accounts:login")
def teaching_reorder(request):
    if request.method != "POST":
        return JsonResponse({"ok": False}, status=405)

    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (ValueError, json.JSONDecodeError):
        return JsonResponse({"ok": False, "message": "잘못된 요청입니다."}, status=400)

    ordered_ids = payload.get("ordered_ids", [])
    if not all(isinstance(v, int) for v in ordered_ids):
        return JsonResponse({"ok": False, "message": "ID 형식이 올바르지 않습니다."}, status=400)

    if not apply_reorder(Teaching, ordered_ids):
        return JsonResponse({"ok": False, "message": "정렬 저장에 실패했습니다."}, status=400)

    return JsonResponse({"ok": True})