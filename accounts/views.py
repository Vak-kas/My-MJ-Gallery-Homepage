from django.shortcuts import render, redirect
from django.contrib.auth.models import User
from django.contrib.auth import login, logout, authenticate
from django.http import HttpResponse
from accounts.forms import UserForm

def index(request):
    return HttpResponse("안녕하세요. 오신것을 환영합니다.")


def signup_view(request):
    if request.method == "POST":
        form = UserForm(request.POST)
        if form.is_valid():
            form.save()
            username = form.cleaned_data.get('username')
            raw_password = form.cleaned_data.get('password1')
            user = authenticate(username=username, password=raw_password)  # 사용자 인증
            login(request, user)  # 로그인
            return redirect('accounts:index')
    else:
        form = UserForm()
    return render(request, 'accounts/signup.html', {'form': form})


def login_view(request):
    if request.method == "POST":
        username = request.POST.get('username')
        password = request.POST.get('password')
        user = authenticate(
            request,
            username=username,
            password=password
        )
        if user is not None:
            login(request, user)
            
            # superuser면 studio로
            if user.is_superuser:
                return redirect('studio:index')
            return redirect('accounts:index')
        else:
            return render(request, 'accounts/login.html', {
                'error': '아이디 또는 비밀번호가 올바르지 않습니다.'
            })
    return render(request, 'accounts/login.html')


def logout_view(request):
    logout(request)
    return redirect('main:home')