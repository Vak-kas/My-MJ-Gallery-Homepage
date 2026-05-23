from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from studio.models import BasicInfo, Contact, Link

from .common import admin_view


@admin_view
def index(request):
    return render(request, "studio/index.html")


@admin_view
def profile(request):
    return redirect("studio:profile_basic")


@admin_view
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


@admin_view
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


@admin_view
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


@admin_view
def profile_contact_delete(request, contact_id):
    contact = get_object_or_404(Contact, id=contact_id)

    if request.method == "POST":
        contact.delete()
        messages.success(request, "연락처 정보가 삭제되었습니다.")

    return redirect("studio:profile_contact")


@admin_view
def profile_contact_toggle_visibility(request, contact_id):
    contact = get_object_or_404(Contact, id=contact_id)

    if request.method == "POST":
        contact.is_visible = request.POST.get("is_visible") == "true"
        contact.save()

    return redirect("studio:profile_contact")


@admin_view
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


@admin_view
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


@admin_view
def profile_link_delete(request, link_id):
    link = get_object_or_404(Link, id=link_id)

    if request.method == "POST":
        link.delete()
        messages.success(request, "링크가 삭제되었습니다.")

    return redirect("studio:profile_links")


@admin_view
def profile_link_toggle_visibility(request, link_id):
    link = get_object_or_404(Link, id=link_id)

    if request.method == "POST":
        link.is_visible = request.POST.get("is_visible") == "true"
        link.save()
        messages.success(request, "공개 여부가 변경되었습니다.")

    return redirect("studio:profile_links")


@admin_view
def profile_link_toggle_primary(request, link_id):
    link = get_object_or_404(Link, id=link_id)

    if request.method == "POST":
        link.is_primary = request.POST.get("is_primary") == "true"
        link.save()
        messages.success(request, "대표 링크 여부가 변경되었습니다.")

    return redirect("studio:profile_links")


@admin_view
def profile_resume(request):
    return render(request, "studio/profile_resume.html")
