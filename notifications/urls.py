from django.urls import path

from . import views

app_name = "notifications"

urlpatterns = [
    path("", views.notification_list, name="list"),
    path("<int:id>/open/", views.notification_open, name="open"),
    path("read-all/", views.notification_read_all, name="read_all"),
    path("clear-read/", views.notification_clear_read, name="clear_read"),
    path("kakao/connect/", views.kakao_connect, name="kakao_connect"),
    path("kakao/callback/", views.kakao_callback, name="kakao_callback"),
    path("kakao/test/", views.kakao_test, name="kakao_test"),
    path("kakao/disconnect/", views.kakao_disconnect, name="kakao_disconnect"),
    path("api/recent/", views.notification_recent, name="recent"),
    path("mail/save/", views.alert_mail_save, name="alert_mail_save"),
    path("mail/test/", views.alert_mail_test, name="alert_mail_test"),
]
