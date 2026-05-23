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


class Education(models.Model):
    STATUS_CHOICES = [
        ("enrolled", "재학중"),
        ("graduated", "졸업"),
        ("admitted", "입학예정"),
    ]

    DEGREE_CHOICES = [
        ("none", "해당없음"),
        ("bachelor", "학부"),
        ("master", "석사"),
        ("phd", "박사"),
    ]

    school_name = models.CharField(max_length=200)
    major = models.CharField(max_length=200)
    degree = models.CharField(max_length=20, choices=DEGREE_CHOICES, default="none")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="graduated")
    
    start_date = models.DateField(blank=True, null=True)  # 입학일
    end_date = models.DateField(blank=True, null=True)    # 졸업일
    
    gpa = models.CharField(max_length=10, blank=True)      # 학점
    description = models.TextField(blank=True)

    is_visible = models.BooleanField(default=True)
    order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["order", "-start_date", "id"]

    def __str__(self):
        return f"{self.school_name} - {self.major}"


class Internship(models.Model):
    country = models.CharField(max_length=100, blank=True)
    company_name = models.CharField(max_length=200)
    department = models.CharField(max_length=200, blank=True)
    position = models.CharField(max_length=200, blank=True)
    
    start_date = models.DateField(blank=True, null=True)
    end_date = models.DateField(blank=True, null=True)
    is_current = models.BooleanField(default=False)
    
    description = models.TextField(blank=True)

    is_visible = models.BooleanField(default=True)
    order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["order", "-start_date", "id"]

    def __str__(self):
        return f"{self.company_name} - {self.country}" if self.country else self.company_name


class Research(models.Model):
    lab_name = models.CharField(max_length=200, blank=True)
    project_name = models.CharField(max_length=200)
    role = models.CharField(max_length=200, blank=True)  # 학부연구생, 대학원생 등
    
    start_date = models.DateField(blank=True, null=True)
    end_date = models.DateField(blank=True, null=True)
    is_current = models.BooleanField(default=False)
    
    output = models.TextField(blank=True)  # 논문, 특허 등
    description = models.TextField(blank=True)

    is_visible = models.BooleanField(default=True)
    order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["order", "-start_date", "id"]

    def __str__(self):
        return f"{self.lab_name} - {self.project_name}"


class Leadership(models.Model):
    organization_name = models.CharField(max_length=200)
    position = models.CharField(max_length=200)
    
    start_date = models.DateField(blank=True, null=True)
    end_date = models.DateField(blank=True, null=True)
    is_current = models.BooleanField(default=False)
    
    description = models.TextField(blank=True)

    is_visible = models.BooleanField(default=True)
    order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["order", "-start_date", "id"]

    def __str__(self):
        return f"{self.organization_name} - {self.position}"


class Teaching(models.Model):
    ROLE_CHOICES = [
        ("ta", "TA / Assistant"),
        ("instructor", "강사"),
        ("professor", "멘토"),
        ("curriculum", "교재개발"),
    ]

    course_name = models.CharField(max_length=200)
    institution = models.CharField(max_length=200)
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default="ta")

    start_date = models.DateField(blank=True, null=True)
    end_date = models.DateField(blank=True, null=True)
    is_current = models.BooleanField(default=False)
    
    year = models.IntegerField(blank=True, null=True)  # 연도
    semester = models.CharField(max_length=10, blank=True)  # 1학기, 2학기
    
    description = models.TextField(blank=True)

    is_visible = models.BooleanField(default=True)
    order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["order", "-year", "id"]

    def __str__(self):
        return f"{self.course_name} - {self.get_role_display()}"