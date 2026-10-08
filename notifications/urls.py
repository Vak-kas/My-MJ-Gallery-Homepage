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
]
