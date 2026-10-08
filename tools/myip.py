"""내 IP·접속 정보 (누구나).

- 페이지: 서버가 본 내 공인 IP, IP 버전, 역방향 DNS 이름, 요청 헤더 일부
- 통신사 조회(선택, 버튼을 눌렀을 때만): 공개 등록 정보(RDAP)에서 이 IP 대역의 소유 기관·국가를 찾아 줌
"""

import ipaddress
import json
import socket
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout

from django.core.cache import cache
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET

from .speedtest import _client_ip

_resolver = ThreadPoolExecutor(max_workers=4)
RDAP_URL = "https://rdap.org/ip/{ip}"
LOOKUP_LIMIT = 10          # IP 당 10분에 통신사 조회 횟수
LOOKUP_WINDOW = 10 * 60


def _parse_ip(raw):
	try:
		return ipaddress.ip_address(raw)
	except ValueError:
		return None


def _reverse_dns(ip, timeout=2.0):
	try:
		return _resolver.submit(lambda: socket.gethostbyaddr(str(ip))[0]).result(timeout=timeout)
	except (FutureTimeout, OSError):
		return ""


def myip(request):
	raw = _client_ip(request)
	ip = _parse_ip(raw)
	info = {
		"ip": raw,
		"version": f"IPv{ip.version}" if ip else "알 수 없음",
		"is_private": bool(ip and (ip.is_private or ip.is_loopback)),
		"hostname": _reverse_dns(ip) if ip and ip.is_global else "",
		"headers": [
			("User-Agent", request.META.get("HTTP_USER_AGENT", "")),
			("Accept-Language", request.META.get("HTTP_ACCEPT_LANGUAGE", "")),
			("프로토콜", "HTTPS" if request.is_secure() or request.META.get("HTTP_X_FORWARDED_PROTO") == "https" else "HTTP"),
			("Do Not Track", request.META.get("HTTP_DNT", "") or "꺼짐"),
		],
	}
	return render(request, "tools/myip.html", {"info": info})


def _vcard_name(entity):
	for item in (entity.get("vcardArray") or [None, []])[1]:
		if item and item[0] == "fn":
			return item[3]
	return ""


def _summarize_rdap(data):
	orgs = []
	for ent in data.get("entities") or []:
		roles = ent.get("roles") or []
		name = _vcard_name(ent)
		if name and ("registrant" in roles or "administrative" in roles) and name not in orgs:
			orgs.append(name)
	remarks = [" ".join(r.get("description") or []) for r in data.get("remarks") or []]
	return {
		"network": data.get("name", ""),
		"range": f"{data.get('startAddress', '')} – {data.get('endAddress', '')}".strip(" –"),
		"country": data.get("country", ""),
		"org": orgs[:3],
		"description": next((r for r in remarks if r), "")[:200],
	}


@require_GET
def myip_lookup(request):
	raw = _client_ip(request)
	ip = _parse_ip(raw)
	if not ip or not ip.is_global:
		return JsonResponse({"error": "공인 IP 가 아니라 조회할 수 없어요."}, status=400)

	key = f"myip:lookup:{raw}"
	bucket = cache.get(key) or {"start": time.time(), "count": 0}
	if bucket["count"] >= LOOKUP_LIMIT:
		return JsonResponse({"error": "잠시 뒤에 다시 시도해 주세요."}, status=429)
	bucket["count"] += 1
	cache.set(key, bucket, max(1, int(bucket["start"] + LOOKUP_WINDOW - time.time())))

	cached = cache.get(f"myip:rdap:{raw}")
	if cached:
		return JsonResponse(cached)
	req = urllib.request.Request(RDAP_URL.format(ip=raw), headers={"Accept": "application/rdap+json"})
	try:
		with urllib.request.urlopen(req, timeout=6) as res:
			result = _summarize_rdap(json.loads(res.read().decode("utf-8")))
	except (OSError, ValueError):  # URLError·타임아웃·연결 오류 모두 OSError
		return JsonResponse({"error": "등록 정보 서버에 연결하지 못했어요. 잠시 뒤 다시 시도해 주세요."}, status=502)
	cache.set(f"myip:rdap:{raw}", result, 24 * 60 * 60)
	return JsonResponse(result)
