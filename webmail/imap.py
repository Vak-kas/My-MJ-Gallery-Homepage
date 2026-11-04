"""Dovecot(IMAP) 에 붙어 메일함을 읽고 다루는 얇은 클라이언트.

기본 폴더(INBOX·Sent·Drafts·Junk·Trash)는 설치 스크립트의 Dovecot 설정과 같고, 그 밖의 폴더는 사용자가 만든 "라벨".
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
SYSTEM_NAMES = set(FOLDER_BY_KEY.values())
# 사용자 폴더(라벨) 키: "f:이름"
LABEL_PREFIX = "f:"
LABEL_NAME_RE = re.compile(r"^[\w가-힣 .\-]{1,40}$")
FILTERS = ("all", "unseen", "flagged", "attach")


class WebmailError(Exception):
	pass


# ── IMAP 변형 UTF-7 (한글 폴더 이름) ──
def mutf7_encode(name: str) -> str:
	out, buf = [], []

	def flush():
		if buf:
			b64 = "".join(buf).encode("utf-16-be")
			import base64

			out.append("&" + base64.b64encode(b64).decode().rstrip("=").replace("/", ",") + "-")
			buf.clear()

	for ch in name:
		if 0x20 <= ord(ch) <= 0x7E:
			flush()
			out.append("&-" if ch == "&" else ch)
		else:
			buf.append(ch)
	flush()
	return "".join(out)


def mutf7_decode(name: str) -> str:
	import base64

	def repl(m):
		chunk = m.group(1)
		if not chunk:
			return "&"
		pad = "=" * (-len(chunk) % 4)
		return base64.b64decode(chunk.replace(",", "/") + pad).decode("utf-16-be", "replace")

	return re.sub(r"&([^-]*)-", repl, name)


def folder_name(key: str) -> str:
	"""키 → IMAP 폴더 이름(서버에 보낼 인코딩 전)."""
	if key in FOLDER_BY_KEY:
		return FOLDER_BY_KEY[key]
	if key.startswith(LABEL_PREFIX):
		return key[len(LABEL_PREFIX):]
	raise WebmailError("없는 폴더예요")


def folder_key(name: str) -> str:
	return KEY_BY_FOLDER.get(name) or (LABEL_PREFIX + name)


def _q(name: str) -> str:
	return '"' + mutf7_encode(name).replace("\\", "\\\\").replace('"', '\\"') + '"'


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
_ATTACH_RE = re.compile(rb'"attachment"|\("name"|\("NAME"|"filename"', re.I)
_PREVIEW_INLINE_RE = re.compile(rb'PREVIEW (?:\(FUZZY\) )?"((?:[^"\\]|\\.)*)"')


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
		typ, data = self.conn.select(_q(folder_name(folder)), readonly=readonly)
		if typ != "OK":
			raise WebmailError(f"폴더를 열 수 없어요: {folder}")
		return int(data[0] or 0)

	def _status(self, name):
		typ, data = self.conn.status(_q(name), "(MESSAGES UNSEEN)")
		if typ == "OK" and data and data[0]:
			m = re.search(rb"MESSAGES (\d+) UNSEEN (\d+)", data[0])
			if m:
				return int(m.group(1)), int(m.group(2))
		return 0, 0

	def list_labels(self):
		"""사용자가 만든 폴더(라벨) 이름 목록 — 기본 폴더 제외."""
		typ, data = self.conn.list('""', "*")
		names = []
		if typ != "OK":
			return names
		for row in data or []:
			if not row:
				continue
			raw = row.decode("utf-8", "replace") if isinstance(row, bytes) else str(row)
			m = re.match(r'\((?P<flags>[^)]*)\) "?(?P<delim>[^" ]*)"? (?P<name>"(?:[^"\\]|\\.)*"|\S+)$', raw)
			if not m:
				continue
			if "\\Noselect" in m.group("flags"):
				continue
			name = m.group("name")
			if name.startswith('"'):
				name = name[1:-1].replace('\\"', '"').replace("\\\\", "\\")
			name = mutf7_decode(name)
			if name in SYSTEM_NAMES or name.upper() == "INBOX":
				continue
			names.append(name)
		return sorted(names, key=str.lower)

	def folder_status(self):
		"""기본 폴더 + 라벨, 각각 (전체, 안 읽음)."""
		out = []
		for key, name, label, icon in FOLDERS:
			total, unseen = self._status(name)
			out.append({"key": key, "label": label, "icon": icon, "total": total, "unseen": unseen, "system": True})
		for name in self.list_labels():
			total, unseen = self._status(name)
			out.append({"key": LABEL_PREFIX + name, "label": name, "icon": "🏷", "total": total, "unseen": unseen, "system": False})
		return out

	def create_label(self, name):
		if not LABEL_NAME_RE.match(name) or name in SYSTEM_NAMES or name.upper() == "INBOX":
			raise WebmailError("라벨 이름은 1~40자(한글·영문·숫자·공백·.-_)이고 기본 폴더 이름은 쓸 수 없어요")
		typ, data = self.conn.create(_q(name))
		if typ != "OK":
			raise WebmailError("라벨을 만들지 못했어요 (이미 있는 이름?)")
		self.conn.subscribe(_q(name))
		return LABEL_PREFIX + name

	def rename_label(self, old, new):
		if not LABEL_NAME_RE.match(new) or new in SYSTEM_NAMES or new.upper() == "INBOX":
			raise WebmailError("라벨 이름이 이상해요")
		if old in SYSTEM_NAMES or old.upper() == "INBOX":
			raise WebmailError("기본 폴더는 이름을 바꿀 수 없어요")
		typ, _ = self.conn.rename(_q(old), _q(new))
		if typ != "OK":
			raise WebmailError("이름을 바꾸지 못했어요")
		self.conn.subscribe(_q(new))
		return LABEL_PREFIX + new

	def delete_label(self, name):
		if name in SYSTEM_NAMES or name.upper() == "INBOX":
			raise WebmailError("기본 폴더는 지울 수 없어요")
		total, _ = self._status(name)
		if total:
			raise WebmailError(f"안에 메일이 {total}통 있어요. 비우거나 옮긴 뒤 지워 주세요")
		try:
			self.conn.unsubscribe(_q(name))
		except imaplib.IMAP4.error:
			pass
		typ, _ = self.conn.delete(_q(name))
		if typ != "OK":
			raise WebmailError("라벨을 지우지 못했어요")

	def unread_count(self):
		return self._status("INBOX")[1]

	# ── 목록 ──
	def search_uids(self, folder, query="", filter="all", advanced=None):
		"""IMAP SEARCH. advanced: {from, to, subject, text, since(date), before(date)}"""
		self._select(folder)
		crit, literals = [], []
		adv = advanced or {}
		if filter == "unseen":
			crit.append("UNSEEN")
		elif filter == "flagged":
			crit.append("FLAGGED")
		elif filter == "attach":  # 표준 검색 키가 없어 멀티파트 헤더로 어림
			crit += ["HEADER", "Content-Type", "multipart/mixed"]
		for key, imap_key in (("from", "FROM"), ("to", "TO"), ("subject", "SUBJECT"), ("text", "TEXT")):
			val = (adv.get(key) or "").strip()
			if val:
				crit.append(imap_key)
				literals.append(val)
		if query:
			crit.append("TEXT")
			literals.append(query)
		for key, imap_key in (("since", "SINCE"), ("before", "BEFORE")):
			val = adv.get(key)
			if val:
				crit += [imap_key, val.strftime("%d-%b-%Y")]
		if not crit:
			crit = ["ALL"]
		if literals:
			# 한글 검색어는 UTF-8 리터럴로 — imaplib 은 마지막 인자 하나만 literal 로 보낼 수 있어 조건을 나눠 교집합
			uids = None
			idx = 0
			plain = [c for c in crit if c not in ("FROM", "TO", "SUBJECT", "TEXT")]
			for c in crit:
				if c in ("FROM", "TO", "SUBJECT", "TEXT"):
					self.conn.literal = literals[idx].encode("utf-8")
					idx += 1
					typ, data = self.conn.uid("SEARCH", "CHARSET", "UTF-8", c)
					found = set(int(u) for u in (data[0] or b"").split()) if typ == "OK" else set()
					uids = found if uids is None else uids & found
			if plain and plain != ["ALL"]:
				typ, data = self.conn.uid("SEARCH", None, *plain)
				found = set(int(u) for u in (data[0] or b"").split()) if typ == "OK" else set()
				uids = found if uids is None else uids & found
			return sorted(uids or [])
		typ, data = self.conn.uid("SEARCH", None, *crit)
		if typ != "OK":
			return []
		return [int(u) for u in (data[0] or b"").split()]

	def list(self, folder, page=1, per_page=30, query="", filter="all", sort="newest", advanced=None):
		uids = self.search_uids(folder, query, filter, advanced)
		total = len(uids)
		if sort != "oldest":
			uids = uids[::-1]
		start = (page - 1) * per_page
		chunk = uids[start:start + per_page]
		items = []
		if chunk:
			ids = ",".join(str(u) for u in chunk)
			typ, data = self.conn.uid("FETCH", ids, "(FLAGS RFC822.SIZE BODYSTRUCTURE BODY.PEEK[HEADER.FIELDS (FROM TO CC SUBJECT DATE)])")
			if typ == "OK":
				rows = self._parse_summaries(data, folder)
				previews = self._previews(ids)
				for r in rows.values():
					r["preview"] = previews.get(r["uid"], "")
				items = [rows[u] for u in chunk if u in rows]
		return {"items": items, "total": total, "page": page, "pages": max(1, (total + per_page - 1) // per_page)}

	def _previews(self, ids):
		"""본문 미리보기(RFC 8970 PREVIEW). 서버가 모르면 빈 값."""
		out = {}
		try:
			typ, data = self.conn.uid("FETCH", ids, "(PREVIEW)")
		except imaplib.IMAP4.error:
			return out
		if typ != "OK":
			return out
		pending_uid = None
		for item in data or []:
			if isinstance(item, tuple):
				m = _UID_RE.search(item[0])
				if m:
					out[int(m.group(1))] = item[1].decode("utf-8", "replace").strip()
			elif isinstance(item, bytes):
				m = _UID_RE.search(item)
				pm = _PREVIEW_INLINE_RE.search(item)
				if m and pm:
					out[int(m.group(1))] = pm.group(1).decode("utf-8", "replace").replace('\\"', '"').strip()
				pending_uid = None
		return out

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
			bs = meta[meta.find(b"BODYSTRUCTURE"):] if b"BODYSTRUCTURE" in meta else b""
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
				"draft": b"\\Draft" in flags,
				"has_attachment": bool(_ATTACH_RE.search(bs)) if bs else False,
				"size": size, "preview": "",
			}
		return rows

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
		bcc = _addr_list(msg.get("Bcc"))
		dt = _date(msg.get("Date"))
		return {
			"uid": uid, "folder": folder,
			"subject": _decode(msg.get("Subject")) or "(제목 없음)",
			"from": frm[0] if frm else {"name": "", "email": ""}, "from_text": _addr_text(frm),
			"to": to, "to_text": _addr_text(to), "cc": cc, "cc_text": _addr_text(cc), "bcc_text": _addr_text(bcc),
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

	def neighbors(self, folder, uid, query="", filter="all", sort="newest", advanced=None):
		"""읽기 화면의 이전/다음 메일 uid."""
		uids = self.search_uids(folder, query, filter, advanced)
		if sort != "oldest":
			uids = uids[::-1]
		if uid not in uids:
			return None, None
		i = uids.index(uid)
		return (uids[i - 1] if i > 0 else None), (uids[i + 1] if i + 1 < len(uids) else None)

	# ── 동작 ──
	def set_flag(self, folder, uids, flag, on=True):
		self._select(folder, readonly=False)
		self.conn.uid("STORE", ",".join(str(u) for u in uids), "+FLAGS" if on else "-FLAGS", f"({flag})")

	def move(self, folder, uids, to_folder):
		self._select(folder, readonly=False)
		dest = _q(folder_name(to_folder))
		ids = ",".join(str(u) for u in uids)
		typ, _ = self.conn.uid("MOVE", ids, dest)
		if typ != "OK":  # MOVE 를 모르는 서버면 복사 + 삭제 표시
			self.conn.uid("COPY", ids, dest)
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

	def empty(self, folder):
		"""폴더 비우기 (스팸·휴지통)."""
		self._select(folder, readonly=False)
		typ, data = self.conn.uid("SEARCH", None, "ALL")
		uids = (data[0] or b"").split() if typ == "OK" else []
		if uids:
			self.conn.uid("STORE", b",".join(uids).decode(), "+FLAGS", "(\\Deleted)")
			self.conn.expunge()
		return len(uids)

	def append(self, folder, raw_bytes, flags="(\\Seen)"):
		typ, data = self.conn.append(_q(folder_name(folder)), flags, imaplib.Time2Internaldate(timezone.now().timestamp()), raw_bytes)
		if typ != "OK":
			raise WebmailError("저장하지 못했어요")
		m = re.search(rb"APPENDUID \d+ (\d+)", data[0] or b"")
		return int(m.group(1)) if m else None


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


def date_group(iso: str) -> str:
	"""목록 묶음: 오늘 · 어제 · 이번 주 · 이번 달 · 이전"""
	if not iso:
		return "이전"
	from datetime import datetime, timedelta

	try:
		dt = timezone.localtime(datetime.fromisoformat(iso))
	except ValueError:
		return "이전"
	today = timezone.localdate()
	d = dt.date()
	if d == today:
		return "오늘"
	if d == today - timedelta(days=1):
		return "어제"
	if d >= today - timedelta(days=today.weekday()):
		return "이번 주"
	if d.year == today.year and d.month == today.month:
		return "이번 달"
	return "이전"
