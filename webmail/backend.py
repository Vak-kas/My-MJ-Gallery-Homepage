"""보내는 메일마다 SentMail 에 기록을 남기는 백엔드. 실제 전송은 안쪽 백엔드(SMTP 또는 console)가 함."""

from django.conf import settings
from django.core.mail import get_connection
from django.core.mail.backends.base import BaseEmailBackend

from .models import SentMail, classify_subject


class LoggingEmailBackend(BaseEmailBackend):
	def __init__(self, fail_silently=False, **kwargs):
		super().__init__(fail_silently=fail_silently, **kwargs)
		inner = getattr(settings, "WEBMAIL_INNER_EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend")
		self.inner = get_connection(backend=inner, fail_silently=fail_silently, **kwargs)

	def open(self):
		return self.inner.open()

	def close(self):
		return self.inner.close()

	def send_messages(self, email_messages):
		sent = 0
		for message in email_messages:
			to = ", ".join(list(message.to) + list(message.cc) + list(message.bcc))[:500]
			row = SentMail(kind=classify_subject(message.subject, message.extra_headers), to=to,
			               subject=(message.subject or "")[:300], from_email=(message.from_email or "")[:200])
			try:
				n = self.inner.send_messages([message]) or 0
				row.ok = n > 0
				if not row.ok:
					row.error = "보내지 못함 (백엔드가 0통 반환)"
				sent += n
			except Exception as exc:  # noqa: BLE001 — 기록은 남기고 원래 동작(예외/무시)은 유지
				row.ok = False
				row.error = str(exc)[:500]
				row.save()
				if not self.fail_silently:
					raise
				continue
			row.save()
		return sent
