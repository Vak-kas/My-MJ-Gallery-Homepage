"""가입 봇 거르기 · 같은 IP 반복 가입 제한 · 의심 가입 표시.

- 숨은 칸(website): 사람 눈엔 안 보임 → 채워져 있으면 봇
- JS 확인값(js_check): 페이지의 JS 가 서명된 폼 토큰을 뒤집어 넣음 → JS 를 안 돌리는 봇은 비어 있음
- 폼 토큰(form_token): 서버가 서명한 발급 시각 → 너무 빨리(MIN_SECONDS 안에) 내면 봇
걸린 요청엔 가입된 척 화면만 보여 주고 아무것도 저장하지 않음 (봇이 우회법을 배우지 않게).
"""

import re
import time

from django.core import signing
from django.core.cache import cache

SALT = "accounts.signup.form"
MIN_SECONDS = 3            # 사람이 칸을 다 채우는 데 이보다는 오래 걸림
MAX_AGE = 24 * 60 * 60
RATE_LIMIT = 3             # 한 IP 에서
RATE_WINDOW = 60 * 60      # 1시간에 이만큼까지 가입

HONEYPOT_FIELD = "website"

DISPOSABLE_DOMAINS = {
	"formtests.info", "mailinator.com", "guerrillamail.com", "guerrillamail.net", "sharklasers.com", "grr.la",
	"10minutemail.com", "10minutemail.net", "tempmail.com", "temp-mail.org", "tempmail.net", "tempmailo.com",
	"yopmail.com", "yopmail.net", "trashmail.com", "trashmail.de", "getnada.com", "dispostable.com",
	"maildrop.cc", "mailnesia.com", "mintemail.com", "throwawaymail.com", "fakeinbox.com", "mohmal.com",
	"emailondeck.com", "moakt.com", "tempail.com", "spamgourmet.com", "mailcatch.com", "inboxkitten.com",
	"burnermail.io", "33mail.com", "mytemp.email", "tmpmail.org", "tmpmail.net", "emlpro.com", "emltmp.com",
}
OLD_OR_BOT_UA = re.compile(r"MSIE [1-9]\.|Trident/|bot|crawl|spider|python|curl|wget|go-http|java/|libwww|headless", re.I)
CONSONANT_RUN = re.compile(r"[bcdfghjklmnpqrstvwxyz]{5,}", re.I)
CONSONANT_RUN_ID = re.compile(r"[bcdfghjklmnpqrstvwxyz]{6,}", re.I)  # 아이디는 이니셜이 붙어(jschmidt) 조금 너그럽게
HANGUL = re.compile(r"[가-힣]")


def make_token():
	return signing.dumps({"t": time.time()}, salt=SALT)


def bot_reason(post):
	"""봇으로 보이면 이유(짧은 영문 키), 아니면 None."""
	if (post.get(HONEYPOT_FIELD) or "").strip():
		return "honeypot"
	token = post.get("form_token") or ""
	if not token or (post.get("js_check") or "") != token[::-1]:
		return "no_js"
	try:
		data = signing.loads(token, salt=SALT, max_age=MAX_AGE)
	except signing.BadSignature:  # 만료도 여기로
		return "bad_token"
	if time.time() - float(data.get("t", 0)) < MIN_SECONDS:
		return "too_fast"
	return None


# ── 같은 IP 반복 가입 ──
def _key(ip):
	return f"accounts:signup-rate:{ip}"


def rate_limited(ip):
	return bool(ip) and len(_recent(ip)) >= RATE_LIMIT


def _recent(ip):
	now = time.time()
	return [t for t in (cache.get(_key(ip)) or []) if now - t < RATE_WINDOW]


def note_signup(ip):
	if ip:
		cache.set(_key(ip), _recent(ip) + [time.time()], RATE_WINDOW)


# ── 의심 가입 표시 (막지는 않고 승인 목록에 보여 줌) ──
def _gibberish(text, run=CONSONANT_RUN):
	"""한글이 없고, 자음이 5개 넘게 이어지거나 공백 없이 너무 긴 영문 덩어리."""
	text = (text or "").strip()
	if not text or HANGUL.search(text):
		return False
	if run.search(text):
		return True
	return any(len(w) >= 20 and w.isalpha() for w in text.split())


def suspicion(username, real_name, message, email, user_agent):
	reasons = []
	if _gibberish(real_name) or _gibberish(username, CONSONANT_RUN_ID):
		reasons.append("무작위 이름")
	if message and _gibberish(message):
		reasons.append("무작위 인사")
	domain = (email or "").rsplit("@", 1)[-1].lower()
	if domain in DISPOSABLE_DOMAINS:
		reasons.append("일회용 메일")
	if not user_agent or OLD_OR_BOT_UA.search(user_agent):
		reasons.append("이상한 브라우저")
	return reasons
