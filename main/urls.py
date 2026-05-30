from django.urls import path

from . import views

app_name = "main"

urlpatterns = [
    path("", views.home, name="home"),
    path("blog/", views.blog, name="blog"),
    path("board/", views.board, name="board"),
    path("diary/", views.diary, name="diary"),
    path("projects/<int:id>/", views.project_detail, name="project_detail"),
]
