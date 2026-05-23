from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import user_passes_test
from .models import BasicInfo, Contact
from django.contrib import messages


def superuser_required(user):
    return user.is_authenticated and user.is_superuser


@user_passes_test(superuser_required, login_url='accounts:login')
def index(request):
    return render(request, 'studio/index.html')


@user_passes_test(superuser_required, login_url='accounts:login')
def profile(request):
    return redirect('studio:profile_basic')

@user_passes_test(superuser_required, login_url='accounts:login')
def profile_links(request):
    return render(request, 'studio/profile_links.html')

@user_passes_test(superuser_required, login_url='accounts:login')
def profile_resume(request):
    return render(request, 'studio/profile_resume.html')

from django.shortcuts import render, redirect
from django.contrib.auth.decorators import user_passes_test

from .models import BasicInfo


def superuser_required(user):
    return user.is_authenticated and user.is_superuser


@user_passes_test(superuser_required, login_url='accounts:login')
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
        # info.location = request.POST.get("location", "")
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

    return render(request, "studio/profile_basic.html", {

        "info": info

    })

@user_passes_test(superuser_required, login_url='accounts:login')
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

    email_contacts = contacts.filter(contact_type="email")
    phone_contacts = contacts.filter(contact_type="phone")
    address_contacts = contacts.filter(contact_type="address")

    return render(request, "studio/profile_contact.html", {
        "contacts": contacts,
        "editing_contact_id": editing_contact_id,
        "contact_sections": [
            {"title": "Email", "items": email_contacts},
            {"title": "Phone", "items": phone_contacts},
            {"title": "Address", "items": address_contacts},
        ],
    })


@user_passes_test(superuser_required, login_url='accounts:login')
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


@user_passes_test(superuser_required, login_url='accounts:login')
def profile_contact_delete(request, contact_id):
    contact = get_object_or_404(Contact, id=contact_id)

    if request.method == "POST":
        contact.delete()
        messages.success(request, "연락처 정보가 삭제되었습니다.")

    return redirect("studio:profile_contact")


@user_passes_test(superuser_required, login_url='accounts:login')
def profile_contact_toggle_visibility(request, contact_id):
    contact = get_object_or_404(Contact, id=contact_id)

    if request.method == "POST":
        contact.is_visible = request.POST.get("is_visible") == "true"
        contact.save()

    return redirect("studio:profile_contact")