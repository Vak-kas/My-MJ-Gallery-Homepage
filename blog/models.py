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


class Post(models.Model):
	VISIBILITY_PUBLIC = "public"
	VISIBILITY_PRIVATE = "private"
	VISIBILITY_PROTECTED = "protected"

	VISIBILITY_CHOICES = [
		(VISIBILITY_PUBLIC, "전체공개"),
		(VISIBILITY_PRIVATE, "비공개"),
		(VISIBILITY_PROTECTED, "일부공개(비밀번호)"),
	]

	CATEGORY_TECH = "tech"
	CATEGORY_BOARD = "board"
	CATEGORY_LIFE = "life"
	CATEGORY_SECRET = "secret"

	CATEGORY_CHOICES = [
		(CATEGORY_TECH, "Tech"),
		(CATEGORY_BOARD, "Board"),
		(CATEGORY_LIFE, "Life"),
		(CATEGORY_SECRET, "Secret"),
	]

	category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, db_index=True)
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

	class Meta:
		ordering = ["-published_at", "-id"]

	def __str__(self):
		return f"[{self.get_category_display()}] {self.title}"

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
	author_name = models.CharField(max_length=60)
	message = models.TextField(max_length=1000)
	is_visible = models.BooleanField(default=True, db_index=True)
	created_at = models.DateTimeField(auto_now_add=True, db_index=True)

	class Meta:
		ordering = ["-created_at", "-id"]
		verbose_name_plural = "Guestbook entries"

	def __str__(self):
		return f"Guestbook by {self.author_name}"
