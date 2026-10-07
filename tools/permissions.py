"""도구별 권한. 스트림 방 권한은 여기 한 곳만 바꾸면 된다
(예: 이메일 인증을 마친 회원에게 열 때 → `return user.is_authenticated and user.is_active`)."""


def can_manage_streams(user):
	return bool(user and user.is_authenticated and user.is_superuser)
