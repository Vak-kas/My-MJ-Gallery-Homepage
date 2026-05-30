from django.contrib import admin
from .models import Comment, GuestbookEntry, Post, PostLike, Tag


@admin.register(Tag)
class TagAdmin(admin.ModelAdmin):
	list_display = ("name", "slug", "created_at")
	search_fields = ("name", "slug")


@admin.register(Post)
class PostAdmin(admin.ModelAdmin):
	list_display = ("title", "author", "category", "is_published", "views", "published_at", "updated_at")
	list_filter = ("category", "author", "is_published", "published_at")
	search_fields = ("title", "summary", "content", "slug")
	prepopulated_fields = {"slug": ("title",)}
	filter_horizontal = ("tags",)


@admin.register(Comment)
class CommentAdmin(admin.ModelAdmin):
	list_display = ("author_name", "post", "is_visible", "created_at")
	list_filter = ("is_visible", "created_at")
	search_fields = ("author_name", "content", "post__title")


@admin.register(PostLike)
class PostLikeAdmin(admin.ModelAdmin):
	list_display = ("post", "user", "created_at")
	list_filter = ("created_at",)
	search_fields = ("post__title", "user__username", "user__email")


@admin.register(GuestbookEntry)
class GuestbookEntryAdmin(admin.ModelAdmin):
	list_display = ("author_name", "is_visible", "created_at")
	list_filter = ("is_visible", "created_at")
	search_fields = ("author_name", "message")
