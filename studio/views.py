from django.shortcuts import render, redirect
from django.contrib.auth.decorators import user_passes_test
from .models import BasicInfo
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
def profile_basic(request):
    return render(request, 'studio/profile_basic.html')

@user_passes_test(superuser_required, login_url='accounts:login')
def profile_contact(request):
    return render(request, 'studio/profile_contact.html')

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
        info.location = request.POST.get("location", "")
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