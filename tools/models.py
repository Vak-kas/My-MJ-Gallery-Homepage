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


def _meet_id():
	return secrets.token_urlsafe(9)


class Meeting(models.Model):
	"""팀플 일정 맞추기. 날짜 × 시간 칸 중 각자 되는 칸을 칠함.
	칸 번호 = 날짜 순번 × 하루 칸 수 + 그날 안에서 칸 순번."""

	meet_id = models.CharField(max_length=24, unique=True, default=_meet_id)
	owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="meetings")
	title = models.CharField(max_length=80)
	note = models.CharField(max_length=300, blank=True)
	dates = models.JSONField()  # ["2026-10-12", ...] 정렬됨
	start_min = models.PositiveSmallIntegerField()  # 00:00 부터 몇 분
	end_min = models.PositiveSmallIntegerField()  # 이 시각 전까지
	slot_min = models.PositiveSmallIntegerField(default=30)
	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)  # 응답이 바뀌어도 갱신 → 화면 자동 새로고침 기준
	expires_at = models.DateTimeField(db_index=True)

	class Meta:
		ordering = ["-created_at", "-id"]

	def __str__(self):
		return f"meet:{self.meet_id} {self.title}"

	def get_absolute_url(self):
		from django.urls import reverse

		return reverse("tools:meet_room", args=[self.meet_id])

	@property
	def slots_per_day(self):
		return (self.end_min - self.start_min) // self.slot_min

	@property
	def slot_count(self):
		return self.slots_per_day * len(self.dates)


class MeetingResponse(models.Model):
	meeting = models.ForeignKey(Meeting, on_delete=models.CASCADE, related_name="responses")
	name = models.CharField(max_length=30)
	key_hash = models.CharField(max_length=64)  # 이 기기에서 고칠 때 쓰는 열쇠(sha256)
	pin_hash = models.CharField(max_length=128, blank=True)  # 다른 기기에서 다시 들어올 때 비밀번호 (선택)
	slots = models.JSONField(default=list)
	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)

	class Meta:
		ordering = ["created_at", "id"]
		constraints = [models.UniqueConstraint(fields=["meeting", "name"], name="uniq_meeting_response_name")]

	def __str__(self):
		return f"{self.meeting_id}:{self.name}"
