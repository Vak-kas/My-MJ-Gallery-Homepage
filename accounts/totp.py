"""TOTP(RFC 6238) — 구글 OTP·Authy 같은 인증 앱과 같은 방식. 외부 패키지 없이 hmac 으로."""

import base64
import hmac
import secrets
import struct
import time
from hashlib import sha1
from urllib.parse import quote

PERIOD = 30
DIGITS = 6


def generate_secret() -> str:
	"""base32 32글자 (160비트)."""
	return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def _code(secret: str, counter: int) -> str:
	key = base64.b32decode(secret.upper() + "=" * (-len(secret) % 8))
	digest = hmac.new(key, struct.pack(">Q", counter), sha1).digest()
	offset = digest[-1] & 0x0F
	value = (struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF) % (10 ** DIGITS)
	return f"{value:0{DIGITS}d}"


def totp(secret: str, at: float | None = None) -> str:
	return _code(secret, int((at if at is not None else time.time()) // PERIOD))


def verify(secret: str, code: str, at: float | None = None, window: int = 1, min_counter: int = 0):
	"""맞으면 그 코드의 counter 를 돌려줌(같은 코드 재사용 방지용), 틀리면 None. 앞뒤 window 칸(기본 ±30초) 허용."""
	code = "".join(ch for ch in (code or "") if ch.isdigit())
	if len(code) != DIGITS:
		return None
	now = int((at if at is not None else time.time()) // PERIOD)
	for delta in range(-window, window + 1):
		counter = now + delta
		if counter <= min_counter:
			continue
		if hmac.compare_digest(_code(secret, counter), code):
			return counter
	return None


def otpauth_uri(secret: str, account: str, issuer: str = "MJ Gallery") -> str:
	return f"otpauth://totp/{quote(issuer)}:{quote(account)}?secret={secret}&issuer={quote(issuer)}&algorithm=SHA1&digits={DIGITS}&period={PERIOD}"


def generate_backup_codes(n: int = 10):
	"""8자리 숫자 코드 n개 (화면에 한 번만 보여 주고 해시로 저장)."""
	return [f"{secrets.randbelow(10 ** 8):08d}" for _ in range(n)]
