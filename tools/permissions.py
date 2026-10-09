"""도구별 권한·한도. 바꿀 때는 여기 한 곳만 고치면 된다."""

# 회원(관리자 아님)이 데이터 전송 방을 만들 때의 한도 — 방 데이터는 서버를 거치므로 트래픽 보호용
MEMBER_STREAM_LIMITS = {
	"max_open_rooms": 1,   # 동시에 열어 둘 수 있는 방
	"rooms_per_day": 3,    # 하루에 만들 수 있는 방
	"ttl_minutes": 60,     # 방 유효 시간 최대
	"rate_mb": 8,          # 속도 상한 최대 (MB/s)
	"total_gb": 3,         # 방 하나 총량 상한 최대 (GB)
}


# 회원이 라이브 방송을 열 때의 한도 (TURN 중계 시 서버 트래픽 보호)
MEMBER_LIVE_LIMITS = {
	"max_open_rooms": 1,   # 동시에 열어 둘 수 있는 방송
	"rooms_per_day": 3,    # 하루에 만들 수 있는 방송
	"ttl_minutes": 120,    # 방송 시간 최대
	"max_viewers": 5,      # 시청자 최대
}
ADMIN_LIVE_LIMITS = {"ttl_minutes": 360, "max_viewers": 20}


def can_create_streams(user):
	"""데이터 전송 방 만들기: 로그인한(승인된) 회원."""
	return bool(user and user.is_authenticated and user.is_active)


def can_manage_streams(user):
	"""모든 방 관리·한도 없음·맡겨두기 업로드: 관리자."""
	return bool(user and user.is_authenticated and user.is_superuser)


def owns_room(user, room):
	return bool(user and user.is_authenticated and (room.get("meta") or {}).get("owner_id") == user.id)


# ── 회원 등급 ─────────────────────────────
# 비로그인 < 일반 회원 < ⭐ VIP 회원(Studio → Users 에서 지정, Django 그룹) < 관리자
VIP_GROUP = "vip"
TIER_LABELS = {"anon": "비로그인", "member": "일반 회원", "vip": "⭐ VIP 회원", "admin": "관리자"}


def is_vip(user):
	if not (user and user.is_authenticated and user.is_active):
		return False
	cached = getattr(user, "_mj_is_vip", None)
	if cached is None:
		cached = user.groups.filter(name=VIP_GROUP).exists()
		user._mj_is_vip = cached
	return cached


def tier(user):
	if not (user and user.is_authenticated):
		return "anon"
	if user.is_superuser:
		return "admin"
	return "vip" if is_vip(user) else "member"


def set_vip(user, on):
	from django.contrib.auth.models import Group

	group, _ = Group.objects.get_or_create(name=VIP_GROUP)
	if on:
		user.groups.add(group)
	else:
		user.groups.remove(group)
	user._mj_is_vip = bool(on)


# VIP 회원은 회원보다 넉넉하게
VIP_STREAM_LIMITS = {"max_open_rooms": 3, "rooms_per_day": 10, "ttl_minutes": 180, "rate_mb": 20, "total_gb": 10}
VIP_LIVE_LIMITS = {"max_open_rooms": 2, "rooms_per_day": 10, "ttl_minutes": 240, "max_viewers": 15}
VIP_QUOTA_MULTIPLIER = 3  # 속도 측정·포트 체크 한도 배수


def stream_limits(user):
	return VIP_STREAM_LIMITS if is_vip(user) else MEMBER_STREAM_LIMITS


def live_limits(user):
	return VIP_LIVE_LIMITS if is_vip(user) else MEMBER_LIVE_LIMITS


def quota_multiplier(user):
	return VIP_QUOTA_MULTIPLIER if is_vip(user) else 1


# AI 기능 (QR 스타일 추천·정규식 만들기·글 비교 요약·네트워크 결과 풀이 모두 합쳐서)
# per_day: 하루 횟수 (None = 제한 없음), max_chars: 한 번에 보낼 수 있는 글자 수
AI_LIMITS = {
	"member": {"per_day": 20, "max_chars": 4_000},
	"vip": {"per_day": 100, "max_chars": 15_000},
	"admin": {"per_day": None, "max_chars": 40_000},
}
