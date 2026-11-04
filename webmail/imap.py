"""Dovecot(IMAP) 에 붙어 메일함을 읽고 다루는 얇은 클라이언트.

폴더 이름은 설치 스크립트의 Dovecot 설정(Drafts·Junk·Sent·Trash)과 같다.
모든 함수는 UID 기준. 연결은 요청마다 열고 닫는다(웹메일은 관리자 한 명만 쓰니 충분).
"""

import email
import imaplib
import re
import socket
import ssl
from dataclasses import dataclass, field
from email import policy
from email.header import decode_header, make_header
from email.utils import getaddresses, parsedate_to_datetime

from django.conf import settings
from django.utils import timezone

FOLDERS = [
	("inbox", "INBOX", "받은 편지함", "📥"),
	("sent", "Sent", "보낸 편지함", "📤"),
	("drafts", "Drafts", "임시 보관함", "📝"),
	("junk", "Junk", "스팸", "🚫"),
	("trash", "Trash", "휴지통", "🗑"),
]
FOLDER_BY_KEY = {k: name for k, name, _l, _i in FOLDERS}
KEY_BY_FOLDER = {name: k for k, name, _l, _i in FOLDERS}


class WebmailError(Exception):
	pass


class _IMAP4_SNI(imaplib.IMAP4_SSL):
	"""127.0.0.1 로 붙으면서 인증서는 mail.<도메인> 이름으로 확인."""

	def __init__(self, host, port, ssl_context, tls_name, timeout):
		self._tls_name = tls_name
		super().__init__(host, port, ssl_context=ssl_context, timeout=timeout)

	def _create_socket(self, timeout):
		sock = socket.create_connection((self.host, self.port), timeout)
		return self.ssl_context.wrap_socket(sock, server_hostname=self._tls_name)


def _decode(value) -> str:
	if value is None:
		return ""
	try:
		return str(make_header(decode_header(str(value))))
	except Exception:  # noqa: BLE001 — 깨진 헤더는 그대로
		return str(value)


def _addr_list(value):
	if not value:
		return []
	out = []
	for name, addr in getaddresses([str(value)]):
		out.append({"name": _decode(name), "email": addr})
	return out


def _addr_text(items):
	return ", ".join(f"{a['name']} <{a['email']}>" if a["name"] else a["email"] for a in items)


def _date(value):
	try:
		dt = parsedate_to_datetime(str(value))
	except Exception:  # noqa: BLE001
		return None
	if dt is None:
		return None
	if timezone.is_naive(dt):
		dt = timezone.make_aware(dt, timezone.utc)
	return timezone.localtime(dt)


_UID_RE = re.compile(rb"UID (\d+)")
_FLAGS_RE = re.compile(rb"FLAGS \(([^)]*)\)")
_SIZE_RE = re.compile(rb"RFC822.SIZE (\d+)")


@dataclass
class Attachment:
	index: int
	filename: str
	content_type: str
	size: int
	content_id: str = ""
	inline: bool = False
	data: bytes = field(default=b"", repr=False)


def _walk_parts(msg):
	"""본문(text/html) 과 첨부 목록 뽑기. 인덱스는 walk() 순서."""
	text, html, attachments = "", "", []
	for idx, part in enumerate(msg.walk()):
		if part.is_multipart():
			continue
		ctype = part.get_content_type()
		disp = (part.get("Content-Disposition") or "").lower()
		filename = part.get_filename()
		cid = (part.get("Content-ID") or "").strip("<>")
		is_attachment = "attachment" in disp or (filename and ctype not in ("text/plain", "text/html")) or (cid and ctype.startswith("image/"))
		if is_attachment:
			payload = part.get_payload(decode=True) or b""
			attachments.append(Attachment(idx, _decode(filename) or f"part-{idx}", ctype, len(payload), cid, "inline" in disp or bool(cid)))
			continue
		if ctype == "text/plain" and not text:
			text = _part_text(part)
		elif ctype == "text/html" and not html:
			html = _part_text(part)
	return text, html, attachments


def _part_text(part) -> str:
	payload = part.get_payload(decode=True) or b""
	charset = part.get_content_charset() or "utf-8"
	for enc in (charset, "utf-8", "euc-kr", "cp949", "latin-1"):
		try:
			return payload.decode(enc)
		except (LookupError, UnicodeDecodeError):
			continue
	return payload.decode("utf-8", "replace")


class Mailbox:
	def __init__(self):
		if not settings.WEBMAIL_ENABLED:
			raise WebmailError("웹메일이 꺼져 있어요 (.env 의 WEBMAIL_PASSWORD)")
		ctx = ssl.create_default_context()
		try:
			self.conn = _IMAP4_SNI(settings.WEBMAIL_IMAP_HOST, settings.WEBMAIL_IMAP_PORT, ctx, settings.WEBMAIL_IMAP_TLS_NAME, timeout=15)
			self.conn.login(settings.WEBMAIL_USER, settings.WEBMAIL_PASSWORD)
		except (OSError, imaplib.IMAP4.error) as exc:
			raise WebmailError(f"메일 서버에 연결하지 못했어요: {exc}") from exc

	def close(self):
		try:
			self.conn.logout()
		except Exception:  # noqa: BLE001
			pass

	def __enter__(self):
		return self

	def __exit__(self, *exc):
		self.close()

	# ── 폴더 ──
	def _select(self, folder, readonly=True):
		name = FOLDER_BY_KEY.get(folder, folder)
		typ, data = self.conn.select(f'"{name}"', readonly=readonly)
		if typ != "OK":
			raise WebmailError(f"폴더를 열 수 없어요: {folder}")
		return int(data[0] or 0)

	def folder_status(self):
		"""폴더별 (전체, 안 읽음)."""
		out = []
		for key, name, label, icon in FOLDERS:
			total = unseen = 0
			typ, data = self.conn.status(f'"{name}"', "(MESSAGES UNSEEN)")
			if typ == "OK" and data and data[0]:
				m = re.search(rb"MESSAGES (\d+) UNSEEN (\d+)", data[0])
				if m:
					total, unseen = int(m.group(1)), int(m.group(2))
			out.append({"key": key, "label": label, "icon": icon, "total": total, "unseen": unseen})
		return out

	def unread_count(self):
		typ, data = self.conn.status('"INBOX"', "(UNSEEN)")
		m = re.search(rb"UNSEEN (\d+)", data[0]) if typ == "OK" and data and data[0] else None
		return int(m.group(1)) if m else 0

	# ── 목록 ──
	def search_uids(self, folder, query=""):
		self._select(folder)
		if query:
			self.conn.literal = query.encode("utf-8")
			typ, data = self.conn.uid("SEARCH", "CHARSET", "UTF-8", "TEXT")
		else:
			typ, data = self.conn.uid("SEARCH", None, "ALL")
		if typ != "OK":
			return []
		return [int(u) for u in (data[0] or b"").split()]

	def list(self, folder, page=1, per_page=30, query=""):
		uids = self.search_uids(folder, query)
		total = len(uids)
		uids = uids[::-1]  # 최신이 위
		start = (page - 1) * per_page
		chunk = uids[start:start + per_page]
		items = []
		if chunk:
			typ, data = self.conn.uid("FETCH", ",".join(str(u) for u in chunk), "(FLAGS RFC822.SIZE BODY.PEEK[HEADER.FIELDS (FROM TO SUBJECT DATE)])")
			if typ == "OK":
				items = self._parse_summaries(data, folder)
		return {"items": items, "total": total, "page": page, "pages": max(1, (total + per_page - 1) // per_page)}

	def _parse_summaries(self, data, folder):
		rows = {}
		for item in data:
			if not isinstance(item, tuple) or len(item) < 2:
				continue
			meta, header = item[0], item[1]
			m = _UID_RE.search(meta)
			if not m:
				continue
			uid = int(m.group(1))
			fm = _FLAGS_RE.search(meta)
			flags = fm.group(1) if fm else b""
			size = int(_SIZE_RE.search(meta).group(1)) if _SIZE_RE.search(meta) else 0
			msg = email.message_from_bytes(header, policy=policy.compat32)
			frm = _addr_list(msg.get("From"))
			to = _addr_list(msg.get("To"))
			dt = _date(msg.get("Date"))
			rows[uid] = {
				"uid": uid, "folder": folder,
				"subject": _decode(msg.get("Subject")) or "(제목 없음)",
				"from": frm[0] if frm else {"name": "", "email": ""},
				"from_text": _addr_text(frm), "to_text": _addr_text(to),
				"date": dt.isoformat() if dt else "", "date_text": _date_text(dt),
				"seen": b"\\Seen" in flags, "flagged": b"\\Flagged" in flags, "answered": b"\\Answered" in flags,
				"size": size,
			}
		# FETCH 결과는 순서가 섞일 수 있어 uid 내림차순으로
		return [rows[u] for u in sorted(rows, reverse=True)]

	# ── 한 통 ──
	def fetch_raw(self, folder, uid):
		self._select(folder)
		typ, data = self.conn.uid("FETCH", str(uid), "(BODY.PEEK[])")
		if typ != "OK" or not data or not isinstance(data[0], tuple):
			raise WebmailError("메일을 찾을 수 없어요")
		return data[0][1]

	def message(self, folder, uid):
		raw = self.fetch_raw(folder, uid)
		msg = email.message_from_bytes(raw, policy=policy.compat32)
		text, html, attachments = _walk_parts(msg)
		frm, to, cc = _addr_list(msg.get("From")), _addr_list(msg.get("To")), _addr_list(msg.get("Cc"))
		dt = _date(msg.get("Date"))
		return {
			"uid": uid, "folder": folder,
			"subject": _decode(msg.get("Subject")) or "(제목 없음)",
			"from": frm[0] if frm else {"name": "", "email": ""}, "from_text": _addr_text(frm),
			"to": to, "to_text": _addr_text(to), "cc": cc, "cc_text": _addr_text(cc),
			"reply_to": _addr_text(_addr_list(msg.get("Reply-To"))) or _addr_text(frm),
			"date": dt.isoformat() if dt else "", "date_text": _date_text(dt, long=True),
			"message_id": (msg.get("Message-ID") or "").strip(),
			"references": (msg.get("References") or "").strip(),
			"text": text, "html": html,
			"attachments": [{"index": a.index, "filename": a.filename, "content_type": a.content_type, "size": a.size,
			                 "content_id": a.content_id, "inline": a.inline} for a in attachments],
		}

	def attachment(self, folder, uid, index):
		raw = self.fetch_raw(folder, uid)
		msg = email.message_from_bytes(raw, policy=policy.compat32)
		for idx, part in enumerate(msg.walk()):
			if idx == index and not part.is_multipart():
				return Attachment(idx, _decode(part.get_filename()) or f"part-{idx}", part.get_content_type(), 0,
				                  (part.get("Content-ID") or "").strip("<>"), False, part.get_payload(decode=True) or b"")
		raise WebmailError("첨부를 찾을 수 없어요")

	# ── 동작 ──
	def set_flag(self, folder, uids, flag, on=True):
		self._select(folder, readonly=False)
		self.conn.uid("STORE", ",".join(str(u) for u in uids), "+FLAGS" if on else "-FLAGS", f"({flag})")

	def move(self, folder, uids, to_folder):
		self._select(folder, readonly=False)
		dest = FOLDER_BY_KEY.get(to_folder, to_folder)
		ids = ",".join(str(u) for u in uids)
		typ, _ = self.conn.uid("MOVE", ids, f'"{dest}"')
		if typ != "OK":  # MOVE 를 모르는 서버면 복사 + 삭제 표시
			self.conn.uid("COPY", ids, f'"{dest}"')
			self.conn.uid("STORE", ids, "+FLAGS", "(\\Deleted)")
			self.conn.expunge()

	def delete(self, folder, uids):
		"""휴지통으로. 이미 휴지통이면 완전히 지움."""
		if folder == "trash":
			self._select(folder, readonly=False)
			self.conn.uid("STORE", ",".join(str(u) for u in uids), "+FLAGS", "(\\Deleted)")
			self.conn.expunge()
		else:
			self.move(folder, uids, "trash")

	def append(self, folder, raw_bytes, flags="(\\Seen)"):
		name = FOLDER_BY_KEY.get(folder, folder)
		self.conn.append(f'"{name}"', flags, imaplib.Time2Internaldate(timezone.now().timestamp()), raw_bytes)


def _date_text(dt, long=False):
	if not dt:
		return ""
	now = timezone.localtime()
	if long:
		return dt.strftime("%Y.%m.%d %H:%M")
	if dt.date() == now.date():
		return dt.strftime("%H:%M")
	if dt.year == now.year:
		return dt.strftime("%m.%d")
	return dt.strftime("%Y.%m.%d")
