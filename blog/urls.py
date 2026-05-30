from django.urls import path

from . import views

app_name = "blog"

urlpatterns = [
    path("", views.index, name="index"),
    path("write/", views.post_create, name="post_create"),
    path("tech/", views.tech, name="tech"),
    path("board/", views.board, name="board"),
    path("life/", views.life, name="life"),
    path("secret/", views.secret, name="secret"),
]
