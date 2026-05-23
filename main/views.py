from django.shortcuts import render

from studio.models import BasicInfo, Contact, Link, Education, Internship, Research, Teaching, Activity, Award


def home(request):
    info = BasicInfo.objects.filter(is_visible=True).first() or BasicInfo.objects.first()

    contacts = Contact.objects.filter(is_visible=True).order_by("order", "id")
    links = Link.objects.filter(is_visible=True).order_by("-is_primary", "order", "id")

    contact_sections = [
        {"title": "Email", "items": contacts.filter(contact_type="email")},
        {"title": "Phone", "items": contacts.filter(contact_type="phone")},
        {"title": "Address", "items": contacts.filter(contact_type="address")},
    ]

    educations = Education.objects.filter(is_visible=True)
    internships = Internship.objects.filter(is_visible=True)
    affiliations = Research.objects.filter(is_visible=True)
    mentorings = Teaching.objects.filter(is_visible=True)

    career_sections = [
        {"key": "education", "title": "Education", "subtitle": "학력", "icon": "🎓", "items": educations[:4], "total": educations.count()},
        {"key": "affiliation", "title": "Affiliation", "subtitle": "소속/역할", "icon": "🔬", "items": affiliations[:4], "total": affiliations.count()},
        {"key": "internship", "title": "Internship", "subtitle": "경력", "icon": "💼", "items": internships[:4], "total": internships.count()},
        {"key": "mentoring", "title": "Mentoring", "subtitle": "멘토링", "icon": "📚", "items": mentorings[:4], "total": mentorings.count()},
    ]

    activities = Activity.objects.filter(is_visible=True)
    activity_sections = [
        {"key": "external_program", "title": "External Program", "subtitle": "대외활동", "icon": "🌍", "items": activities.filter(activity_type="external_program")[:4], "total": activities.filter(activity_type="external_program").count()},
        {"key": "seminar", "title": "Seminar", "subtitle": "세미나", "icon": "🎤", "items": activities.filter(activity_type="seminar")[:4], "total": activities.filter(activity_type="seminar").count()},
        {"key": "community", "title": "Community", "subtitle": "커뮤니티", "icon": "🤝", "items": activities.filter(activity_type="community")[:4], "total": activities.filter(activity_type="community").count()},
        {"key": "volunteer", "title": "Volunteer", "subtitle": "봉사", "icon": "🌿", "items": activities.filter(activity_type="volunteer")[:4], "total": activities.filter(activity_type="volunteer").count()},
        {"key": "challenge", "title": "Challenge", "subtitle": "대회", "icon": "🏆", "items": activities.filter(activity_type="challenge")[:4], "total": activities.filter(activity_type="challenge").count()},
        {"key": "other", "title": "Other", "subtitle": "기타", "icon": "🗂", "items": activities.filter(activity_type="other")[:4], "total": activities.filter(activity_type="other").count()},
    ]

    return render(request, "main/home.html", {
        "info": info,
        "contact_sections": contact_sections,
        "links": links,
        "career_sections": career_sections,
        "activity_sections": activity_sections,
        "awards": Award.objects.filter(is_visible=True),
    })
