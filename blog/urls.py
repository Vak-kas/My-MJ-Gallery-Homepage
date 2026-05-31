from django.urls import path

from . import views

app_name = "blog"

urlpatterns = [
    path("", views.index, name="index"),
    path("write/", views.post_create, name="post_create"),
    path("post/<str:slug>/", views.post_detail, name="post_detail"),
    path("post/<str:slug>/edit/", views.post_edit, name="post_edit"),
    path("post/<str:slug>/delete/", views.post_delete, name="post_delete"),
    path("tech/", views.tech, name="tech"),
    path("board/", views.board, name="board"),
    path("life/", views.life, name="life"),
    path("secret/", views.secret, name="secret"),
    path("api/url-preview/", views.url_preview, name="url_preview"),
]
