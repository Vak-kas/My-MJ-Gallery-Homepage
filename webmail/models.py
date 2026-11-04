"""사이트가 보낸 메일 기록 (Studio 보안용). 메일함 자체는 Dovecot 에 있고 여기엔 안 둠."""

from django.db import models


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
