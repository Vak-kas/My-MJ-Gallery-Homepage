from django.shortcuts import render
from django.contrib.auth.decorators import user_passes_test


def superuser_required(user):
    return user.is_authenticated and user.is_superuser


@user_passes_test(superuser_required, login_url='accounts:login')
def index(request):
    return render(request, 'studio/index.html')