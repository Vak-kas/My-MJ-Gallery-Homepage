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

    # location = models.CharField(max_length=100, blank=True)

    is_visible = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def interest_list(self):
        return [item.strip() for item in self.interests.split(",") if item.strip()]

    def keyword_list(self):
        return [item.strip() for item in self.keywords.split(",") if item.strip()]

    def __str__(self):
        return self.korean_name
    


class Contact(models.Model):
    CONTACT_TYPE_CHOICES = [
        ("email", "Email"),
        ("phone", "Phone"),
        ("address", "Address"),
    ]

    contact_type = models.CharField(
        max_length=20,
        choices=CONTACT_TYPE_CHOICES
    )

    label = models.CharField(max_length=100, blank=True)
    value = models.TextField()

    is_visible = models.BooleanField(default=True)
    order = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self):
        return f"{self.label} - {self.value}"
    

class Link(models.Model):
    PLATFORM_CHOICES = [
        ("github", "GitHub"),
        ("velog", "Velog"),
        ("tistory", "Tistory"),
        ("linkedin", "LinkedIn"),
        ("notion", "Notion"),
        ("scholar", "Google Scholar"),
        ("youtube", "YouTube"),
        ("instagram", "Instagram"),
        ("x", "X"),
        ("website", "Website"),
        ("other", "Other"),
    ]

    platform = models.CharField(max_length=30, choices=PLATFORM_CHOICES)
    label = models.CharField(max_length=100, blank=True)
    url = models.URLField()

    is_visible = models.BooleanField(default=True)
    is_primary = models.BooleanField(default=False)
    order = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self):
        return f"{self.get_platform_display()} - {self.url}"