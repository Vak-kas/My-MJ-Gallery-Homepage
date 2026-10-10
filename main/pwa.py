"""앱처럼 설치 (PWA): 앱 정보(manifest), 서비스 워커, 인터넷이 끊겼을 때 화면, 설치 안내.

서비스 워커는 개인 정보가 섞일 수 있는 HTML 화면은 저장하지 않음 — 정적 파일(/static/)과
'연결이 끊겼어요' 화면만 저장하고, 화면 요청이 실패할 때만 그 화면을 보여 줌.
"""

import json

from django.http import HttpResponse
from django.shortcuts import render
from django.templatetags.static import static
from django.urls import reverse
from django.views.decorators.cache import cache_control

# 바꾸면 휴대폰에 저장된 옛 파일을 지우고 새로 받음
SW_VERSION = "mj-v1"


@cache_control(max_age=60 * 60)
def manifest(request):
	data = {
		"name": "MJ Gallery",
		"short_name": "MJ Gallery",
		"description": "서민재 갤러리 — 블로그·도구·게임",
		"lang": "ko",
		"start_url": "/?source=app",
		"scope": "/",
		"display": "standalone",
		"orientation": "any",
		"background_color": "#f5f5f7",
		"theme_color": "#ffffff",
		"icons": [
			{"src": static("images/app/icon-192.png"), "sizes": "192x192", "type": "image/png", "purpose": "any"},
			{"src": static("images/app/icon-512.png"), "sizes": "512x512", "type": "image/png", "purpose": "any"},
			{"src": static("images/app/icon-maskable-512.png"), "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
		],
		# 아이콘을 꾹 누르면 나오는 바로가기 (안드로이드)
		"shortcuts": [
			{"name": "내 클립보드", "short_name": "클립보드", "url": reverse("tools:clipboard"), "icons": [{"src": static("images/app/icon-192.png"), "sizes": "192x192"}]},
			{"name": "논문 찾기", "short_name": "논문", "url": reverse("tools:papers"), "icons": [{"src": static("images/app/icon-192.png"), "sizes": "192x192"}]},
			{"name": "Tool 목록", "short_name": "Tool", "url": reverse("tools:index"), "icons": [{"src": static("images/app/icon-192.png"), "sizes": "192x192"}]},
			{"name": "Game", "short_name": "Game", "url": reverse("games:index"), "icons": [{"src": static("images/app/icon-192.png"), "sizes": "192x192"}]},
		],
	}
	return HttpResponse(json.dumps(data, ensure_ascii=False), content_type="application/manifest+json; charset=utf-8")


SW = """// MJ Gallery 서비스 워커 — 정적 파일과 '연결이 끊겼어요' 화면만 저장 (개인 화면은 저장 안 함)
const CACHE = "%(version)s";
const OFFLINE = "%(offline)s";
const PRECACHE = [OFFLINE, %(icons)s];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(PRECACHE)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))).then(() => self.clients.claim()));
});

self.addEventListener("fetch", (e) => {
  const req = e.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin !== location.origin) return;
  // 화면 이동: 늘 서버에서 받고, 실패하면(인터넷 끊김) 안내 화면
  if (req.mode === "navigate") {
    e.respondWith(fetch(req).catch(() => caches.match(OFFLINE)));
    return;
  }
  // 정적 파일: 저장해 둔 걸 바로 보여 주고 뒤에서 새로 받아 둠
  if (url.pathname.startsWith("/static/")) {
    e.respondWith(caches.open(CACHE).then(async (c) => {
      const hit = await c.match(req);
      const net = fetch(req).then((res) => { if (res.ok) c.put(req, res.clone()); return res; }).catch(() => hit);
      return hit || net;
    }));
  }
});
"""


def service_worker(request):
	icons = ", ".join(json.dumps(static(f"images/app/{n}")) for n in ("icon-192.png", "icon-512.png"))
	body = SW % {"version": SW_VERSION, "offline": reverse("pwa_offline"), "icons": icons}
	res = HttpResponse(body, content_type="application/javascript; charset=utf-8")
	res["Service-Worker-Allowed"] = "/"
	res["Cache-Control"] = "no-cache"  # 새 버전이 바로 퍼지게
	return res


def offline(request):
	return render(request, "pwa/offline.html")


def install(request):
	return render(request, "pwa/install.html")
