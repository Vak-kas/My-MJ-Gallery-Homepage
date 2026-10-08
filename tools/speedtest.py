"""인터넷 속도 측정용 API (지연 / 다운로드 / 업로드).

브라우저가 이 서버와 실제로 데이터를 주고받으며 처리량을 잰다.
서버 트래픽을 실제로 쓰므로 로그인한 회원만 쓸 수 있고,
회원별로 10분·하루 동안 쓸 수 있는 양을 제한한다. (관리자는 제한 없음)
"""

import math
import os
import time
from functools import wraps

from django.core.cache import cache
from django.http import HttpResponse, JsonResponse, StreamingHttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

CHUNK = os.urandom(1024 * 1024)  # 압축되지 않는 1MB 랜덤 데이터 (매 요청마다 만들지 않고 재사용)
MAX_REQUEST_BYTES = 25 * 1024 * 1024
GB = 1024 * 1024 * 1024
WINDOW_SECONDS = 10 * 60
DAY_SECONDS = 24 * 60 * 60
# 브라우저는 한 번 측정에 다운로드 200MB·업로드 100MB 까지만 요청
# → 회원당 10분에 약 5번, 하루에 약 15번 측정 가능
QUOTAS = {
	"down": [(WINDOW_SECONDS, 1 * GB), (DAY_SECONDS, 3 * GB)],
	"up": [(WINDOW_SECONDS, GB // 2), (DAY_SECONDS, 3 * GB // 2)],
}

NO_CACHE = {
	"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
	"Pragma": "no-cache",
}


def _client_ip(request):
	# nginx 가 X-Real-IP 를 덮어써서 넘겨줌 (gunicorn 은 유닉스 소켓이라 REMOTE_ADDR 이 비어 있음)
	return (request.META.get("HTTP_X_REAL_IP") or request.META.get("REMOTE_ADDR") or "unknown").strip()


def _consume_quota(request, kind, amount):
	"""회원별 사용량에 amount 를 더함. 모든 한도 안이면 0, 넘으면 다시 쓸 수 있을 때까지 남은 초를 돌려줌.

	창은 그 회원의 첫 요청 시점부터 고정 → 계속 측정해도 시간이 지나면 반드시 풀림.
	"""
	user = request.user
	if user.is_superuser:
		return 0  # 사이트 관리자는 제한 없음

	now = time.time()
	buckets = []
	for window, quota in QUOTAS[kind]:
		key = f"speedtest:{kind}:{window}:u{user.id}"
		bucket = cache.get(key)
		if not bucket or now - bucket["start"] >= window:
			bucket = {"start": now, "used": 0}
		remaining = max(1, math.ceil(bucket["start"] + window - now))
		if bucket["used"] + amount > quota:
			return remaining
		buckets.append((key, bucket, remaining))
	for key, bucket, remaining in buckets:
		bucket["used"] += amount
		cache.set(key, bucket, remaining)
	return 0


def _login_required_json(view):
	@wraps(view)
	def wrapper(request, *args, **kwargs):
		if not request.user.is_authenticated:
			return JsonResponse({"error": "로그인한 회원만 속도를 측정할 수 있습니다."}, status=401, headers=NO_CACHE)
		return view(request, *args, **kwargs)
	return wrapper


def _limited(retry_after):
	minutes = max(1, math.ceil(retry_after / 60))
	wait = f"약 {minutes}분" if minutes < 60 else f"약 {math.ceil(minutes / 60)}시간"
	return JsonResponse(
		{"error": f"측정 한도를 넘었습니다. {wait} 뒤에 다시 시도해 주세요.", "retry_after": retry_after},
		status=429,
		headers={**NO_CACHE, "Retry-After": str(retry_after)},
	)


def _with_headers(response):
	for key, value in NO_CACHE.items():
		response[key] = value
	return response


@_login_required_json
@require_GET
def ping(request):
	return _with_headers(HttpResponse(b"", content_type="text/plain"))


@_login_required_json
@require_GET
def download(request):
	try:
		size = int(request.GET.get("bytes", 1024 * 1024))
	except (TypeError, ValueError):
		size = 1024 * 1024
	size = max(1, min(size, MAX_REQUEST_BYTES))
	retry_after = _consume_quota(request, "down", size)
	if retry_after:
		return _limited(retry_after)

	def stream():
		remaining = size
		while remaining > 0:
			piece = CHUNK[: min(len(CHUNK), remaining)]
			remaining -= len(piece)
			yield piece

	response = StreamingHttpResponse(stream(), content_type="application/octet-stream")
	response["Content-Length"] = str(size)
	return _with_headers(response)


@csrf_exempt  # 측정용: 받은 데이터는 버리고 개수만 셈 (상태 변경 없음)
@_login_required_json
@require_POST
def upload(request):
	try:
		declared = int(request.META.get("CONTENT_LENGTH") or 0)
	except ValueError:
		declared = 0
	if declared <= 0:
		return JsonResponse({"error": "본문이 비어 있습니다."}, status=400, headers=NO_CACHE)
	if declared > MAX_REQUEST_BYTES:
		return JsonResponse({"error": "요청이 너무 큽니다."}, status=413, headers=NO_CACHE)
	retry_after = _consume_quota(request, "up", declared)
	if retry_after:
		return _limited(retry_after)

	received = 0
	while True:
		piece = request.read(64 * 1024)
		if not piece:
			break
		received += len(piece)
	return JsonResponse({"received": received}, headers=NO_CACHE)
