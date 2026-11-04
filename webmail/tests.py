import json
from unittest import mock

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.mail import send_mail
from django.core.mail.backends.base import BaseEmailBackend
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from .models import SentMail, classify_subject
from .sanitize import sanitize_html, text_to_html


class SanitizeTests(SimpleTestCase):
	def test_scripts_forms_and_handlers_removed(self):
		out = sanitize_html('<div onclick="x()"><script>alert(1)</script><p style="color:red;background:url(x)">hi'
		                    '<a href="javascript:1">a</a><a href="https://x.y">b</a></p><iframe src=x>evil</iframe>'
		                    '<form><input><button>b</button></form>tail</div>')
		self.assertNotIn("script", out)
		self.assertNotIn("onclick", out)
		self.assertNotIn("javascript:", out)
		self.assertNotIn("url(", out)
		self.assertNotIn("evil", out)
		self.assertNotIn("<form", out)
		self.assertIn('href="https://x.y"', out)
		self.assertIn('rel="noopener noreferrer nofollow"', out)
		self.assertTrue(out.endswith("tail</div>"))

	def test_remote_images_blocked_until_allowed(self):
		src = '<img src="https://t/p.png"><img src="cid:abc"><img src="data:image/png;base64,AA">'
		blocked = sanitize_html(src)
		self.assertIn('data-src="https://t/p.png"', blocked)
		self.assertIn('src="cid:abc"', blocked)
		self.assertIn('src="data:image/png;base64,AA"', blocked)
		self.assertIn('src="https://t/p.png"', sanitize_html(src, show_images=True))

	def test_text_mail_links(self):
		out = text_to_html("see https://smjgallery.kr <b>")
		self.assertIn('<a href="https://smjgallery.kr"', out)
		self.assertIn("&lt;b&gt;", out)


class ClassifyTests(SimpleTestCase):
	def test_kinds(self):
		self.assertEqual(classify_subject("[MJ Gallery] 가입 이메일 인증"), "verify")
		self.assertEqual(classify_subject("[MJ Gallery] 비밀번호 재설정"), "reset")
		self.assertEqual(classify_subject("[MJ Gallery] 찾으신 아이디"), "find_id")
		self.assertEqual(classify_subject("아무거나", {"X-MJ-Kind": "webmail"}), "webmail")
		self.assertEqual(classify_subject("아무거나"), "other")


@override_settings(EMAIL_BACKEND="webmail.backend.LoggingEmailBackend",
                   WEBMAIL_INNER_EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class LoggingBackendTests(TestCase):
	def test_every_send_is_recorded(self):
		send_mail("[MJ Gallery] 가입 이메일 인증", "본문", None, ["a@example.com"])
		self.assertEqual(len(mail.outbox), 1)
		row = SentMail.objects.get()
		self.assertEqual((row.kind, row.to, row.ok), ("verify", "a@example.com", True))

	@override_settings(WEBMAIL_INNER_EMAIL_BACKEND="webmail.tests.BrokenBackend")
	def test_failure_is_recorded_and_silent_when_asked(self):
		sent = send_mail("x", "y", None, ["b@example.com"], fail_silently=True)
		self.assertEqual(sent, 0)
		row = SentMail.objects.get()
		self.assertFalse(row.ok)
		self.assertIn("boom", row.error)


class BrokenBackend(BaseEmailBackend):
	def send_messages(self, messages):
		raise RuntimeError("boom")


class FakeMailbox:
	"""IMAP 없이 뷰를 시험하기 위한 가짜 메일함."""
	calls = []
	messages = {
		("inbox", 7): {
			"uid": 7, "folder": "inbox", "subject": "안녕", "from": {"name": "홍길동", "email": "hong@example.com"}, "from_text": "홍길동 <hong@example.com>",
			"to": [], "to_text": "mjseo@smjgallery.kr", "cc": [], "cc_text": "", "reply_to": "hong@example.com", "date": "", "date_text": "2026.11.04 10:00",
			"message_id": "<m1@example.com>", "references": "", "text": "", "html": '<p>hi</p><script>x</script><img src="https://t/p.png"><img src="cid:pic1">',
			"attachments": [{"index": 2, "filename": "pic.png", "content_type": "image/png", "size": 10, "content_id": "pic1", "inline": True},
			                {"index": 3, "filename": "doc.pdf", "content_type": "application/pdf", "size": 20, "content_id": "", "inline": False}],
		},
	}

	def __init__(self):
		pass

	def __enter__(self):
		return self

	def __exit__(self, *exc):
		pass

	def folder_status(self):
		return [{"key": "inbox", "label": "받은 편지함", "icon": "📥", "total": 1, "unseen": 1}]

	def unread_count(self):
		return 1

	def list(self, folder, page=1, per_page=30, query=""):
		items = [dict(m, seen=False, flagged=False, answered=False, size=100) for (f, _u), m in self.messages.items() if f == folder]
		return {"items": items, "total": len(items), "page": page, "pages": 1}

	def message(self, folder, uid):
		try:
			return dict(self.messages[(folder, uid)])
		except KeyError:
			from .imap import WebmailError
			raise WebmailError("메일을 찾을 수 없어요")

	def set_flag(self, folder, uids, flag, on=True):
		FakeMailbox.calls.append(("flag", folder, tuple(uids), flag, on))

	def move(self, folder, uids, to):
		FakeMailbox.calls.append(("move", folder, tuple(uids), to))

	def delete(self, folder, uids):
		FakeMailbox.calls.append(("delete", folder, tuple(uids)))

	def append(self, folder, raw, flags="(\\Seen)"):
		FakeMailbox.calls.append(("append", folder))


@override_settings(WEBMAIL_ENABLED=True, WEBMAIL_PASSWORD="x", WEBMAIL_USER="mjseo@smjgallery.kr",
                   EMAIL_BACKEND="webmail.backend.LoggingEmailBackend",
                   WEBMAIL_INNER_EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class WebmailViewTests(TestCase):
	def setUp(self):
		User = get_user_model()
		self.admin = User.objects.create_superuser("mail-admin", "a@example.com", "pw")
		self.member = User.objects.create_user("mail-member", "m@example.com", "pw")
		FakeMailbox.calls = []
		patcher = mock.patch("webmail.views.imap.Mailbox", FakeMailbox)
		patcher.start()
		self.addCleanup(patcher.stop)

	def test_only_admin(self):
		self.assertEqual(self.client.get(reverse("webmail:index")).status_code, 302)
		self.client.force_login(self.member)
		self.assertEqual(self.client.get(reverse("webmail:index")).status_code, 302)
		self.assertEqual(self.client.get(reverse("webmail:api_list")).status_code, 302)
		self.client.force_login(self.admin)
		res = self.client.get(reverse("webmail:index"))
		self.assertEqual(res.status_code, 200)
		self.assertContains(res, 'id="mail-app"')
		self.assertContains(res, "/mail/")  # navbar 아이콘

	def test_widget_only_for_admin_and_hidden_on_mail_page(self):
		self.client.force_login(self.member)
		self.assertNotContains(self.client.get(reverse("main:home")), 'id="mail-fab"')
		self.client.force_login(self.admin)
		self.assertContains(self.client.get(reverse("main:home")), 'id="mail-fab"')
		self.assertNotContains(self.client.get(reverse("webmail:index")), 'id="mail-fab"')

	def test_list_and_message_sanitized(self):
		self.client.force_login(self.admin)
		data = self.client.get(reverse("webmail:api_list"), {"folder": "inbox"}).json()
		self.assertEqual(data["total"], 1)
		self.assertEqual(data["items"][0]["subject"], "안녕")
		msg = self.client.get(reverse("webmail:api_message"), {"folder": "inbox", "uid": 7}).json()
		self.assertTrue(msg["is_html"])
		self.assertNotIn("<script", msg["body_html"])
		self.assertIn('data-src="https://t/p.png"', msg["body_html"])
		self.assertTrue(msg["has_remote_images"])
		self.assertIn("/mail/attachment/?folder=inbox&uid=7&i=2", msg["body_html"])  # cid → 첨부 주소
		self.assertEqual(msg["attachments"][1]["url"], "/mail/attachment/?folder=inbox&uid=7&i=3")
		self.assertIn(("flag", "inbox", (7,), "\\Seen", True), FakeMailbox.calls)
		self.assertEqual(self.client.get(reverse("webmail:api_message"), {"folder": "inbox", "uid": 99}).status_code, 502)
		self.assertEqual(self.client.get(reverse("webmail:api_list"), {"folder": "nope"}).status_code, 400)

	def test_actions(self):
		self.client.force_login(self.admin)
		res = self.client.post(reverse("webmail:api_action"), json.dumps({"folder": "inbox", "uids": [7], "action": "move", "to": "junk"}), content_type="application/json")
		self.assertEqual(res.status_code, 200)
		self.assertIn(("move", "inbox", (7,), "junk"), FakeMailbox.calls)
		res = self.client.post(reverse("webmail:api_action"), json.dumps({"folder": "inbox", "uids": [7], "action": "delete"}), content_type="application/json")
		self.assertIn(("delete", "inbox", (7,)), FakeMailbox.calls)
		res = self.client.post(reverse("webmail:api_action"), json.dumps({"folder": "inbox", "uids": [], "action": "seen"}), content_type="application/json")
		self.assertEqual(res.status_code, 400)

	def test_send_records_and_copies_to_sent(self):
		self.client.force_login(self.admin)
		res = self.client.post(reverse("webmail:api_send"), {"to": "hong@example.com", "subject": "Re: 안녕", "body": "답장이에요",
		                                                     "in_reply_to": "<m1@example.com>", "reply_folder": "inbox", "reply_uid": "7"})
		self.assertEqual(res.status_code, 200, res.content)
		self.assertEqual(len(mail.outbox), 1)
		sent = mail.outbox[0]
		self.assertEqual(sent.to, ["hong@example.com"])
		self.assertEqual(sent.extra_headers["In-Reply-To"], "<m1@example.com>")
		self.assertIn("mjseo@smjgallery.kr", sent.from_email)
		self.assertEqual(SentMail.objects.get().kind, "webmail")
		self.assertIn(("append", "sent"), FakeMailbox.calls)
		self.assertIn(("flag", "inbox", (7,), "\\Answered", True), FakeMailbox.calls)
		self.assertEqual(self.client.post(reverse("webmail:api_send"), {"to": "not-an-address", "body": "x"}).status_code, 400)

	def test_unread_endpoint(self):
		self.client.force_login(self.admin)
		self.assertEqual(self.client.get(reverse("webmail:api_unread")).json()["unread"], 1)


class StudioMailLogTests(TestCase):
	def test_page_lists_rows_and_filters(self):
		User = get_user_model()
		admin = User.objects.create_superuser("log-admin", "a@example.com", "pw")
		SentMail.objects.create(kind="verify", to="a@example.com", subject="가입 인증", ok=True)
		SentMail.objects.create(kind="reset", to="b@example.com", subject="비번", ok=False, error="connection refused")
		self.assertEqual(self.client.get(reverse("studio:mail")).status_code, 302)
		self.client.force_login(admin)
		res = self.client.get(reverse("studio:mail"))
		self.assertEqual(res.status_code, 200)
		self.assertContains(res, "a@example.com")
		self.assertContains(res, "connection refused")
		res = self.client.get(reverse("studio:mail"), {"failed": "1"})
		self.assertEqual([r.to for r in res.context["rows"]], ["b@example.com"])
		res = self.client.get(reverse("studio:mail"), {"kind": "verify"})
		self.assertEqual([r.to for r in res.context["rows"]], ["a@example.com"])
