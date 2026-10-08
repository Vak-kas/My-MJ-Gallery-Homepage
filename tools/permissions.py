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
