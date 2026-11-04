"""예약 발송 실행: run_scheduled(1분마다) → send_due(). 보낸 뒤 보낸 편지함에 사본, 답장이면 원본에 ↩."""

import logging
from email.utils import formataddr, make_msgid

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.utils import timezone

from . import imap
from .models import ScheduledMail

log = logging.getLogger(__name__)


def build_message(to, cc, bcc, subject, body, in_reply_to="", references="", files=(), html=""):
	"""files: (filename, bytes, content_type) 묶음. html 이 있으면 글자 본문 + HTML 본문(multipart/alternative)."""
	from .sanitize import sanitize_html
	from_email = formataddr((settings.WEBMAIL_FROM_NAME, settings.WEBMAIL_USER))
	headers = {"X-MJ-Kind": "webmail", "Message-ID": make_msgid(domain=settings.WEBMAIL_USER.split("@")[-1])}
	if in_reply_to:
		headers["In-Reply-To"] = in_reply_to
		headers["References"] = (references + " " + in_reply_to).strip()
	msg = EmailMultiAlternatives(subject or "(제목 없음)", body, from_email, to, cc=cc or None, bcc=bcc or None, headers=headers)
	if html and html.strip():
		clean = sanitize_html(html, show_images=True)
		msg.attach_alternative(f'<!doctype html><html><body style="font:14px/1.6 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;color:#1d1d1f">{clean}</body></html>', "text/html")
	for name, data, ctype in files:
		msg.attach(name, data, ctype or "application/octet-stream")
	return msg


def split_addresses(raw):
	import re

	return [a.strip() for a in re.split(r"[,;\n]", raw or "") if a.strip()]


def after_send(msg, reply_folder="", reply_uid=None):
	"""보낸 편지함 사본 + 답장 표시. IMAP 이 안 되면 로그만."""
	try:
		with imap.Mailbox() as box:
			box.append("sent", msg.message().as_bytes())
			if reply_folder and reply_uid:
				try:
					box.set_flag(reply_folder, [int(reply_uid)], "\\Answered", True)
				except (imap.WebmailError, ValueError):
					pass
	except imap.WebmailError as exc:
		log.warning("보낸 편지함 저장 실패: %s", exc)


def send_due(now=None):
	"""때가 된 예약 메일을 보냄. 보낸 개수 반환."""
	now = now or timezone.now()
	sent = 0
	for item in ScheduledMail.objects.filter(status=ScheduledMail.STATUS_PENDING, send_at__lte=now).order_by("send_at", "id"):
		files = []
		for att in item.attachments.all():
			try:
				with att.file.open("rb") as fh:
					files.append((att.filename, fh.read(), att.content_type))
			except OSError as exc:
				item.status, item.error = ScheduledMail.STATUS_FAILED, f"첨부를 읽지 못함: {exc}"[:500]
				item.save(update_fields=["status", "error"])
				break
		else:
			msg = build_message(split_addresses(item.to), split_addresses(item.cc), split_addresses(item.bcc), item.subject, item.body,
			                    item.in_reply_to, item.references, files, html=item.html)
			try:
				n = msg.send(fail_silently=False)
			except Exception as exc:  # noqa: BLE001
				item.status, item.error = ScheduledMail.STATUS_FAILED, str(exc)[:500]
				item.save(update_fields=["status", "error"])
				continue
			if not n:
				item.status, item.error = ScheduledMail.STATUS_FAILED, "보내지 못함"
				item.save(update_fields=["status", "error"])
				continue
			item.status, item.sent_at = ScheduledMail.STATUS_SENT, timezone.now()
			item.save(update_fields=["status", "sent_at"])
			after_send(msg, item.reply_folder, item.reply_uid)
			sent += 1
			for att in item.attachments.all():
				att.file.delete(save=False)
	return sent
