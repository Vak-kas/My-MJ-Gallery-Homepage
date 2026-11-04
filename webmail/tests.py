import json
from unittest import mock

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.mail import send_mail
from django.core.mail.backends.base import BaseEmailBackend
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from .imap import WebmailError, date_group, mutf7_decode, mutf7_encode
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


class ImapHelperTests(SimpleTestCase):
	def test_mutf7_roundtrip(self):
		for name in ("학교", "영수증 2026", "Work&Life", "plain"):
			enc = mutf7_encode(name)
			self.assertTrue(all(0x20 <= ord(c) <= 0x7E for c in enc), enc)
			self.assertEqual(mutf7_decode(enc), name)
		self.assertEqual(mutf7_encode("Work&Life"), "Work&-Life")

	def test_date_group(self):
		from django.utils import timezone

		now = timezone.localtime()
		self.assertEqual(date_group(now.isoformat()), "오늘")
		self.assertEqual(date_group(""), "이전")
		self.assertEqual(date_group("2000-01-01T00:00:00+09:00"), "이전")


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


def _msg(uid, folder="inbox", **kw):
	base = {
		"uid": uid, "folder": folder, "subject": "안녕", "from": {"name": "홍길동", "email": "hong@example.com"}, "from_text": "홍길동 <hong@example.com>",
		"to": [{"name": "", "email": "mjseo@smjgallery.kr"}], "to_text": "mjseo@smjgallery.kr", "cc": [], "cc_text": "", "bcc_text": "", "reply_to": "hong@example.com",
		"date": "2026-11-04T10:00:00+09:00", "date_text": "2026.11.04 10:00", "message_id": "<m1@example.com>", "references": "", "text": "", "html": "",
		"attachments": [], "seen": False, "flagged": False, "answered": False, "draft": False, "has_attachment": False, "size": 100, "preview": "hi",
	}
	base.update(kw)
	return base


class FakeMailbox:
	"""IMAP 없이 뷰를 시험하기 위한 가짜 메일함."""
	calls = []
	labels = ["학교"]
	messages = {}

	@classmethod
	def reset(cls):
		cls.calls = []
		cls.labels = ["학교"]
		cls.messages = {
			("inbox", 7): _msg(7, html='<p>hi</p><script>x</script><img src="https://t/p.png"><img src="cid:pic1">',
			                   attachments=[{"index": 2, "filename": "pic.png", "content_type": "image/png", "size": 10, "content_id": "pic1", "inline": True},
			                                {"index": 3, "filename": "doc.pdf", "content_type": "application/pdf", "size": 20, "content_id": "", "inline": False}],
			                   has_attachment=True),
			("inbox", 5): _msg(5, subject="두 번째", seen=True, flagged=True, text="plain body"),
			("drafts", 9): _msg(9, folder="drafts", subject="초안", draft=True, text="쓰다 만 글", seen=True),
		}

	def __init__(self):
		pass

	def __enter__(self):
		return self

	def __exit__(self, *exc):
		pass

	def folder_status(self):
		sys_ = [{"key": k, "label": k, "icon": "x", "total": 1, "unseen": 1 if k == "inbox" else 0, "system": True} for k in ("inbox", "sent", "drafts", "junk", "trash")]
		return sys_ + [{"key": f"f:{n}", "label": n, "icon": "🏷", "total": 0, "unseen": 0, "system": False} for n in FakeMailbox.labels]

	def unread_count(self):
		return sum(1 for (f, _u), m in self.messages.items() if f == "inbox" and not m["seen"])

	def list(self, folder, page=1, per_page=30, query="", filter="all", sort="newest", advanced=None):
		FakeMailbox.calls.append(("list", folder, query, filter, sort, advanced or {}))
		items = [dict(m) for (f, _u), m in sorted(self.messages.items(), reverse=True) if f == folder]
		if filter == "unseen":
			items = [m for m in items if not m["seen"]]
		if filter == "flagged":
			items = [m for m in items if m["flagged"]]
		if query:
			items = [m for m in items if query in m["subject"]]
		return {"items": items, "total": len(items), "page": page, "pages": 1}

	def message(self, folder, uid):
		try:
			return dict(self.messages[(folder, uid)])
		except KeyError:
			raise WebmailError("메일을 찾을 수 없어요")

	def neighbors(self, folder, uid, **kw):
		uids = [u for (f, u) in sorted(self.messages, reverse=True) if f == folder]
		i = uids.index(uid)
		return (uids[i - 1] if i > 0 else None), (uids[i + 1] if i + 1 < len(uids) else None)

	def fetch_raw(self, folder, uid):
		if (folder, uid) not in self.messages:
			raise WebmailError("없음")
		return b"Subject: raw\r\n\r\nbody"

	def set_flag(self, folder, uids, flag, on=True):
		FakeMailbox.calls.append(("flag", folder, tuple(uids), flag, on))

	def move(self, folder, uids, to):
		FakeMailbox.calls.append(("move", folder, tuple(uids), to))

	def delete(self, folder, uids):
		FakeMailbox.calls.append(("delete", folder, tuple(uids)))

	def empty(self, folder):
		FakeMailbox.calls.append(("empty", folder))
		return 3

	def append(self, folder, raw, flags="(\\Seen)"):
		FakeMailbox.calls.append(("append", folder, flags))
		return 42

	def create_label(self, name):
		if name in FakeMailbox.labels:
			raise WebmailError("이미 있어요")
		FakeMailbox.labels.append(name)
		return "f:" + name

	def rename_label(self, old, new):
		FakeMailbox.labels[FakeMailbox.labels.index(old)] = new
		return "f:" + new

	def delete_label(self, name):
		FakeMailbox.labels.remove(name)


@override_settings(WEBMAIL_ENABLED=True, WEBMAIL_PASSWORD="x", WEBMAIL_USER="mjseo@smjgallery.kr",
                   EMAIL_BACKEND="webmail.backend.LoggingEmailBackend",
                   WEBMAIL_INNER_EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class WebmailViewTests(TestCase):
	def setUp(self):
		User = get_user_model()
		self.admin = User.objects.create_superuser("mail-admin", "a@example.com", "pw")
		self.member = User.objects.create_user("mail-member", "m@example.com", "pw")
		FakeMailbox.reset()
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
		self.assertContains(res, "/mail/")  # navbar 버튼

	def test_compose_to_param(self):
		self.client.force_login(self.admin)
		res = self.client.get(reverse("webmail:index") + "?to=hong@example.com")
		self.assertContains(res, 'data-compose-to="hong@example.com"')
		res = self.client.get(reverse("webmail:index") + "?to=not-an-address")
		self.assertContains(res, 'data-compose-to=""')

	def test_widget_only_for_admin_and_hidden_on_mail_page(self):
		self.client.force_login(self.member)
		self.assertNotContains(self.client.get(reverse("main:home")), 'id="mail-fab"')
		self.client.force_login(self.admin)
		self.assertContains(self.client.get(reverse("main:home")), 'id="mail-fab"')
		self.assertNotContains(self.client.get(reverse("webmail:index")), 'id="mail-fab"')

	def test_state_lists_labels(self):
		self.client.force_login(self.admin)
		data = self.client.get(reverse("webmail:api_state")).json()
		self.assertIn("f:학교", [f["key"] for f in data["folders"]])

	def test_list_filters_sort_and_groups(self):
		self.client.force_login(self.admin)
		data = self.client.get(reverse("webmail:api_list"), {"folder": "inbox"}).json()
		self.assertEqual(data["total"], 2)
		self.assertIn(data["items"][0]["group"], ("오늘", "어제", "이번 주", "이번 달", "이전"))  # 가짜 메일 시각이 시간대·자정에 걸려 달라짐
		self.assertTrue(data["items"][0]["has_attachment"])
		data = self.client.get(reverse("webmail:api_list"), {"folder": "inbox", "filter": "flagged"}).json()
		self.assertEqual([m["uid"] for m in data["items"]], [5])
		data = self.client.get(reverse("webmail:api_list"), {"folder": "inbox", "filter": "weird", "sort": "oldest", "from": "hong", "since": "2026-01-01"}).json()
		self.assertEqual((data["filter"], data["sort"]), ("all", "oldest"))
		self.assertEqual(FakeMailbox.calls[-1][5]["from"], "hong")
		self.assertEqual(str(FakeMailbox.calls[-1][5]["since"]), "2026-01-01")
		self.assertEqual(self.client.get(reverse("webmail:api_list"), {"folder": "inbox", "since": "bad"}).status_code, 400)
		self.assertEqual(self.client.get(reverse("webmail:api_list"), {"folder": "nope"}).status_code, 400)
		self.assertEqual(self.client.get(reverse("webmail:api_list"), {"folder": "f:학교"}).status_code, 200)

	def test_message_sanitized_with_neighbors(self):
		self.client.force_login(self.admin)
		msg = self.client.get(reverse("webmail:api_message"), {"folder": "inbox", "uid": 7}).json()
		self.assertTrue(msg["is_html"])
		self.assertNotIn("<script", msg["body_html"])
		self.assertIn('data-src="https://t/p.png"', msg["body_html"])
		self.assertTrue(msg["has_remote_images"])
		self.assertIn("/mail/attachment/?folder=inbox&uid=7&i=2", msg["body_html"])  # cid → 첨부 주소
		self.assertEqual(msg["attachments"][1]["url"], "/mail/attachment/?folder=inbox&uid=7&i=3")
		self.assertEqual((msg["prev_uid"], msg["next_uid"]), (None, 5))
		self.assertEqual(msg["raw_url"], "/mail/raw/?folder=inbox&uid=7")
		self.assertIn(("flag", "inbox", (7,), "\\Seen", True), FakeMailbox.calls)
		self.assertEqual(self.client.get(reverse("webmail:api_message"), {"folder": "inbox", "uid": 99}).status_code, 502)
		raw = self.client.get(reverse("webmail:raw"), {"folder": "inbox", "uid": 7})
		self.assertEqual(raw.status_code, 200)
		self.assertEqual(raw["Content-Type"], "text/plain; charset=utf-8")
		self.assertEqual(self.client.get(reverse("webmail:raw"), {"folder": "inbox", "uid": 99}).status_code, 404)

	def test_actions_and_empty(self):
		self.client.force_login(self.admin)
		post = lambda body: self.client.post(reverse("webmail:api_action"), json.dumps(body), content_type="application/json")  # noqa: E731
		self.assertEqual(post({"folder": "inbox", "uids": [7], "action": "move", "to": "f:학교"}).status_code, 200)
		self.assertIn(("move", "inbox", (7,), "f:학교"), FakeMailbox.calls)
		self.assertEqual(post({"folder": "inbox", "uids": [7], "action": "flag"}).status_code, 200)
		self.assertIn(("flag", "inbox", (7,), "\\Flagged", True), FakeMailbox.calls)
		self.assertEqual(post({"folder": "inbox", "uids": [], "action": "seen"}).status_code, 400)
		self.assertEqual(post({"folder": "inbox", "action": "empty"}).status_code, 400)
		res = post({"folder": "trash", "action": "empty"})
		self.assertEqual(res.json()["count"], 3)

	def test_labels(self):
		self.client.force_login(self.admin)
		post = lambda body: self.client.post(reverse("webmail:api_labels"), json.dumps(body), content_type="application/json")  # noqa: E731
		res = post({"action": "create", "name": "영수증"})
		self.assertEqual(res.json()["key"], "f:영수증")
		self.assertIn("f:영수증", [f["key"] for f in res.json()["folders"]])
		self.assertEqual(post({"action": "create", "name": "영수증"}).status_code, 502)
		self.assertEqual(post({"action": "rename", "folder": "f:영수증", "name": "지출"}).json()["key"], "f:지출")
		self.assertEqual(post({"action": "rename", "folder": "inbox", "name": "x"}).status_code, 400)
		self.assertEqual(post({"action": "delete", "folder": "f:지출"}).status_code, 200)
		self.assertNotIn("지출", FakeMailbox.labels)

	def test_draft_then_send(self):
		self.client.force_login(self.admin)
		res = self.client.post(reverse("webmail:api_draft"), {"to": "", "subject": "초안", "body": "쓰는 중"})
		self.assertEqual(res.status_code, 200, res.content)
		self.assertEqual(res.json()["uid"], 42)
		self.assertIn(("append", "drafts", "(\\Seen \\Draft)"), FakeMailbox.calls)
		res = self.client.post(reverse("webmail:api_send"), {"to": "hong@example.com", "cc": "", "bcc": "b@example.com", "subject": "Re: 안녕", "body": "답장이에요",
		                                                     "in_reply_to": "<m1@example.com>", "reply_folder": "inbox", "reply_uid": "7", "draft_uid": "42"})
		self.assertEqual(res.status_code, 200, res.content)
		sent = mail.outbox[0]
		self.assertEqual((sent.to, sent.bcc), (["hong@example.com"], ["b@example.com"]))
		self.assertEqual(sent.extra_headers["In-Reply-To"], "<m1@example.com>")
		self.assertIn("mjseo@smjgallery.kr", sent.from_email)
		self.assertEqual(SentMail.objects.get().kind, "webmail")
		self.assertIn(("append", "sent", "(\\Seen)"), FakeMailbox.calls)
		self.assertIn(("flag", "inbox", (7,), "\\Answered", True), FakeMailbox.calls)
		self.assertIn(("delete", "drafts", (42,)), FakeMailbox.calls)
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


@override_settings(WEBMAIL_ENABLED=True, WEBMAIL_PASSWORD="x", WEBMAIL_USER="mjseo@smjgallery.kr",
                   EMAIL_BACKEND="webmail.backend.LoggingEmailBackend",
                   WEBMAIL_INNER_EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class WebmailV3Tests(TestCase):
	"""서명·템플릿·주소록·예약 발송·HTML 메일"""

	def setUp(self):
		User = get_user_model()
		self.admin = User.objects.create_superuser("v3-admin", "a@example.com", "pw")
		self.client.force_login(self.admin)
		FakeMailbox.reset()
		patcher = mock.patch("webmail.views.imap.Mailbox", FakeMailbox)
		patcher.start()
		self.addCleanup(patcher.stop)
		patcher2 = mock.patch("webmail.scheduled.imap.Mailbox", FakeMailbox)
		patcher2.start()
		self.addCleanup(patcher2.stop)

	def post_json(self, name, body):
		return self.client.post(reverse(name), json.dumps(body), content_type="application/json")

	def test_state_has_signature_templates_contacts(self):
		data = self.client.get(reverse("webmail:api_state")).json()
		self.assertIn("<b>Minjae Seo", data["signature"])
		self.assertIn("mjseo@smjgallery.kr", data["signature"])
		self.assertEqual(data["contacts"], {})

	def test_signature_saved_sanitized(self):
		res = self.post_json("webmail:api_prefs", {"signature": "<b>민재</b><script>x</script>"})
		self.assertEqual(res.json()["signature"], "<b>민재</b>")
		self.assertEqual(self.client.get(reverse("webmail:api_state")).json()["signature"], "<b>민재</b>")

	def test_contacts(self):
		res = self.post_json("webmail:api_contacts", {"action": "set", "email": "Hey_minj@naver.com", "name": "서민재", "note": "본인"})
		self.assertEqual(res.json()["contacts"]["hey_minj@naver.com"]["name"], "서민재")
		self.assertEqual(self.post_json("webmail:api_contacts", {"action": "set", "email": "bad", "name": "x"}).status_code, 400)
		res = self.post_json("webmail:api_contacts", {"action": "delete", "email": "hey_minj@naver.com"})
		self.assertEqual(res.json()["contacts"], {})

	def test_send_html_has_text_and_html_parts(self):
		res = self.client.post(reverse("webmail:api_send"), {"to": "hong@example.com", "subject": "서식", "body": "굵게 본문", "html": "<p><b>굵게</b> 본문</p><script>x</script>"})
		self.assertEqual(res.status_code, 200, res.content)
		sent = mail.outbox[0]
		self.assertEqual(sent.body, "굵게 본문")
		html = sent.alternatives[0][0]
		self.assertIn("<b>굵게</b>", html)
		self.assertNotIn("<script", html)

	def test_schedule_and_send_due(self):
		from datetime import timedelta

		from django.core.files.uploadedfile import SimpleUploadedFile
		from django.utils import timezone

		from .models import ScheduledMail
		from .scheduled import send_due

		past = (timezone.localtime() - timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M")
		self.assertEqual(self.client.post(reverse("webmail:api_schedule"), {"to": "hong@example.com", "subject": "예약", "body": "x", "send_at": past}).status_code, 400)
		future = (timezone.localtime() + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M")
		res = self.client.post(reverse("webmail:api_schedule"), {"to": "hong@example.com", "subject": "예약", "body": "글자", "html": "<p>글자</p>", "send_at": future,
		                                                         "attachments": SimpleUploadedFile("a.txt", b"hello", content_type="text/plain"), "draft_uid": "9"})
		self.assertEqual(res.status_code, 200, res.content)
		item = ScheduledMail.objects.get()
		self.assertEqual((item.status, item.attachments.count()), ("pending", 1))
		self.assertIn(("delete", "drafts", (9,)), FakeMailbox.calls)
		self.assertEqual(send_due(timezone.now()), 0)  # 아직 때가 아님
		self.assertEqual(send_due(timezone.now() + timedelta(hours=2)), 1)
		item.refresh_from_db()
		self.assertEqual(item.status, "sent")
		self.assertEqual(len(mail.outbox), 1)
		self.assertEqual(mail.outbox[0].attachments[0][0], "a.txt")
		self.assertIn(("append", "sent", "(\\Seen)"), FakeMailbox.calls)
		# 취소
		res = self.client.post(reverse("webmail:api_schedule"), {"to": "hong@example.com", "subject": "둘", "body": "x", "send_at": future})
		sid = res.json()["id"]
		self.assertEqual(self.post_json("webmail:api_schedule", {"action": "cancel", "id": sid}).status_code, 200)
		self.assertEqual(ScheduledMail.objects.get(id=sid).status, "cancelled")
		self.assertEqual(self.post_json("webmail:api_schedule", {"action": "cancel", "id": sid}).status_code, 400)


@override_settings(WEBMAIL_ENABLED=True, WEBMAIL_PASSWORD="x", WEBMAIL_USER="mjseo@smjgallery.kr")
class AppPasswordTests(TestCase):
	def setUp(self):
		import tempfile

		User = get_user_model()
		self.admin = User.objects.create_superuser("ap-admin", "a@example.com", "pw")
		self.client.force_login(self.admin)
		self.tmp = tempfile.mkdtemp()
		patcher = mock.patch("webmail.views.imap.Mailbox", FakeMailbox)
		patcher.start()
		self.addCleanup(patcher.stop)
		FakeMailbox.reset()
		self.override = override_settings(WEBMAIL_APP_PASSWORD_FILE=f"{self.tmp}/mail/app_passwords")
		self.override.enable()
		self.addCleanup(self.override.disable)

	def test_ssha512_matches_dovecot_format(self):
		import base64
		import hashlib

		from .models import ssha512

		h = ssha512("secret", salt=b"0123456789abcdef")
		self.assertTrue(h.startswith("{SSHA512}"))
		raw = base64.b64decode(h[len("{SSHA512}"):])
		self.assertEqual(raw[-16:], b"0123456789abcdef")
		self.assertEqual(raw[:-16], hashlib.sha512(b"secret" + b"0123456789abcdef").digest())

	def test_create_writes_file_and_delete_removes(self):
		import os
		from pathlib import Path

		from .models import AppPassword

		res = self.client.post(reverse("webmail:api_app_passwords"), json.dumps({"action": "create", "label": "맥북 Mail"}), content_type="application/json")
		self.assertEqual(res.status_code, 200, res.content)
		data = res.json()
		self.assertEqual(data["login"], "mjseo+mail@smjgallery.kr")  # 한글은 빠지고 영문만 slug 로
		self.assertRegex(data["password"], r"^[0-9a-f]{4}(-[0-9a-f]{4}){3}$")
		res2 = self.client.post(reverse("webmail:api_app_passwords"), json.dumps({"action": "create", "label": "iPhone 15"}), content_type="application/json").json()
		self.assertEqual(res2["login"], "mjseo+iphone-15@smjgallery.kr")
		path = Path(self.tmp) / "mail" / "app_passwords"
		lines = path.read_text().splitlines()
		self.assertEqual(len(lines), 2)
		self.assertTrue(lines[0].startswith("mjseo+mail@smjgallery.kr:{SSHA512}"))
		self.assertTrue(lines[0].endswith(":::::::user=mjseo@smjgallery.kr"))
		self.assertEqual(oct(os.stat(path).st_mode & 0o777), "0o640")
		state = self.client.get(reverse("webmail:api_state")).json()
		self.assertEqual([a["label"] for a in state["app_passwords"]], ["맥북 Mail", "iPhone 15"])
		first = AppPassword.objects.get(label="맥북 Mail")
		self.client.post(reverse("webmail:api_app_passwords"), json.dumps({"action": "delete", "id": first.id}), content_type="application/json")
		self.assertEqual(len(path.read_text().splitlines()), 1)
		self.assertEqual(self.client.post(reverse("webmail:api_app_passwords"), json.dumps({"action": "create", "label": ""}), content_type="application/json").status_code, 400)
