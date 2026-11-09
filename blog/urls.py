from django.urls import path

from . import views

app_name = "blog"

urlpatterns = [
    path("", views.index, name="index"),
    path("write/", views.post_create, name="post_create"),
    path("post/<str:slug>/", views.post_detail, name="post_detail"),
    path("post/<str:slug>/og.png", views.post_og_image, name="post_og"),
    path("post/<str:slug>/edit/", views.post_edit, name="post_edit"),
    path("post/<str:slug>/delete/", views.post_delete, name="post_delete"),
    path("series/<str:slug>/", views.series_detail, name="series"),
    path("all/", views.all_posts, name="all"),
    path("board/", views.board, name="board"),   # 옛 자유게시판 → /blog/life/
    path("api/url-preview/", views.url_preview, name="url_preview"),
    path("api/math-ocr/", views.math_ocr, name="math_ocr"),
    path("api/image-upload/", views.image_upload, name="image_upload"),
    # 카테고리 목록 (Studio › Categories 에서 만든 카테고리, 주소 = slug). 다른 주소와 안 겹치게 맨 끝
    path("<slug:slug>/", views.category_page, name="category"),
]
