from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render

from studio.models import Skill

from .common import admin_view, get_next_order


@admin_view
def skill(request):
    skills = Skill.objects.all()
    editing_skill_id = request.GET.get("edit", "").strip()
    editing_skill_id = int(editing_skill_id) if editing_skill_id.isdigit() else None
    editing_skill = Skill.objects.filter(id=editing_skill_id).first() if editing_skill_id else None

    category_meta = {
        "language_framework": {"icon": "🧪", "title": "Language & Framework"},
        "devops_infra": {"icon": "🏅", "title": "DevOps/Infra"},
        "test_security": {"icon": "🔎", "title": "Test & Security"},
        "platform": {"icon": "🖥", "title": "Platform"},
        "other": {"icon": "🧰", "title": "Other"},
    }

    grouped_sections = []
    for key, label in Skill.CATEGORY_CHOICES:
        items = skills.filter(category=key)
        grouped_sections.append({
            "key": key,
            "title": category_meta.get(key, {}).get("title", label),
            "icon": category_meta.get(key, {}).get("icon", "🧰"),
            "items": items,
            "count": items.count(),
        })

    return render(
        request,
        "studio/skill.html",
        {
            "skills": skills,
            "editing_skill": editing_skill,
            "skill_categories": Skill.CATEGORY_CHOICES,
            "grouped_sections": grouped_sections,
        },
    )


@admin_view
def skill_create(request):
    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        category = request.POST.get("category", "language_framework").strip() or "language_framework"
        note = request.POST.get("note", "").strip()
        is_visible = request.POST.get("is_visible") == "true"

        valid_categories = {choice[0] for choice in Skill.CATEGORY_CHOICES}
        if category not in valid_categories:
            category = "language_framework"

        if not name:
            messages.error(request, "기술명은 필수입니다.")
            return redirect("studio:skill")

        Skill.objects.create(
            name=name,
            category=category,
            note=note,
            is_visible=is_visible,
            order=get_next_order(Skill),
        )
        messages.success(request, "기술 스택이 추가되었습니다.")

    return redirect("studio:skill")


@admin_view
def skill_update(request, id):
    skill_item = get_object_or_404(Skill, id=id)

    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        category = request.POST.get("category", "language_framework").strip() or "language_framework"
        note = request.POST.get("note", "").strip()
        is_visible = request.POST.get("is_visible") == "true"

        valid_categories = {choice[0] for choice in Skill.CATEGORY_CHOICES}
        if category not in valid_categories:
            category = "language_framework"

        if not name:
            messages.error(request, "기술명은 필수입니다.")
            return redirect(f"/studio/skill/?edit={id}#skill-{id}")

        skill_item.name = name
        skill_item.category = category
        skill_item.note = note
        skill_item.is_visible = is_visible
        skill_item.save()
        messages.success(request, "기술 스택이 수정되었습니다.")

    return redirect(f"/studio/skill/#skill-{id}")


@admin_view
def skill_delete(request, id):
    skill_item = get_object_or_404(Skill, id=id)

    if request.method == "POST":
        skill_item.delete()
        messages.success(request, "기술 스택이 삭제되었습니다.")

    return redirect("studio:skill")


@admin_view
def skill_toggle_visibility(request, id):
    skill_item = get_object_or_404(Skill, id=id)

    if request.method == "POST":
        skill_item.is_visible = request.POST.get("is_visible") == "true"
        skill_item.save(update_fields=["is_visible", "updated_at"])
        messages.success(request, "공개 여부가 변경되었습니다.")

    return redirect("studio:skill")
