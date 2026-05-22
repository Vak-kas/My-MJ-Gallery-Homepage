from django.db import models


class BasicInfo(models.Model):
    profile_image = models.ImageField(
        upload_to="profile/",
        blank=True,
        null=True
    )

    korean_name = models.CharField(max_length=50)
    english_name = models.CharField(max_length=100, blank=True)

    profile_badge = models.CharField(max_length=255, blank=True)
    affiliation = models.CharField(max_length=200, blank=True)

    headline = models.CharField(max_length=255, blank=True)
    bio = models.TextField(blank=True)

    interests = models.TextField(blank=True)
    keywords = models.TextField(blank=True)

    location = models.CharField(max_length=100, blank=True)

    is_visible = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def interest_list(self):
        return [item.strip() for item in self.interests.split(",") if item.strip()]

    def keyword_list(self):
        return [item.strip() for item in self.keywords.split(",") if item.strip()]

    def __str__(self):
        return self.korean_name