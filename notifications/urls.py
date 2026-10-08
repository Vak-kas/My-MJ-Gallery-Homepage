from django.urls import path

from . import views

app_name = "notifications"

urlpatterns = [
    path("", views.notification_list, name="list"),
    path("<int:id>/open/", views.notification_open, name="open"),
    path("read-all/", views.notification_read_all, name="read_all"),
    path("clear-read/", views.notification_clear_read, name="clear_read"),
]
