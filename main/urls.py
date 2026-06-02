from django.urls import path

from . import views

app_name = "main"

urlpatterns = [
    path("", views.home, name="home"),
    path("photos/", views.photos, name="photos"),
    path("photos/bulk-delete/", views.photo_bulk_delete, name="photo_bulk_delete"),
    path("photos/<int:id>/delete/", views.photo_delete, name="photo_delete"),
    path("projects/<int:id>/", views.project_detail, name="project_detail"),
]
