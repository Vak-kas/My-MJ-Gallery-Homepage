"""🛰 위성 궤도 · NTN 계산기.

계산은 모두 브라우저에서 하고, 서버는 CelesTrak 의 궤도 자료(TLE)만 대신 받아 줌
(CelesTrak 은 브라우저에서 바로 받을 수 없게 막혀 있고, 같은 자료를 2시간 안에 다시 받지 말라고 함 → 4시간 저장).
"""

import re
import urllib.error
import urllib.parse
import urllib.request

from django.core.cache import cache
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_GET

from security.utils import client_ip

CELESTRAK = "https://celestrak.org/NORAD/elements/gp.php"
CACHE_SECONDS = 4 * 60 * 60
BACKUP_SECONDS = 7 * 24 * 60 * 60  # CelesTrak 이 안 줄 때 쓸 예비 사본
USER_AGENT = "smjgallery.kr satellite tool (+https://smjgallery.kr/tools/satellite/)"
SEARCH_PER_MIN = 20  # 이름·번호 찾기는 IP 하나에 1분 20번

# 화면의 '위성 묶음' (CelesTrak GROUP 이름, 보여줄 이름)
GROUPS = [
	("stations", "🧑‍🚀 우주정거장 (ISS·톈궁)"),
	("visual", "✨ 맨눈으로 보이는 밝은 위성"),
	("starlink", "🛰 스타링크 (LEO 550km 안팎)"),
	("oneweb", "🛰 원웹 (LEO 1200km)"),
	("kuiper", "🛰 아마존 Kuiper"),
	("iridium-NEXT", "📞 이리듐 NEXT (LEO 780km)"),
	("globalstar", "📞 글로벌스타 (LEO 1414km)"),
	("gps-ops", "📍 GPS (MEO 20200km)"),
	("galileo", "📍 갈릴레오 (MEO 23222km)"),
	("beidou", "📍 베이더우"),
	("geo", "📡 정지궤도 (GEO 35786km)"),
	("weather", "🌦 기상 위성"),
]
GROUP_NAMES = dict(GROUPS)


def page(request):
	return render(request, "tools/satellite.html", {"groups": GROUPS})


def _parse_tle(text):
	"""이름 줄 + 1 줄 + 2 줄 묶음만 골라냄 (이상한 줄은 건너뜀)."""
	lines = [ln.rstrip() for ln in text.splitlines() if ln.strip()]
	out = []
	for i in range(len(lines) - 2):
		if lines[i + 1].startswith("1 ") and lines[i + 2].startswith("2 ") and not lines[i].startswith(("1 ", "2 ")):
			out.append({"name": lines[i].strip()[:40], "l1": lines[i + 1][:69], "l2": lines[i + 2][:69]})
	return out


def _fetch(params):
	url = CELESTRAK + "?" + urllib.parse.urlencode({**params, "FORMAT": "tle"})
	req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
	with urllib.request.urlopen(req, timeout=20) as res:
		return res.read(8 * 1024 * 1024).decode("utf-8", "replace")


@require_GET
def tle(request):
	"""?group=starlink | ?catnr=25544 | ?name=ISS → {"sats": [{name, l1, l2}], "source": ...}"""
	group = request.GET.get("group", "")
	catnr = request.GET.get("catnr", "").strip()
	name = " ".join(request.GET.get("name", "").split())
	if group:
		if group not in GROUP_NAMES:
			return JsonResponse({"error": "없는 위성 묶음이에요."}, status=400)
		params, key = {"GROUP": group}, f"sat:tle:g:{group}"
	elif catnr:
		if not re.fullmatch(r"\d{1,9}", catnr):
			return JsonResponse({"error": "위성 번호(NORAD)는 숫자로 넣어 주세요."}, status=400)
		params, key = {"CATNR": catnr}, f"sat:tle:c:{catnr}"
	elif name:
		if not re.fullmatch(r"[A-Za-z0-9 ()\-./+]{2,30}", name):
			return JsonResponse({"error": "위성 이름은 영문·숫자 2~30자로 넣어 주세요. (예: ISS, KOMPSAT, STARLINK-1007)"}, status=400)
		params, key = {"NAME": name}, f"sat:tle:n:{name.upper()}"
	else:
		return JsonResponse({"error": "무엇을 찾을지 정해 주세요."}, status=400)

	data = cache.get(key)
	stale = False
	if data is None:
		if not group:
			rate_key = f"sat:rate:{client_ip(request)}"
			count = cache.get(rate_key, 0)
			if count >= SEARCH_PER_MIN:
				return JsonResponse({"error": "찾기를 너무 자주 했어요. 1분 뒤 다시 해 주세요."}, status=429)
			cache.set(rate_key, count + 1, 60)
		try:
			sats = _parse_tle(_fetch(params))
		except (urllib.error.URLError, OSError, ValueError):
			sats = None  # CelesTrak 이 거절(2시간 안에 다시 받음 등)하거나 안 됨
		if sats is None:
			data = cache.get(key + ":backup")  # 예전에 받아 둔 것이라도
			if data is None:
				return JsonResponse({"error": "궤도 자료(CelesTrak)를 받지 못했어요. 잠시 뒤 다시 해 주세요."}, status=502)
			stale = True
			cache.set(key, data, 30 * 60)
		else:
			data = {"sats": sats, "fetched": timezone.now().isoformat()}
			cache.set(key, data, CACHE_SECONDS if sats else 600)
			if sats:
				cache.set(key + ":backup", data, BACKUP_SECONDS)
	if not data["sats"]:
		return JsonResponse({"error": "찾는 위성이 없어요.", "sats": []}, status=404)
	return JsonResponse({**data, "source": "CelesTrak", "count": len(data["sats"]), "stale": stale})
