"""웹메일 (/mail/, 관리자 전용) — 화면 하나 + JSON API. 오른쪽 아래 떠 있는 패널도 같은 API 를 씀."""

import json
import re
from datetime import datetime
from email.utils import formataddr

from django.conf import settings
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET, require_POST

from studio.views.common import admin_view

from . import diagnose, dmarc, imap
from .models import AppPassword, MailContact, ScheduledAttachment, ScheduledMail, WebmailPref, write_app_password_file
from .sanitize import sanitize_html, text_to_html
from .scheduled import after_send, build_message
from main.jsonbody import loads_object

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
		folders = box.folder_status()
	return JsonResponse({"ok": True, "folders": folders, "user": settings.WEBMAIL_USER, "from_name": settings.WEBMAIL_FROM_NAME,
	                     "signature": WebmailPref.get().signature, "contacts": _contacts_map(), "scheduled": _scheduled_list(),
	                     "app_passwords": _app_password_list(), "imap_host": settings.WEBMAIL_IMAP_TLS_NAME})


def _app_password_list():
	from django.utils import timezone

	return [{"id": a.id, "label": a.label, "login": a.login, "created": timezone.localtime(a.created_at).strftime("%Y.%m.%d")} for a in AppPassword.objects.all()]


@_api
@require_POST
def api_app_passwords(request):
	"""앱 비밀번호 만들기(평문은 이 응답에만)·지우기."""
	try:
		payload = loads_object(request.body)
	except ValueError:
		raise _ApiError("JSON 이 이상해요")
	action = payload.get("action")
	if action == "create":
		label = (payload.get("label") or "").strip()
		if not label:
			raise _ApiError("기기 이름을 적어 주세요 (예: 맥북 Mail)")
		if AppPassword.objects.count() >= 20:
			raise _ApiError("앱 비밀번호는 20개까지예요. 안 쓰는 걸 지워 주세요")
		try:
			obj, plain = AppPassword.create_for(label)
		except OSError as exc:
			raise _ApiError(f"비밀번호 파일을 쓰지 못했어요: {exc}", 500)
		return JsonResponse({"ok": True, "login": obj.login, "password": plain, "app_passwords": _app_password_list()})
	if action == "delete":
		# 파일 쓰기가 실패하면 삭제도 되돌림 (화면에선 지워졌는데 Dovecot 파일에 남아 계속 로그인되던 것)
		from django.db import transaction
		try:
			with transaction.atomic():
				AppPassword.objects.filter(id=payload.get("id")).delete()
				write_app_password_file()
		except OSError as exc:
			raise _ApiError(f"비밀번호 파일을 쓰지 못해 지우지 않았어요: {exc}", 500)
		return JsonResponse({"ok": True, "app_passwords": _app_password_list()})
	raise _ApiError("모르는 동작이에요")


def _contacts_map():
	return {c.email: {"name": c.name, "note": c.note} for c in MailContact.objects.all()}


def _scheduled_list():
	from django.utils import timezone

	rows = ScheduledMail.objects.exclude(status=ScheduledMail.STATUS_CANCELLED).order_by("-send_at")[:50]
	return [{"id": r.id, "to": r.to, "subject": r.subject, "send_at": timezone.localtime(r.send_at).strftime("%Y.%m.%d %H:%M"),
	         "status": r.status, "status_text": r.get_status_display(), "error": r.error} for r in rows]


@_api
@require_POST
def api_prefs(request):
	"""서명 저장."""
	try:
		payload = loads_object(request.body)
	except ValueError:
		raise _ApiError("JSON 이 이상해요")
	pref = WebmailPref.get()
	pref.signature = sanitize_html((payload.get("signature") or "").strip()[:4000], show_images=True)
	pref.save(update_fields=["signature", "updated_at"])
	return JsonResponse({"ok": True, "signature": pref.signature})


@_api
@require_POST
def api_contacts(request):
	try:
		payload = loads_object(request.body)
	except ValueError:
		raise _ApiError("JSON 이 이상해요")
	action = payload.get("action")
	email = (payload.get("email") or "").strip().lower()[:254]
	if not _EMAIL_RE.match(email):
		raise _ApiError("주소가 이상해요")
	if action == "set":
		name = (payload.get("name") or "").strip()[:80]
		if not name:
			raise _ApiError("이름을 적어 주세요")
		MailContact.objects.update_or_create(email=email, defaults={"name": name, "note": (payload.get("note") or "").strip()[:200]})
	elif action == "delete":
		MailContact.objects.filter(email=email).delete()
	else:
		raise _ApiError("모르는 동작이에요")
	return JsonResponse({"ok": True, "contacts": _contacts_map()})


@_api
@require_POST
def api_schedule(request):
	"""예약 발송 등록(multipart, 쓰기 폼 + send_at) / 취소(JSON {action: cancel, id})."""
	if request.content_type and request.content_type.startswith("application/json"):
		try:
			payload = loads_object(request.body)
		except ValueError:
			raise _ApiError("JSON 이 이상해요")
		if payload.get("action") != "cancel":
			raise _ApiError("모르는 동작이에요")
		n = ScheduledMail.objects.filter(id=payload.get("id"), status=ScheduledMail.STATUS_PENDING).update(status=ScheduledMail.STATUS_CANCELLED)
		if not n:
			raise _ApiError("취소할 수 있는 예약이 아니에요")
		return JsonResponse({"ok": True, "scheduled": _scheduled_list()})
	from django.utils import timezone
	from django.utils.dateparse import parse_datetime

	to = _addresses(request.POST.get("to"))
	cc = _addresses(request.POST.get("cc"))
	bcc = _addresses(request.POST.get("bcc"))
	if not to:
		raise _ApiError("받는 사람을 적어 주세요")
	raw_at = (request.POST.get("send_at") or "").strip()
	send_at = parse_datetime(raw_at) if raw_at else None
	if not send_at:
		raise _ApiError("보낼 시각을 골라 주세요")
	if timezone.is_naive(send_at):
		send_at = timezone.make_aware(send_at, timezone.get_current_timezone())
	if send_at <= timezone.now():
		raise _ApiError("보낼 시각은 지금보다 뒤여야 해요")
	files = request.FILES.getlist("attachments")
	if sum(f.size for f in files) > settings.WEBMAIL_ATTACHMENT_MAX_BYTES:
		raise _ApiError(f"첨부는 모두 합쳐 {settings.WEBMAIL_ATTACHMENT_MAX_BYTES // (1024 * 1024)}MB 까지예요")
	reply_uid = (request.POST.get("reply_uid") or "").strip()
	item = ScheduledMail.objects.create(
		to=", ".join(to), cc=", ".join(cc), bcc=", ".join(bcc), subject=(request.POST.get("subject") or "").strip()[:300], body=request.POST.get("body") or "",
		html=request.POST.get("html") or "",
		in_reply_to=(request.POST.get("in_reply_to") or "").strip()[:300], references=(request.POST.get("references") or "").strip(),
		reply_folder=(request.POST.get("reply_folder") or "")[:100], reply_uid=int(reply_uid) if reply_uid.isdigit() else None, send_at=send_at,
	)
	for f in files:
		ScheduledAttachment.objects.create(mail=item, file=f, filename=f.name[:255], content_type=(f.content_type or "")[:120], size=f.size)
	draft_uid = (request.POST.get("draft_uid") or "").strip()
	if draft_uid.isdigit():
		try:
			with _mailbox() as box:
				box.delete("drafts", [int(draft_uid)])
		except (_ApiError, imap.WebmailError):
			pass
	return JsonResponse({"ok": True, "id": item.id, "send_at": timezone.localtime(send_at).strftime("%Y.%m.%d %H:%M"), "scheduled": _scheduled_list()})


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
		att["dmarc"] = dmarc.looks_like_report(att["filename"], att["content_type"])
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


@_api
@require_GET
def api_diagnose(request):
	"""받은 메일 진단: SPF·DKIM·DMARC·전달 경로·피싱 단서 (DKIM 은 dkimpy 로 직접 검증)."""
	folder, uid = _folder(request), _uid(request.GET.get("uid"))
	with _mailbox() as box:
		raw_bytes = box.fetch_raw(folder, uid)
	return JsonResponse({"ok": True, **diagnose.analyze(raw_bytes, verify=request.GET.get("verify") != "0")})


@_api
@require_GET
def api_dmarc(request):
	"""DMARC 집계 보고서 첨부(.zip/.xml.gz/.xml)를 읽어 요약."""
	folder, uid = _folder(request), _uid(request.GET.get("uid"))
	try:
		index = int(request.GET.get("i") or -1)
	except ValueError:
		raise _ApiError("첨부 번호가 이상해요")
	with _mailbox() as box:
		att = box.attachment(folder, uid, index)
	try:
		report = dmarc.parse_report(att.data)
	except dmarc.ReportError as exc:
		raise _ApiError(str(exc))
	return JsonResponse({"ok": True, "filename": att.filename, **report})


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
		payload = loads_object(request.body)
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
		payload = loads_object(request.body)
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
	files = request.FILES.getlist("attachments")
	total = sum(f.size for f in files)
	if total > settings.WEBMAIL_ATTACHMENT_MAX_BYTES:
		raise _ApiError(f"첨부는 모두 합쳐 {settings.WEBMAIL_ATTACHMENT_MAX_BYTES // (1024 * 1024)}MB 까지예요")
	msg = build_message(to, cc, bcc, (request.POST.get("subject") or "").strip()[:300], request.POST.get("body") or "",
	                    (request.POST.get("in_reply_to") or "").strip(), (request.POST.get("references") or "").strip(),
	                    [(f.name, f.read(), f.content_type) for f in files], html=request.POST.get("html") or "")
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
	from django.core.mail import EmailMultiAlternatives

	from_email = formataddr((settings.WEBMAIL_FROM_NAME, settings.WEBMAIL_USER))
	msg = EmailMultiAlternatives((request.POST.get("subject") or "").strip()[:300], request.POST.get("body") or "", from_email, to, cc=cc, bcc=bcc,
	                             headers={"X-MJ-Draft": "1"})
	html = request.POST.get("html") or ""
	if html.strip():
		msg.attach_alternative(sanitize_html(html, show_images=True), "text/html")
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
	reply_folder, reply_uid = (request.POST.get("reply_folder") or ""), (request.POST.get("reply_uid") or "")
	after_send(msg, reply_folder if reply_folder in imap.FOLDER_BY_KEY or reply_folder.startswith(imap.LABEL_PREFIX) else "", int(reply_uid) if reply_uid.isdigit() else None)
	draft_uid = (request.POST.get("draft_uid") or "").strip()
	if draft_uid.isdigit():
		try:
			with _mailbox() as box:
				box.delete("drafts", [int(draft_uid)])
		except (_ApiError, imap.WebmailError):
			pass
	return JsonResponse({"ok": True})
