from django.urls import path

from . import views

app_name = 'accounts'

urlpatterns = [
    path('', views.index, name="index"),
    path('signup/', views.signup_view, name="signup"),
    path('login/', views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("verify/sent/", views.verify_sent_view, name="verify_sent"),
    path("verify/resend/", views.resend_verification_view, name="verify_resend"),
    path("verify/<str:uidb64>/<str:token>/", views.verify_email_view, name="verify_email"),
]