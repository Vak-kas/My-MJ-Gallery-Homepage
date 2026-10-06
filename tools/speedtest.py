"""인터넷 속도 측정용 API (지연 / 다운로드 / 업로드).

브라우저가 이 서버와 실제로 데이터를 주고받으며 처리량을 잰다.
누구나 쓸 수 있는 공개 API 라서, 서버 트래픽이 과하게 쓰이지 않도록
IP 별로 일정 시간 동안 쓸 수 있는 양을 제한한다.
"""

import os

from django.core.cache import cache
from django.http import HttpResponse, JsonResponse, StreamingHttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

CHUNK = os.urandom(1024 * 1024)  # 압축되지 않는 1MB 랜덤 데이터 (매 요청마다 만들지 않고 재사용)
MAX_REQUEST_BYTES = 25 * 1024 * 1024
WINDOW_SECONDS = 10 * 60
# 브라우저는 한 번 측정에 다운로드 200MB·업로드 100MB 까지만 요청 → 10분에 최소 5번 측정 가능
DOWNLOAD_QUOTA = 1024 * 1024 * 1024
UPLOAD_QUOTA = 512 * 1024 * 1024

NO_CACHE = {
	"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
	"Pragma": "no-cache",
}


def _client_ip(request):
	# nginx 가 X-Real-IP 를 덮어써서 넘겨줌 (gunicorn 은 유닉스 소켓이라 REMOTE_ADDR 이 비어 있음)
	return (request.META.get("HTTP_X_REAL_IP") or request.META.get("REMOTE_ADDR") or "unknown").strip()


def _consume_quota(request, kind, amount, quota):
	"""IP 별 사용량에 amount 를 더하고, 한도를 넘으면 False."""
	key = f"speedtest:{kind}:{_client_ip(request)}"
	used = cache.get(key, 0)
	if used + amount > quota:
		return False
	cache.set(key, used + amount, WINDOW_SECONDS)
	return True


def _limited():
	return JsonResponse(
		{"error": "측정 한도를 넘었습니다. 10분 뒤에 다시 시도해 주세요."},
		status=429,
		headers=NO_CACHE,
	)


def _with_headers(response):
	for key, value in NO_CACHE.items():
		response[key] = value
	return response


@require_GET
def ping(request):
	return _with_headers(HttpResponse(b"", content_type="text/plain"))


@require_GET
def download(request):
	try:
		size = int(request.GET.get("bytes", 1024 * 1024))
	except (TypeError, ValueError):
		size = 1024 * 1024
	size = max(1, min(size, MAX_REQUEST_BYTES))
	if not _consume_quota(request, "down", size, DOWNLOAD_QUOTA):
		return _limited()

	def stream():
		remaining = size
		while remaining > 0:
			piece = CHUNK[: min(len(CHUNK), remaining)]
			remaining -= len(piece)
			yield piece

	response = StreamingHttpResponse(stream(), content_type="application/octet-stream")
	response["Content-Length"] = str(size)
	return _with_headers(response)


@csrf_exempt  # 공개 측정용: 받은 데이터는 버리고 개수만 셈 (상태 변경 없음)
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
	if not _consume_quota(request, "up", declared, UPLOAD_QUOTA):
		return _limited()

	received = 0
	while True:
		piece = request.read(64 * 1024)
		if not piece:
			break
		received += len(piece)
	return JsonResponse({"received": received}, headers=NO_CACHE)
