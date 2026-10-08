"""mj-relay 데몬 제어 API 호출 (같은 서버 127.0.0.1, 공유 비밀키)."""

import json
from urllib import error, request

from django.conf import settings


class RelayError(Exception):
	pass


def _call(method, path, payload=None):
	if not settings.RELAY_API_KEY:
		raise RelayError("스트림 중계 서버가 설정되지 않았습니다 (RELAY_API_KEY).")
	data = json.dumps(payload).encode() if payload is not None else None
	req = request.Request(
		settings.RELAY_API_URL.rstrip("/") + path,
		data=data,
		method=method,
		headers={"X-Relay-Key": settings.RELAY_API_KEY, "Content-Type": "application/json"},
	)
	try:
		with request.urlopen(req, timeout=5) as resp:
			return json.loads(resp.read() or b"{}")
	except error.HTTPError as exc:
		try:
			message = json.loads(exc.read()).get("error")
		except (ValueError, AttributeError):
			message = None
		if exc.code == 404:
			return None
		raise RelayError(message or f"중계 서버 오류 ({exc.code})") from exc
	except (error.URLError, TimeoutError, ConnectionError) as exc:
		raise RelayError("스트림 중계 서버에 연결할 수 없습니다. 서버에서 mj-relay 가 실행 중인지 확인해 주세요.") from exc


def list_rooms():
	return (_call("GET", "/rooms") or {}).get("rooms", [])


def get_room(room_id):
	return _call("GET", f"/rooms/{room_id}")


def create_room(payload):
	return _call("POST", "/rooms", payload)


def close_room(room_id):
	return _call("DELETE", f"/rooms/{room_id}")


def join_room(room_id, role, token, ip):
	"""role(sender/receiver) 링크를 연 네트워크의 IP 를 등록."""
	return _call("POST", f"/rooms/{room_id}/join", {"role": role, "token": token, "ip": ip})


# ── 라이브 방송 ─────────────────────────────

def list_live():
	return (_call("GET", "/live") or {}).get("rooms", [])


def get_live(room_id):
	return _call("GET", f"/live/{room_id}")


def create_live(payload):
	return _call("POST", "/live", payload)


def close_live(room_id):
	return _call("DELETE", f"/live/{room_id}")
