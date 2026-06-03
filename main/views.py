from django.shortcuts import get_object_or_404, render
from django.views.decorators.clickjacking import xframe_options_exempt
from django.contrib import messages
from django.core.paginator import Paginator
from django.core.exceptions import ValidationError
from django.db.models import DateTimeField
from django.db.models.functions import Coalesce
from django.shortcuts import redirect
from urllib.parse import quote
from studio.models import BasicInfo, Contact, Link, Education, Internship, Research, Teaching, Certification, Activity, Award, Publication, Project, Skill
from .models import Photo


PHOTO_FEED_PAGE_SIZE = 24
PHOTO_MAX_UPLOAD_BYTES = 10 * 1024 * 1024


def _normalize_tags(raw_tags: str) -> str:
    parts = [part.strip().lstrip("#") for part in (raw_tags or "").split(",")]
    unique_tags = []
    seen = set()
    for part in parts:
        if not part:
            continue
        lowered = part.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        unique_tags.append(part)
    return ", ".join(unique_tags)


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
    certifications = Certification.objects.filter(is_visible=True)

    career_sections = [
        {"key": "education", "title": "Education", "subtitle": "학력", "icon": "🎓", "items": educations, "total": educations.count()},
        {"key": "affiliation", "title": "Affiliation", "subtitle": "소속/역할", "icon": "🔬", "items": affiliations, "total": affiliations.count()},
        {"key": "internship", "title": "Internship", "subtitle": "경력", "icon": "💼", "items": internships, "total": internships.count()},
        {"key": "mentoring", "title": "Mentoring", "subtitle": "멘토링", "icon": "📚", "items": mentorings, "total": mentorings.count()},
        {"key": "certification", "title": "Certification", "subtitle": "자격증", "icon": "📜", "items": certifications, "total": certifications.count()},
    ]

    activities = Activity.objects.filter(is_visible=True)
    activity_sections = [
        {"key": "external_program", "title": "External Program", "subtitle": "대외활동", "icon": "🌍", "items": activities.filter(activity_type="external_program"), "total": activities.filter(activity_type="external_program").count()},
        {"key": "seminar", "title": "Seminar", "subtitle": "세미나", "icon": "🎤", "items": activities.filter(activity_type="seminar"), "total": activities.filter(activity_type="seminar").count()},
        {"key": "community", "title": "Community", "subtitle": "커뮤니티", "icon": "🤝", "items": activities.filter(activity_type="community"), "total": activities.filter(activity_type="community").count()},
        {"key": "volunteer", "title": "Volunteer", "subtitle": "봉사", "icon": "🌿", "items": activities.filter(activity_type="volunteer"), "total": activities.filter(activity_type="volunteer").count()},
        {"key": "challenge", "title": "Challenge", "subtitle": "대회", "icon": "🏆", "items": activities.filter(activity_type="challenge"), "total": activities.filter(activity_type="challenge").count()},
        {"key": "other", "title": "Other", "subtitle": "기타", "icon": "🗂", "items": activities.filter(activity_type="other"), "total": activities.filter(activity_type="other").count()},
    ]

    awards = Award.objects.filter(is_visible=True)
    skills = Skill.objects.filter(is_visible=True)

    skill_sections = [
        {"key": "language_framework", "title": "Language & Framework", "icon": "🪄", "items": skills.filter(category="language_framework"), "total": skills.filter(category="language_framework").count()},
        {"key": "devops_infra", "title": "DevOps/Infra Tools", "icon": "🏅", "items": skills.filter(category="devops_infra"), "total": skills.filter(category="devops_infra").count()},
        {"key": "test_security", "title": "Test & Security Tools", "icon": "🔎", "items": skills.filter(category="test_security"), "total": skills.filter(category="test_security").count()},
        {"key": "platform", "title": "Platform", "icon": "🐰", "items": skills.filter(category="platform"), "total": skills.filter(category="platform").count()},
        {"key": "other", "title": "Other", "icon": "🧰", "items": skills.filter(category="other"), "total": skills.filter(category="other").count()},
    ]

    award_stats = {
        "total": awards.count(),
        "campus": awards.filter(award_category="campus").count(),
        "external": awards.filter(award_category="external").count(),
        "other": awards.filter(award_category="other").count(),
    }

    return render(request, "main/home.html", {
        "info": info,
        "contact_sections": contact_sections,
        "links": links,
        "career_sections": career_sections,
        "activity_sections": activity_sections,
        "awards": awards,
        "award_stats": award_stats,
        "certifications": certifications,
        "publications_international": Publication.objects.filter(is_visible=True, publication_type="international"),
        "publications_domestic": Publication.objects.filter(is_visible=True, publication_type="domestic"),
        "projects": Project.objects.filter(is_visible=True),
        "skill_sections": skill_sections,
    })


@xframe_options_exempt
def project_detail(request, id):
    proj = get_object_or_404(Project, id=id, is_visible=True)
    is_embedded = request.GET.get("embed") == "1"
    attachment_ext = ""
    is_pdf_attachment = False
    is_image_attachment = False
    is_office_attachment = False
    office_preview_url = ""

    if proj.attachment and proj.attachment.name:
        attachment_ext = proj.attachment.name.rsplit(".", 1)[-1].lower() if "." in proj.attachment.name else ""
        is_pdf_attachment = attachment_ext == "pdf"
        is_image_attachment = attachment_ext in {"jpg", "jpeg", "png", "gif", "webp", "bmp", "svg"}
        is_office_attachment = attachment_ext in {"ppt", "pptx"}
        if is_office_attachment:
            absolute_src = request.build_absolute_uri(proj.attachment.url)
            office_preview_url = f"https://view.officeapps.live.com/op/embed.aspx?src={quote(absolute_src, safe='')}"

    return render(request, "main/project_detail.html", {
        "proj": proj,
        "is_embedded": is_embedded,
        "attachment_ext": attachment_ext,
        "is_pdf_attachment": is_pdf_attachment,
        "is_image_attachment": is_image_attachment,
        "is_office_attachment": is_office_attachment,
        "office_preview_url": office_preview_url,
    })


def photos(request):
    if request.method == "POST":
        if not (request.user.is_authenticated and request.user.is_superuser):
            messages.error(request, "사진 업로드 권한이 없습니다.")
            return redirect("main:photos")

        files = request.FILES.getlist("photos")
        tags = _normalize_tags((request.POST.get("tags") or "").strip())

        if not files:
            messages.error(request, "업로드할 사진 파일을 선택해 주세요.")
            return redirect("main:photos")

        uploaded_count = 0
        skipped = []

        for f in files:
            content_type = (getattr(f, "content_type", "") or "").lower()
            if not content_type.startswith("image/"):
                skipped.append(f"{f.name} (이미지 파일 아님)")
                continue

            if f.size > PHOTO_MAX_UPLOAD_BYTES:
                skipped.append(f"{f.name} (10MB 초과)")
                continue

            photo = Photo(
                tags=tags,
                image=f,
                uploaded_by=request.user,
            )

            try:
                photo.full_clean()
                photo.save()
                uploaded_count += 1
            except ValidationError:
                skipped.append(f"{f.name} (처리 실패)")

        if uploaded_count:
            messages.success(request, f"사진 {uploaded_count}장을 업로드했습니다.")

        if skipped:
            preview = ", ".join(skipped[:3])
            more = "" if len(skipped) <= 3 else f" 외 {len(skipped) - 3}건"
            messages.warning(request, f"일부 파일은 제외되었습니다: {preview}{more}")

        return redirect("main:photos")

    tag_query = (request.GET.get("tag") or "").strip()

    photo_qs = Photo.objects.filter(is_visible=True)
    if tag_query:
        photo_qs = photo_qs.filter(tags__icontains=tag_query)

    photo_qs = photo_qs.annotate(
        sort_dt=Coalesce("taken_at", "created_at", output_field=DateTimeField())
    ).order_by("-sort_dt", "-id")

    page_number = request.GET.get("page")
    page_obj = Paginator(photo_qs, PHOTO_FEED_PAGE_SIZE).get_page(page_number)

    all_tag_values = Photo.objects.filter(is_visible=True).exclude(tags="").values_list("tags", flat=True)
    tag_counter = {}
    for tag_blob in all_tag_values:
        for raw in tag_blob.split(","):
            tag = raw.strip()
            if not tag:
                continue
            key = tag.lower()
            if key not in tag_counter:
                tag_counter[key] = {"name": tag, "count": 0}
            tag_counter[key]["count"] += 1

    popular_tags = sorted(tag_counter.values(), key=lambda item: (-item["count"], item["name"]))[:15]

    return render(
        request,
        "main/photos.html",
        {
            "photos": list(page_obj.object_list),
            "page_obj": page_obj,
            "selected_tag": tag_query,
            "popular_tags": popular_tags,
        },
    )


def photo_delete(request, id):
    if request.method != "POST":
        return redirect("main:photos")

    if not (request.user.is_authenticated and request.user.is_superuser):
        messages.error(request, "사진 삭제 권한이 없습니다.")
        return redirect("main:photos")

    photo = get_object_or_404(Photo, id=id)
    photo.delete()
    messages.success(request, "사진을 삭제했습니다.")

    next_url = (request.POST.get("next") or "").strip()
    if next_url.startswith("/photos"):
        return redirect(next_url)

    return redirect("main:photos")


def photo_bulk_delete(request):
    if request.method != "POST":
        return redirect("main:photos")

    if not (request.user.is_authenticated and request.user.is_superuser):
        messages.error(request, "사진 삭제 권한이 없습니다.")
        return redirect("main:photos")

    raw_ids = request.POST.getlist("photo_ids")
    photo_ids = []
    for raw in raw_ids:
        try:
            photo_ids.append(int(raw))
        except (TypeError, ValueError):
            continue

    if not photo_ids:
        messages.warning(request, "삭제할 사진을 먼저 선택해 주세요.")
        return redirect("main:photos")

    deleted_count, _ = Photo.objects.filter(id__in=photo_ids).delete()
    messages.success(request, f"선택한 사진 {deleted_count}장을 삭제했습니다.")

    next_url = (request.POST.get("next") or "").strip()
    if next_url.startswith("/photos"):
        return redirect(next_url)

    return redirect("main:photos")
