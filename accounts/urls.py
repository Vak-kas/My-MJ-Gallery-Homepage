from django.urls import path

from . import views

app_name = 'accounts'

urlpatterns = [
    path('', views.index, name="index"),
    path('signup/', views.signup_view, name="signup"),
    path('login/', views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    # 가입 이메일 인증
    path("verify/<int:user_id>/<str:token>/", views.verify_email_view, name="verify_email"),
    path("verify/resend/", views.verify_resend_view, name="verify_resend"),
    # 아이디·비밀번호 찾기
    path("find-id/", views.find_id_view, name="find_id"),
    path("password/reset/", views.PasswordResetStart.as_view(), name="password_reset"),
    path("password/reset/sent/", views.PasswordResetSent.as_view(), name="password_reset_done"),
    path("password/reset/<uidb64>/<token>/", views.PasswordResetConfirm.as_view(), name="password_reset_confirm"),
    path("password/reset/complete/", views.PasswordResetComplete.as_view(), name="password_reset_complete"),
    # 내 계정
    path("profile/", views.profile_edit_view, name="profile_edit"),
    path("password/change/", views.password_change_view, name="password_change"),
    path("delete/", views.delete_account_view, name="delete"),
]
