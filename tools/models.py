import secrets
from uuid import uuid4

from django.conf import settings
from django.db import models
from django.db.models.signals import post_delete
from django.dispatch import receiver

from .storage import private_storage


def clip_upload_to(instance, filename):
	# 원래 파일 이름은 DB 에만 두고, 디스크에는 추측할 수 없는 이름으로 저장
	return f"clipboard/{instance.user_id}/{uuid4().hex}"


class ClipItem(models.Model):
	"""계정별 개인 클립보드 항목 (텍스트 / 이미지 / 파일)."""

	KIND_TEXT = "text"
	KIND_IMAGE = "image"
	KIND_FILE = "file"
	KIND_CHOICES = [(KIND_TEXT, "텍스트"), (KIND_IMAGE, "이미지"), (KIND_FILE, "파일")]

	user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="clip_items")
	kind = models.CharField(max_length=10, choices=KIND_CHOICES)
	text = models.TextField(blank=True)
	file = models.FileField(upload_to=clip_upload_to, storage=private_storage, blank=True)
	filename = models.CharField(max_length=255, blank=True)
	mime = models.CharField(max_length=120, blank=True)
	size = models.BigIntegerField(default=0)
	pinned = models.BooleanField(default=False)
	created_at = models.DateTimeField(auto_now_add=True, db_index=True)

	class Meta:
		ordering = ["-pinned", "-created_at", "-id"]

	def __str__(self):
		return f"{self.user_id}:{self.kind}:{self.pk}"


@receiver(post_delete, sender=ClipItem)
def _delete_clip_file(sender, instance, **kwargs):
	if instance.file:
		instance.file.delete(save=False)


def _share_token():
	return secrets.token_urlsafe(24)


def shared_upload_to(instance, filename):
	return f"shared/{instance.token}"


class SharedFile(models.Model):
	"""맡겨두기: 받는 사람이 없을 때 서버에 잠시 올려두고 링크로 내려받는 파일."""

	token = models.CharField(max_length=64, unique=True, default=_share_token)
	file = models.FileField(upload_to=shared_upload_to, storage=private_storage, blank=True)
	name = models.CharField(max_length=255)
	mime = models.CharField(max_length=120, blank=True)
	size = models.BigIntegerField()  # 올릴 전체 크기
	received = models.BigIntegerField(default=0)  # 지금까지 받은 크기
	sha256 = models.CharField(max_length=64, blank=True)
	completed = models.BooleanField(default=False)
	download_count = models.PositiveIntegerField(default=0)
	created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="shared_files")
	created_at = models.DateTimeField(auto_now_add=True)
	expires_at = models.DateTimeField(db_index=True)

	class Meta:
		ordering = ["-created_at", "-id"]

	def __str__(self):
		return f"{self.name} ({self.token[:6]}…)"


@receiver(post_delete, sender=SharedFile)
def _delete_shared_file(sender, instance, **kwargs):
	if instance.file:
		instance.file.delete(save=False)


BASE62 = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"


def short_code(length=6):
	return "".join(secrets.choice(BASE62) for _ in range(length))


class ShortLink(models.Model):
	"""단축 URL: smjgallery.kr/s/<code> → 원래 주소로 이동."""

	code = models.CharField(max_length=16, unique=True)
	target_url = models.URLField(max_length=2000)
	owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="short_links")
	created_at = models.DateTimeField(auto_now_add=True)
	expires_at = models.DateTimeField(null=True, blank=True)
	click_count = models.PositiveIntegerField(default=0)
	last_clicked_at = models.DateTimeField(null=True, blank=True)

	class Meta:
		ordering = ["-created_at", "-id"]

	def __str__(self):
		return f"{self.code} → {self.target_url}"


def _note_id():
	return secrets.token_urlsafe(16)


class SecretNote(models.Model):
	"""1회용 비밀 메모. 내용은 브라우저에서 AES-GCM 으로 암호화되어 오고, 키는 링크의 # 뒤에만 있어 서버는 모름.
	한 번 열리면 암호문을 지우고 열람 시각만 남김."""

	note_id = models.CharField(max_length=32, unique=True, default=_note_id)
	ciphertext = models.TextField(blank=True)  # base64(iv + 암호문)
	label = models.CharField(max_length=60, blank=True)  # 만든 사람만 보는 메모 이름
	created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="secret_notes")
	created_at = models.DateTimeField(auto_now_add=True)
	expires_at = models.DateTimeField()
	opened_at = models.DateTimeField(null=True, blank=True)

	class Meta:
		ordering = ["-created_at", "-id"]

	def __str__(self):
		return f"secret:{self.note_id}"
