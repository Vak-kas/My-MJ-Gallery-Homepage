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


class Certification(models.Model):
    name = models.CharField(max_length=200)
    issuer = models.CharField(max_length=200, blank=True)
    score = models.CharField(max_length=80, blank=True)

    acquired_date = models.DateField(blank=True, null=True)
    expiration_date = models.DateField(blank=True, null=True)

    credential_id = models.CharField(max_length=120, blank=True)
    url = models.URLField(blank=True)
    description = models.TextField(blank=True)

    attachment = models.FileField(upload_to="certification/", blank=True, null=True)
    preview_image = models.ImageField(upload_to="certification/previews/", blank=True, null=True)

    is_visible = models.BooleanField(default=True)
    order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["order", "-acquired_date", "id"]

    def __str__(self):
        return self.name


class Project(models.Model):
    PROJECT_TYPE_CHOICES = [
        ("research", "연구"),
        ("personal", "개인"),
        ("team", "팀 프로젝트"),
    ]
    STATUS_CHOICES = [
        ("in_progress", "진행중"),
        ("completed", "완료"),
        ("on_hold", "보류"),
    ]

    title = models.CharField(max_length=200)
    subtitle = models.CharField(max_length=300, blank=True)
    project_type = models.CharField(max_length=20, choices=PROJECT_TYPE_CHOICES, default="team")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="in_progress")
    thumbnail = models.ImageField(upload_to="project/", blank=True, null=True)
    detail_image_1 = models.ImageField(upload_to="project/", blank=True, null=True)
    detail_image_2 = models.ImageField(upload_to="project/", blank=True, null=True)
    detail_image_3 = models.ImageField(upload_to="project/", blank=True, null=True)

    github_url = models.URLField(blank=True)
    deploy_url = models.URLField(blank=True)

    period_start = models.DateField(blank=True, null=True)
    period_end = models.DateField(blank=True, null=True)
    is_current = models.BooleanField(default=False)

    team_size = models.PositiveSmallIntegerField(blank=True, null=True)
    contribution = models.CharField(max_length=100, blank=True)  # e.g. "20% (6명)"

    tech_stack = models.CharField(max_length=500, blank=True)  # 쉼표 구분 입력

    description = models.TextField(blank=True)      # 프로젝트 소개
    role = models.TextField(blank=True)             # 담당 역할
    key_points = models.TextField(blank=True)       # 주요 고려사항
    lessons_learned = models.TextField(blank=True)  # 배운점
    results = models.TextField(blank=True)          # 결과물/성과

    attachment = models.FileField(upload_to="project/attachments/", blank=True, null=True)

    is_visible = models.BooleanField(default=True)
    order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["order", "-period_start", "id"]

    def __str__(self):
        return self.title

    def tech_list(self):
        return [t.strip() for t in self.tech_stack.split(",") if t.strip()]

    def period_display(self):
        if not self.period_start:
            return ""
        start = self.period_start.strftime("%Y.%m")
        if self.status == "in_progress":
            end = "현재"
        elif self.period_end:
            end = self.period_end.strftime("%Y.%m")
        elif self.status == "on_hold":
            end = "보류"
        else:
            return start
        return f"{start} ~ {end}"

    def all_images(self):
        return [img for img in [self.thumbnail, self.detail_image_1, self.detail_image_2, self.detail_image_3] if img]


class Activity(models.Model):
    ACTIVITY_TYPE_CHOICES = [
        ("external_program", "External Program"),
        ("community", "Community"),
        ("seminar", "Seminar"),
        ("volunteer", "Volunteer"),
        ("challenge", "Challenge"),
        ("other", "Other"),
    ]

    activity_type = models.CharField(max_length=20, choices=ACTIVITY_TYPE_CHOICES, default="external_program")
    title = models.CharField(max_length=200)
    organization_name = models.CharField(max_length=200, blank=True)
    role = models.CharField(max_length=200, blank=True)

    start_date = models.DateField(blank=True, null=True)
    end_date = models.DateField(blank=True, null=True)
    is_current = models.BooleanField(default=False)

    description = models.TextField(blank=True)
    url = models.URLField(blank=True)
    attachment = models.FileField(upload_to="activity/", max_length=255, blank=True, null=True)
    is_attachment_public = models.BooleanField(default=True, help_text="파일 공개 여부")
    preview_image = models.ImageField(upload_to="activity/previews/", max_length=255, blank=True, null=True)

    is_visible = models.BooleanField(default=True)
    order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["order", "-start_date", "id"]

    def __str__(self):
        return f"{self.get_activity_type_display()} - {self.title}"


class Award(models.Model):
    AWARD_CATEGORY_CHOICES = [
        ("campus", "교내"),
        ("external", "대외"),
        ("other", "기타"),
    ]

    title = models.CharField(max_length=200)
    organizer = models.CharField(max_length=200, blank=True)
    award_name = models.CharField(max_length=200, blank=True)
    award_category = models.CharField(max_length=20, choices=AWARD_CATEGORY_CHOICES, default="other")
    date = models.DateField(blank=True, null=True)

    description = models.TextField(blank=True)
    url = models.URLField(blank=True)
    attachment = models.FileField(upload_to="award/", max_length=255, blank=True, null=True)
    preview_image = models.ImageField(upload_to="award/previews/", max_length=255, blank=True, null=True)

    is_visible = models.BooleanField(default=True)
    order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["order", "-date", "id"]

    def __str__(self):
        return self.title


class Publication(models.Model):
    PUBLICATION_TYPE_CHOICES = [
        ("international", "국제지/국제학회"),
        ("domestic", "국내지/국내학회"),
    ]

    PUBLICATION_KIND_CHOICES = [
        ("journal", "저널"),
        ("conference", "학술지"),
    ]

    publication_type = models.CharField(max_length=20, choices=PUBLICATION_TYPE_CHOICES, default="international")
    publication_kind = models.CharField(max_length=20, choices=PUBLICATION_KIND_CHOICES, default="journal")
    title = models.CharField(max_length=255)
    venue = models.CharField(max_length=255, blank=True)
    authors = models.CharField(max_length=255, blank=True)
    date = models.DateField(blank=True, null=True)

    doi = models.CharField(max_length=120, blank=True)
    url = models.URLField(blank=True)
    abstract = models.TextField(blank=True)
    attachment = models.FileField(upload_to="publication/", max_length=255, blank=True, null=True)
    preview_image = models.ImageField(upload_to="publication/previews/", max_length=255, blank=True, null=True)

    is_visible = models.BooleanField(default=True)
    order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["order", "-date", "id"]

    def __str__(self):
        return self.title


class Skill(models.Model):
    CATEGORY_CHOICES = [
        ("language_framework", "Language & Framework"),
        ("devops_infra", "DevOps/Infra"),
        ("test_security", "Test & Security"),
        ("platform", "Platform"),
        ("other", "Other"),
    ]

    name = models.CharField(max_length=100)
    category = models.CharField(max_length=30, choices=CATEGORY_CHOICES, default="language_framework")
    note = models.CharField(max_length=150, blank=True)

    is_visible = models.BooleanField(default=True)
    order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self):
        return f"{self.get_category_display()} - {self.name}"