"""웹메일 (/mail/, 관리자 전용) — 화면 하나 + JSON API. 오른쪽 아래 떠 있는 패널도 같은 API 를 씀."""

import json
import re
from datetime import datetime
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


class _ApiError(Exception):
	def __init__(self, message, status=400):
		super().__init__(message)
		self.status = status


def _mailbox():
	try:
		return imap.Mailbox()
	except imap.WebmailError as exc:
		raise _ApiError(str(exc), 503)


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


def _folder_key(value):
	key = (value or "inbox").strip()
	if key in imap.FOLDER_BY_KEY:
		return key
	if key.startswith(imap.LABEL_PREFIX) and imap.LABEL_NAME_RE.match(key[len(imap.LABEL_PREFIX):]):
		return key
	raise _ApiError("없는 폴더예요")


def _folder(request):
	return _folder_key(request.GET.get("folder") or request.POST.get("folder"))


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


def _list_params(request):
	"""목록·이전/다음 메일에 같이 쓰는 검색 조건."""
	g = request.GET
	filt = g.get("filter") or "all"
	if filt not in imap.FILTERS:
		filt = "all"
	sort = "oldest" if g.get("sort") == "oldest" else "newest"
	adv = {}
	for key in ("from", "to", "subject", "text"):
		val = (g.get(key) or "").strip()[:200]
		if val:
			adv[key] = val
	for key in ("since", "before"):
		val = (g.get(key) or "").strip()
		if val:
			try:
				adv[key] = datetime.strptime(val, "%Y-%m-%d").date()
			except ValueError:
				raise _ApiError("날짜는 YYYY-MM-DD 로")
	return {"query": (g.get("q") or "").strip()[:200], "filter": filt, "sort": sort, "advanced": adv}


@admin_view
def index(request):
	compose_to = (request.GET.get("to") or "").strip()[:200]
	return render(request, "webmail/index.html", {
		"mail_user": settings.WEBMAIL_USER,
		"enabled": settings.WEBMAIL_ENABLED,
		"hide_mail_widget": True,
		"compose_to": compose_to if _EMAIL_RE.match(compose_to) else "",
		"from_name": settings.WEBMAIL_FROM_NAME,
	})


@_api
@require_GET
def api_state(request):
	with _mailbox() as box:
		return JsonResponse({"ok": True, "folders": box.folder_status(), "user": settings.WEBMAIL_USER, "from_name": settings.WEBMAIL_FROM_NAME})


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
	params = _list_params(request)
	with _mailbox() as box:
		data = box.list(folder, page=page, per_page=30, **params)
	for item in data["items"]:
		item["group"] = imap.date_group(item.get("date"))
	data.update({"ok": True, "folder": folder, "filter": params["filter"], "sort": params["sort"]})
	return JsonResponse(data)


@_api
@require_GET
def api_message(request):
	folder, uid = _folder(request), _uid(request.GET.get("uid"))
	show_images = request.GET.get("images") == "1"
	params = _list_params(request)
	with _mailbox() as box:
		msg = box.message(folder, uid)
		if not request.GET.get("keep_unread"):
			box.set_flag(folder, [uid], "\\Seen", True)
		try:
			msg["prev_uid"], msg["next_uid"] = box.neighbors(folder, uid, **params)
		except imap.WebmailError:
			msg["prev_uid"], msg["next_uid"] = None, None
	if msg["html"]:
		body = sanitize_html(msg["html"], show_images=show_images)
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
	msg["raw_url"] = _raw_url(folder, uid)
	msg["ok"] = True
	return JsonResponse(msg)


def _attachment_url(folder, uid, index):
	from django.urls import reverse
	from urllib.parse import quote

	return f"{reverse('webmail:attachment')}?folder={quote(folder)}&uid={uid}&i={index}"


def _raw_url(folder, uid):
	from django.urls import reverse
	from urllib.parse import quote

	return f"{reverse('webmail:raw')}?folder={quote(folder)}&uid={uid}"


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


@admin_view
def raw(request):
	"""원본 보기 (헤더 포함, 글자 그대로)."""
	try:
		folder, uid = _folder(request), _uid(request.GET.get("uid"))
		with imap.Mailbox() as box:
			data = box.fetch_raw(folder, uid)
	except (_ApiError, imap.WebmailError):
		raise Http404("메일을 찾을 수 없어요")
	res = HttpResponse(data, content_type="text/plain; charset=utf-8")
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
	folder = _folder_key(payload.get("folder"))
	action = payload.get("action")
	with _mailbox() as box:
		if action == "empty":
			if folder not in ("junk", "trash"):
				raise _ApiError("스팸·휴지통만 비울 수 있어요")
			n = box.empty(folder)
			return JsonResponse({"ok": True, "unread": box.unread_count(), "count": n})
		uids = [_uid(u) for u in (payload.get("uids") or [])][:200]
		if not uids:
			raise _ApiError("고른 메일이 없어요")
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
			to = _folder_key(payload.get("to"))
			if to == folder:
				raise _ApiError("이미 그 폴더예요")
			box.move(folder, uids, to)
		else:
			raise _ApiError("모르는 동작이에요")
		unread = box.unread_count()
	return JsonResponse({"ok": True, "unread": unread})


@_api
@require_POST
def api_labels(request):
	"""라벨(사용자 폴더) 만들기·이름 바꾸기·지우기."""
	try:
		payload = json.loads(request.body or b"{}")
	except ValueError:
		raise _ApiError("JSON 이 이상해요")
	action = payload.get("action")
	name = (payload.get("name") or "").strip()
	with _mailbox() as box:
		if action == "create":
			key = box.create_label(name)
		elif action == "rename":
			old = _folder_key(payload.get("folder"))
			if not old.startswith(imap.LABEL_PREFIX):
				raise _ApiError("기본 폴더는 이름을 바꿀 수 없어요")
			key = box.rename_label(old[len(imap.LABEL_PREFIX):], name)
		elif action == "delete":
			old = _folder_key(payload.get("folder"))
			if not old.startswith(imap.LABEL_PREFIX):
				raise _ApiError("기본 폴더는 지울 수 없어요")
			box.delete_label(old[len(imap.LABEL_PREFIX):])
			key = None
		else:
			raise _ApiError("모르는 동작이에요")
		folders = box.folder_status()
	return JsonResponse({"ok": True, "key": key, "folders": folders})


def _build_message(request):
	to = _addresses(request.POST.get("to"))
	cc = _addresses(request.POST.get("cc"))
	bcc = _addresses(request.POST.get("bcc"))
	subject = (request.POST.get("subject") or "").strip()[:300]
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
	msg = EmailMessage(subject or "(제목 없음)", body, from_email, to, cc=cc, bcc=bcc, headers=headers)
	for f in files:
		msg.attach(f.name, f.read(), f.content_type or "application/octet-stream")
	return msg, to


@_api
@require_POST
def api_draft(request):
	"""임시 보관: Drafts 에 저장(전에 저장한 초안은 지움). 받는 사람이 비어도 저장."""
	post = request.POST.copy()
	msg, _to = _build_message_lenient(request)
	old = (post.get("draft_uid") or "").strip()
	with _mailbox() as box:
		uid = box.append("drafts", msg.message().as_bytes(), "(\\Seen \\Draft)")
		if old.isdigit() and int(old) != uid:
			try:
				box.delete("drafts", [int(old)])
			except imap.WebmailError:
				pass
	return JsonResponse({"ok": True, "uid": uid})


def _build_message_lenient(request):
	"""초안용: 주소가 비어 있거나 틀려도 그대로 둠."""
	to = [a.strip() for a in re.split(r"[,;\n]", request.POST.get("to") or "") if a.strip()]
	cc = [a.strip() for a in re.split(r"[,;\n]", request.POST.get("cc") or "") if a.strip()]
	bcc = [a.strip() for a in re.split(r"[,;\n]", request.POST.get("bcc") or "") if a.strip()]
	from_email = formataddr((settings.WEBMAIL_FROM_NAME, settings.WEBMAIL_USER))
	msg = EmailMessage((request.POST.get("subject") or "").strip()[:300], request.POST.get("body") or "", from_email, to, cc=cc, bcc=bcc,
	                   headers={"X-MJ-Draft": "1"})
	return msg, to


@_api
@require_POST
def api_send(request):
	msg, to = _build_message(request)
	if not to:
		raise _ApiError("받는 사람을 적어 주세요")
	try:
		sent = msg.send(fail_silently=False)
	except Exception as exc:  # noqa: BLE001
		raise _ApiError(f"보내지 못했어요: {exc}", 502)
	if not sent:
		raise _ApiError("보내지 못했어요", 502)

	# 보낸 편지함에 사본, 답장이면 원본에 답장 표시, 초안이었으면 초안 삭제
	with _mailbox() as box:
		box.append("sent", msg.message().as_bytes())
		reply_folder, reply_uid = request.POST.get("reply_folder"), request.POST.get("reply_uid")
		if reply_folder and reply_uid:
			try:
				box.set_flag(_folder_key(reply_folder), [_uid(reply_uid)], "\\Answered", True)
			except (_ApiError, imap.WebmailError):
				pass
		draft_uid = (request.POST.get("draft_uid") or "").strip()
		if draft_uid.isdigit():
			try:
				box.delete("drafts", [int(draft_uid)])
			except imap.WebmailError:
				pass
	return JsonResponse({"ok": True})
