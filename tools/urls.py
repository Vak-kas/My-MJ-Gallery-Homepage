from django.urls import path

from . import views

app_name = "tools"

urlpatterns = [
    path("", views.index, name="index"),
    path("duplex/", views.duplex, name="duplex"),
    path("subnet/", views.subnet, name="subnet"),
]
