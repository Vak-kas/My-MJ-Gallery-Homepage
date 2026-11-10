from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.db import models


class Tag(models.Model):
	name = models.CharField(max_length=40, unique=True)
	slug = models.SlugField(max_length=60, unique=True)
	created_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		ordering = ["name"]

	def __str__(self):
		return self.name

	@staticmethod
	def clean_name(raw) -> str:
		"""입력한 태그 이름 정리: 양끝 공백·앞의 # 떼기, 공백 하나로, 40자."""
		name = " ".join(str(raw or "").strip().lstrip("#").split())
		return name[:40]


class Category(models.Model):
	"""블로그 카테고리 — Studio › Categories 에서 추가·수정·순서·노출을 정함.

	글(Post.category)에는 slug 문자열이 들어감. slug 는 주소 /blog/<slug>/ 이기도 함.
	"""

	slug = models.SlugField("주소", max_length=30, unique=True)
	name = models.CharField("이름", max_length=30)
	description = models.CharField("설명", max_length=120, blank=True)
	color = models.CharField("색", max_length=7, default="#0066cc")   # #rrggbb
	icon = models.CharField("아이콘", max_length=8, default="📝", blank=True)   # 이번 주 기록에 쓰는 이모지
	order = models.PositiveIntegerField(default=0)
	is_private = models.BooleanField("관리자 전용", default=False)   # Secret 처럼 나만 보는 카테고리
	show_on_hub = models.BooleanField("블로그 허브 카드", default=True)
	show_on_home = models.BooleanField("홈 블로그 바로가기", default=True)
	in_topic_map = models.BooleanField("Topic Map 포함", default=False)
	weekly_goal = models.PositiveSmallIntegerField("주간 목표", default=0)
	created_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		ordering = ["order", "id"]

	def __str__(self):
		return self.name

	def save(self, *args, **kwargs):
		super().save(*args, **kwargs)
		from .categories import clear_cache
		clear_cache()

	def delete(self, *args, **kwargs):
		result = super().delete(*args, **kwargs)
		from .categories import clear_cache
		clear_cache()
		return result

	@property
	def soft_color(self):
		"""배지·카드 배경용 연한 색 (같은 색에 투명도 10%)"""
		return f"{self.color}1a"


class Series(models.Model):
	"""글 묶음 (예: HackRF 입문 1~5편). 유튜브 재생목록처럼 /blog/series/ 에 모아 보여주고, Studio › Series 에서 관리."""

	name = models.CharField(max_length=80)
	slug = models.SlugField(max_length=100, unique=True, allow_unicode=True)
	description = models.CharField(max_length=200, blank=True)
	author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="blog_series")
	order = models.PositiveIntegerField(default=0)
	is_listed = models.BooleanField("시리즈 모음에 보이기", default=True)
	show_on_hub = models.BooleanField("블로그 허브에 보이기", default=True)
	created_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		ordering = ["order", "-id"]
		constraints = [models.UniqueConstraint(fields=["author", "name"], name="unique_series_name_per_author")]

	def __str__(self):
		return self.name


class Post(models.Model):
	VISIBILITY_PUBLIC = "public"
	VISIBILITY_PRIVATE = "private"
	VISIBILITY_PROTECTED = "protected"

	VISIBILITY_CHOICES = [
		(VISIBILITY_PUBLIC, "전체공개"),
		(VISIBILITY_PRIVATE, "비공개"),
		(VISIBILITY_PROTECTED, "일부공개(비밀번호)"),
	]

	# 처음부터 있던 카테고리 slug (카테고리 자체는 Category 표에서 관리 — Studio › Categories)
	CATEGORY_TECH = "tech"
	CATEGORY_ALGORITHM = "algorithm"
	CATEGORY_PAPER = "paper"
	CATEGORY_LIFE = "life"
	CATEGORY_SECRET = "secret"

	category = models.CharField(max_length=30, db_index=True)   # Category.slug

	@classmethod
	def allowed_categories(cls, user):
		"""글을 쓸 수 있는 카테고리 slug — 관리자만 전부, 일반 회원은 글쓰기 없음"""
		if getattr(user, "is_superuser", False):
			from .categories import slugs
			return set(slugs())
		return set()

	@property
	def category_info(self):
		"""이 글의 Category (지워진 카테고리면 이름만 slug 인 임시 값)"""
		from .categories import get
		return get(self.category)

	def get_category_display(self):
		return self.category_info.name
	title = models.CharField(max_length=200)
	cover_image = models.ImageField(upload_to="blog/covers/", blank=True, null=True)
	author = models.ForeignKey(
		settings.AUTH_USER_MODEL,
		on_delete=models.SET_NULL,
		null=True,
		blank=True,
		related_name="blog_posts",
	)
	slug = models.SlugField(max_length=230, unique=True)
	summary = models.CharField(max_length=240, blank=True)
	content = models.TextField(blank=True)
	tags = models.ManyToManyField(Tag, related_name="posts", blank=True)
	is_published = models.BooleanField(default=True, db_index=True)
	visibility = models.CharField(
		max_length=20,
		choices=VISIBILITY_CHOICES,
		default=VISIBILITY_PUBLIC,
		db_index=True,
	)
	access_password = models.CharField(max_length=128, blank=True)
	views = models.PositiveIntegerField(default=0)
	published_at = models.DateTimeField(null=True, blank=True, db_index=True)
	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)
	author_ip = models.GenericIPAddressField("작성 IP", null=True, blank=True)  # 부정 이용 방지, 90일 뒤 비움
	author_agent = models.CharField("작성 브라우저", max_length=300, blank=True)
	series = models.ForeignKey(Series, on_delete=models.SET_NULL, null=True, blank=True, related_name="posts")
	series_order = models.PositiveIntegerField(null=True, blank=True)

	class Meta:
		ordering = ["-published_at", "-id"]

	def __str__(self):
		return f"[{self.get_category_display()}] {self.title}"

	@property
	def is_edited(self):
		"""발행(없으면 작성) 시각보다 1분 넘게 뒤에 저장됐으면 '수정됨'. 임시저장 글을 처음 발행한 건 수정이 아님."""
		base = self.published_at or self.created_at
		if not base or not self.updated_at:
			return False
		return (self.updated_at - base).total_seconds() > 60

	def set_access_password(self, raw_password: str):
		raw_password = (raw_password or "").strip()
		if raw_password:
			self.access_password = make_password(raw_password)
		else:
			self.access_password = ""

	def check_access_password(self, raw_password: str) -> bool:
		if not self.access_password:
			return False
		return check_password((raw_password or "").strip(), self.access_password)


class PostLike(models.Model):
	post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name="likes")
	user = models.ForeignKey(
		settings.AUTH_USER_MODEL,
		on_delete=models.CASCADE,
		related_name="blog_post_likes",
	)
	created_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		unique_together = ("post", "user")
		ordering = ["-created_at", "-id"]

	def __str__(self):
		return f"{self.user} likes {self.post.title}"


class Comment(models.Model):
	post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name="comments")
	author = models.ForeignKey(
		settings.AUTH_USER_MODEL,
		on_delete=models.SET_NULL,
		null=True,
		blank=True,
		related_name="blog_comments",
	)
	author_name = models.CharField(max_length=60)
	content = models.TextField(max_length=1200)
	is_visible = models.BooleanField(default=True, db_index=True)
	created_at = models.DateTimeField(auto_now_add=True, db_index=True)
	updated_at = models.DateTimeField(auto_now=True)
	author_ip = models.GenericIPAddressField("작성 IP", null=True, blank=True)  # 부정 이용 방지, 90일 뒤 비움
	author_agent = models.CharField("작성 브라우저", max_length=300, blank=True)

	class Meta:
		ordering = ["-created_at", "-id"]

	def __str__(self):
		return f"{self.author_name} on {self.post.title}"


class CommentLike(models.Model):
	comment = models.ForeignKey(Comment, on_delete=models.CASCADE, related_name="likes")
	user = models.ForeignKey(
		settings.AUTH_USER_MODEL,
		on_delete=models.CASCADE,
		related_name="blog_comment_likes",
	)
	created_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		unique_together = ("comment", "user")
		ordering = ["-created_at", "-id"]

	def __str__(self):
		return f"{self.user} likes comment #{self.comment_id}"


class GuestbookEntry(models.Model):
	# 로그인한 사용자만 작성 (예전 익명 글은 author 가 비어 있음)
	author = models.ForeignKey(
		settings.AUTH_USER_MODEL,
		on_delete=models.SET_NULL,
		null=True,
		blank=True,
		related_name="guestbook_entries",
	)
	author_name = models.CharField(max_length=60)
	message = models.TextField(max_length=1000)
	is_visible = models.BooleanField(default=True, db_index=True)
	created_at = models.DateTimeField(auto_now_add=True, db_index=True)
	author_ip = models.GenericIPAddressField("작성 IP", null=True, blank=True)  # 부정 이용 방지, 90일 뒤 비움
	author_agent = models.CharField("작성 브라우저", max_length=300, blank=True)

	class Meta:
		ordering = ["-created_at", "-id"]
		verbose_name_plural = "Guestbook entries"

	def __str__(self):
		return f"Guestbook by {self.author_name}"
