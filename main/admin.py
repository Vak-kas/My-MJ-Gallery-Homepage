from django.contrib import admin
from .models import Photo


@admin.register(Photo)
class PhotoAdmin(admin.ModelAdmin):
	list_display = ("id", "tags", "taken_at", "is_visible", "created_at")
	list_filter = ("is_visible", "created_at", "taken_at")
	search_fields = ("title", "caption", "tags")
	ordering = ("-taken_at", "-created_at", "-id")
