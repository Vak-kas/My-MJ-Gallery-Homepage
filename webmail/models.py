"""사이트가 보낸 메일 기록 (Studio 보안용). 메일함 자체는 Dovecot 에 있고 여기엔 안 둠."""

from django.db import models

from tools.storage import private_storage


class SentMail(models.Model):
	KIND_CHOICES = [
		("verify", "가입 이메일 인증"),
		("reset", "비밀번호 재설정"),
		("find_id", "아이디 찾기"),
		("test", "설정 테스트"),
		("webmail", "웹메일에서 직접"),
		("contact", "사이트 문의"),
		("other", "기타"),
	]
	kind = models.CharField(max_length=20, choices=KIND_CHOICES, default="other", db_index=True)
	to = models.CharField("받는 사람", max_length=500)
	subject = models.CharField(max_length=300, blank=True)
	from_email = models.CharField(max_length=200, blank=True)
	ok = models.BooleanField(default=True, db_index=True)
	error = models.CharField(max_length=500, blank=True)
	created_at = models.DateTimeField(auto_now_add=True, db_index=True)

	class Meta:
		ordering = ["-created_at", "-id"]

	def __str__(self):
		return f"[{self.get_kind_display()}] {self.subject} → {self.to}"


def classify_subject(subject: str, headers=None) -> str:
	"""제목(과 X-MJ-Kind 헤더)으로 어떤 메일인지 구분."""
	kind = (headers or {}).get("X-MJ-Kind")
	if kind in dict(SentMail.KIND_CHOICES):
		return kind
	s = subject or ""
	if "가입 이메일 인증" in s:
		return "verify"
	if "비밀번호" in s:
		return "reset"
	if "아이디" in s:
		return "find_id"
	if "메일 설정 테스트" in s:
		return "test"
	return "other"


DEFAULT_SIGNATURE = (
	"<div><b>Minjae Seo (서민재)</b></div>"
	"<div>M.S. Student, Dept. of Computer Engineering, Hanbat National University</div>"
	"<div><i>Intelligent Communications and Information Security Lab (ICIS Lab)</i></div>"
	'<div>Email&nbsp; <a href="mailto:mjseo@smjgallery.kr">mjseo@smjgallery.kr</a> · <a href="mailto:mjseo@edu.hanbat.ac.kr">mjseo@edu.hanbat.ac.kr</a></div>'
	"<div>Phone&nbsp; +82 10-2750-5716</div>"
	"<div>174, Hakhaseo-ro 121beon-gil, Yuseong-gu, Daejeon, South Korea</div>"
	'<div><a href="https://smjgallery.kr">https://smjgallery.kr</a></div>'
)

class WebmailPref(models.Model):
	"""웹메일 설정 (한 줄짜리 — 메일함이 하나라서). 서명은 서버에 두어 어느 기기에서나 같게."""
	signature = models.TextField("서명 (HTML)", blank=True, default=DEFAULT_SIGNATURE)
	updated_at = models.DateTimeField(auto_now=True)

	@classmethod
	def get(cls):
		obj = cls.objects.first()
		if obj is None:
			obj = cls.objects.create()
		return obj


class MailContact(models.Model):
	"""주소 → 이름 매칭 (목록·읽기·자동완성에 이 이름으로 보임)."""
	email = models.EmailField(unique=True)
	name = models.CharField("이름", max_length=80)
	note = models.CharField("메모", max_length=200, blank=True)
	updated_at = models.DateTimeField(auto_now=True)

	class Meta:
		ordering = ["name", "email"]

	def save(self, *args, **kwargs):
		self.email = self.email.strip().lower()
		super().save(*args, **kwargs)

	def __str__(self):
		return f"{self.name} <{self.email}>"


def scheduled_upload_to(instance, filename):
	from uuid import uuid4

	return f"webmail/scheduled/{uuid4().hex}/{filename}"


class ScheduledMail(models.Model):
	"""예약 발송: run_scheduled(1분마다)가 때가 된 것을 보냄."""
	STATUS_PENDING, STATUS_SENT, STATUS_FAILED, STATUS_CANCELLED = "pending", "sent", "failed", "cancelled"
	STATUS_CHOICES = [(STATUS_PENDING, "대기"), (STATUS_SENT, "보냄"), (STATUS_FAILED, "실패"), (STATUS_CANCELLED, "취소")]

	to = models.CharField(max_length=1000)
	cc = models.CharField(max_length=1000, blank=True)
	bcc = models.CharField(max_length=1000, blank=True)
	subject = models.CharField(max_length=300, blank=True)
	body = models.TextField("글자 본문", blank=True)
	html = models.TextField("HTML 본문", blank=True)
	in_reply_to = models.CharField(max_length=300, blank=True)
	references = models.TextField(blank=True)
	reply_folder = models.CharField(max_length=100, blank=True)
	reply_uid = models.PositiveIntegerField(null=True, blank=True)
	send_at = models.DateTimeField(db_index=True)
	status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=STATUS_PENDING, db_index=True)
	error = models.CharField(max_length=500, blank=True)
	created_at = models.DateTimeField(auto_now_add=True)
	sent_at = models.DateTimeField(null=True, blank=True)

	class Meta:
		ordering = ["send_at", "id"]

	def __str__(self):
		return f"[{self.get_status_display()}] {self.subject} → {self.to} @ {self.send_at:%m-%d %H:%M}"


class ScheduledAttachment(models.Model):
	mail = models.ForeignKey(ScheduledMail, on_delete=models.CASCADE, related_name="attachments")
	file = models.FileField(upload_to=scheduled_upload_to, max_length=300, storage=private_storage)
	filename = models.CharField(max_length=255)
	content_type = models.CharField(max_length=120, blank=True)
	size = models.PositiveIntegerField(default=0)
