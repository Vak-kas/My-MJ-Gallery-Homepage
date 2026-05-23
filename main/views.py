from django.shortcuts import render

from studio.models import BasicInfo, Contact, Link


def home(request):
    info = BasicInfo.objects.filter(is_visible=True).first() or BasicInfo.objects.first()

    contacts = Contact.objects.filter(is_visible=True).order_by("order", "id")
    links = Link.objects.filter(is_visible=True).order_by("-is_primary", "order", "id")

    contact_sections = [
        {"title": "Email", "items": contacts.filter(contact_type="email")},
        {"title": "Phone", "items": contacts.filter(contact_type="phone")},
        {"title": "Address", "items": contacts.filter(contact_type="address")},
    ]

    return render(request, "main/home.html", {
        "info": info,
        "contact_sections": contact_sections,
        "links": links,
    })
