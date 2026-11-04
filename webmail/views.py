"""웹메일 (/mail/, 관리자 전용) — 화면 하나 + JSON API. 오른쪽 아래 떠 있는 패널도 같은 API 를 씀."""

import json
import re
from email.utils import formataddr, make_msgid

from django.conf import settings
from django.core.mail import EmailMessage
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET, require_POST

from studio.views.common import admin_view

from . import imap
from .sanitize import sanitize_html, text_to_html

_EMAIL_RE = re.compile(r"^[^@\s<>]+@[^@\s<>]+\.[^@\s<>]+$")


def _mailbox():
	try:
		return imap.Mailbox()
	except imap.WebmailError as exc:
		raise _ApiError(str(exc), 503)


class _ApiError(Exception):
	def __init__(self, message, status=400):
		super().__init__(message)
		self.status = status


def _api(view):
	"""API 공통: 관리자만, 오류는 JSON 으로."""

	def wrapped(request, *args, **kwargs):
		try:
			return view(request, *args, **kwargs)
		except _ApiError as exc:
			return JsonResponse({"ok": False, "error": str(exc)}, status=exc.status)
		except imap.WebmailError as exc:
			return JsonResponse({"ok": False, "error": str(exc)}, status=502)

	wrapped.__name__ = view.__name__
	return admin_view(wrapped)


def _folder(request):
	key = (request.GET.get("folder") or request.POST.get("folder") or "inbox").strip()
	if key not in imap.FOLDER_BY_KEY:
		raise _ApiError("없는 폴더예요")
	return key


def _uid(value):
	try:
		uid = int(value)
	except (TypeError, ValueError):
		raise _ApiError("uid 가 이상해요")
	if uid <= 0:
		raise _ApiError("uid 가 이상해요")
	return uid


def _addresses(raw):
	items = [a.strip() for a in re.split(r"[,;\n]", raw or "") if a.strip()]
	for a in items:
		addr = a[a.rfind("<") + 1:a.rfind(">")] if "<" in a and a.endswith(">") else a
		if not _EMAIL_RE.match(addr):
			raise _ApiError(f"주소가 이상해요: {a}")
	return items


@admin_view
def index(request):
	return render(request, "webmail/index.html", {
		"folders": [{"key": k, "label": l, "icon": i} for k, _n, l, i in imap.FOLDERS],
		"mail_user": settings.WEBMAIL_USER,
		"enabled": settings.WEBMAIL_ENABLED,
		"hide_mail_widget": True,
	})


@_api
@require_GET
def api_state(request):
	with _mailbox() as box:
		return JsonResponse({"ok": True, "folders": box.folder_status(), "user": settings.WEBMAIL_USER})


@_api
@require_GET
def api_unread(request):
	if not settings.WEBMAIL_ENABLED:
		return JsonResponse({"ok": True, "unread": 0, "enabled": False})
	with _mailbox() as box:
		return JsonResponse({"ok": True, "unread": box.unread_count(), "enabled": True})


@_api
@require_GET
def api_list(request):
	folder = _folder(request)
	try:
		page = max(1, int(request.GET.get("page") or 1))
	except ValueError:
		page = 1
	query = (request.GET.get("q") or "").strip()[:200]
	with _mailbox() as box:
		data = box.list(folder, page=page, per_page=30, query=query)
	data["ok"] = True
	data["folder"] = folder
	return JsonResponse(data)


@_api
@require_GET
def api_message(request):
	folder, uid = _folder(request), _uid(request.GET.get("uid"))
	show_images = request.GET.get("images") == "1"
	with _mailbox() as box:
		msg = box.message(folder, uid)
		if not request.GET.get("keep_unread"):
			box.set_flag(folder, [uid], "\\Seen", True)
	if msg["html"]:
		body = sanitize_html(msg["html"], show_images=show_images)
		# 본문 안 그림(cid:) → 첨부 주소로
		for att in msg["attachments"]:
			if att["content_id"]:
				body = body.replace(f'cid:{att["content_id"]}', _attachment_url(folder, uid, att["index"]))
		msg["body_html"], msg["is_html"] = body, True
	else:
		msg["body_html"], msg["is_html"] = text_to_html(msg["text"]), False
	msg["has_remote_images"] = "data-src=" in msg["body_html"]
	for att in msg["attachments"]:
		att["url"] = _attachment_url(folder, uid, att["index"])
	msg.pop("html", None)
	msg["ok"] = True
	return JsonResponse(msg)


def _attachment_url(folder, uid, index):
	from django.urls import reverse

	return f"{reverse('webmail:attachment')}?folder={folder}&uid={uid}&i={index}"


@admin_view
def attachment(request):
	try:
		folder, uid, index = _folder(request), _uid(request.GET.get("uid")), int(request.GET.get("i") or -1)
		with imap.Mailbox() as box:
			att = box.attachment(folder, uid, index)
	except (_ApiError, imap.WebmailError, ValueError):
		raise Http404("첨부를 찾을 수 없어요")
	ctype = att.content_type if att.content_type.startswith("image/") else "application/octet-stream"
	res = HttpResponse(att.data, content_type=ctype)
	disp = "inline" if ctype.startswith("image/") else "attachment"
	from urllib.parse import quote

	res["Content-Disposition"] = f"{disp}; filename*=UTF-8''{quote(att.filename)}"
	res["X-Content-Type-Options"] = "nosniff"
	res["Content-Security-Policy"] = "default-src 'none'; sandbox"
	return res


@_api
@require_POST
def api_action(request):
	try:
		payload = json.loads(request.body or b"{}")
	except ValueError:
		raise _ApiError("JSON 이 이상해요")
	folder = payload.get("folder") or "inbox"
	if folder not in imap.FOLDER_BY_KEY:
		raise _ApiError("없는 폴더예요")
	uids = [_uid(u) for u in (payload.get("uids") or [])][:200]
	action = payload.get("action")
	if not uids:
		raise _ApiError("고른 메일이 없어요")
	with _mailbox() as box:
		if action == "seen":
			box.set_flag(folder, uids, "\\Seen", True)
		elif action == "unseen":
			box.set_flag(folder, uids, "\\Seen", False)
		elif action == "flag":
			box.set_flag(folder, uids, "\\Flagged", True)
		elif action == "unflag":
			box.set_flag(folder, uids, "\\Flagged", False)
		elif action == "delete":
			box.delete(folder, uids)
		elif action == "move":
			to = payload.get("to")
			if to not in imap.FOLDER_BY_KEY or to == folder:
				raise _ApiError("옮길 폴더가 이상해요")
			box.move(folder, uids, to)
		else:
			raise _ApiError("모르는 동작이에요")
		unread = box.unread_count()
	return JsonResponse({"ok": True, "unread": unread})


@_api
@require_POST
def api_send(request):
	to = _addresses(request.POST.get("to"))
	cc = _addresses(request.POST.get("cc"))
	if not to:
		raise _ApiError("받는 사람을 적어 주세요")
	subject = (request.POST.get("subject") or "").strip()[:300] or "(제목 없음)"
	body = request.POST.get("body") or ""
	files = request.FILES.getlist("attachments")
	total = sum(f.size for f in files)
	if total > settings.WEBMAIL_ATTACHMENT_MAX_BYTES:
		raise _ApiError(f"첨부는 모두 합쳐 {settings.WEBMAIL_ATTACHMENT_MAX_BYTES // (1024 * 1024)}MB 까지예요")

	from_email = formataddr((settings.WEBMAIL_FROM_NAME, settings.WEBMAIL_USER))
	headers = {"X-MJ-Kind": "webmail", "Message-ID": make_msgid(domain=settings.WEBMAIL_USER.split("@")[-1])}
	in_reply_to = (request.POST.get("in_reply_to") or "").strip()
	if in_reply_to:
		headers["In-Reply-To"] = in_reply_to
		headers["References"] = ((request.POST.get("references") or "").strip() + " " + in_reply_to).strip()
	msg = EmailMessage(subject, body, from_email, to, cc=cc, headers=headers)
	for f in files:
		msg.attach(f.name, f.read(), f.content_type or "application/octet-stream")
	try:
		sent = msg.send(fail_silently=False)
	except Exception as exc:  # noqa: BLE001
		raise _ApiError(f"보내지 못했어요: {exc}", 502)
	if not sent:
		raise _ApiError("보내지 못했어요", 502)

	# 보낸 편지함에 사본, 답장이면 원본에 답장 표시
	with _mailbox() as box:
		box.append("sent", msg.message().as_bytes())
		reply_folder, reply_uid = request.POST.get("reply_folder"), request.POST.get("reply_uid")
		if reply_folder in imap.FOLDER_BY_KEY and reply_uid:
			try:
				box.set_flag(reply_folder, [_uid(reply_uid)], "\\Answered", True)
			except (_ApiError, imap.WebmailError):
				pass
	return JsonResponse({"ok": True})
