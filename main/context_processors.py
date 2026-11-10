from django.conf import settings

from . import og_cards, seo


def _tool_meta(url_name):
	from tools.registry import TOOLS

	for tool in TOOLS:
		if tool["url_name"] == f"tools:{url_name}":
			return seo.build(f"{tool['title']} · Tool", tool["description"], og_cards.image_url("tool", tool["slug"]), path="")
	return None


def _game_meta(url_name):
	from games.registry import GAMES

	for game in GAMES:
		if game["url_name"] == f"games:{url_name}":
			return seo.build(f"{game['title']} · Game", game["description"], og_cards.image_url("game", game["slug"]), path="")
	return None


def _category_meta(slug):
	"""블로그 카테고리 목록 페이지 — 이름·설명·카드 이미지는 Studio › Categories 값 (관리자 전용은 기본값)"""
	from blog import categories

	if not categories.exists(slug) or categories.is_private(slug):
		return None
	info = categories.get(slug)
	return seo.build(info.name, info.description or None, og_cards.image_url("category", slug), path="")


CARD_KEYS = {("blog", "index"): ("page", "blog"), ("blog", "all"): ("page", "all"), ("blog", "series_list"): ("page", "series"), ("tools", "index"): ("tool", "index"), ("main", "photos"): ("page", "gallery"),
			 ("games", "index"): ("page", "games")}


PAGE_TITLES = {
	("blog", "index"): ("Blog", "기술 글과 일상 기록을 모은 서민재의 블로그."),
	("blog", "all"): ("All Posts", "모든 카테고리의 글을 한곳에서."),
	("blog", "series_list"): ("Series", "주제별로 이어서 읽는 글 묶음 — 처음부터 순서대로."),
	("tools", "index"): ("Tool", "살면서 ‘이런 게 있었으면’ 싶었던 것들을 직접 만들어 모아둔 곳. 문서·사진·학점, 파일 공유, 네트워크, 개발 도구."),
	("main", "photos"): ("Gallery", "사진 갤러리."),
	("games", "index"): ("Game", "사다리타기·돌림판 같은 모임 게임, 2048·한글 타자 연습 랭킹, 같이 하는 게임."),
}


def seo_meta(request):
	match = getattr(request, "resolver_match", None)
	ns, name = (match.namespace, match.url_name) if match else ("", "")
	meta = None
	if (ns, name) in PAGE_TITLES:
		title, desc = PAGE_TITLES[(ns, name)]
		card = CARD_KEYS.get((ns, name))
		meta = seo.build(title, desc, og_cards.image_url(*card) if card else None, path=request.path)
	elif (ns, name) == ("blog", "category"):
		meta = _category_meta(match.kwargs.get("slug", ""))
	elif ns == "tools":
		meta = _tool_meta(name)
	elif ns == "games":
		meta = _game_meta(name)
	meta = meta or seo.build(path=request.path)
	meta["url"] = seo.absolute(request.path)
	meta["noindex"] = request.path.startswith(seo.NOINDEX_PREFIXES)
	return {"default_meta": meta, "contact_email": settings.CONTACT_EMAIL}


def share(request):
	"""카카오톡 공유하기 JavaScript 키 (components/share.html), 검색엔진 소유 확인 값 (base.html)."""
	from django.conf import settings

	return {
		"kakao_js_key": settings.KAKAO_JS_KEY,
		"google_site_verification": _verification_value(settings.GOOGLE_SITE_VERIFICATION),
		"naver_site_verification": _verification_value(settings.NAVER_SITE_VERIFICATION),
	}


def _verification_value(raw):
	"""content 값만 넣어도, <meta ... content="값" /> 태그를 통째로 넣어도 값만 꺼냄."""
	import re

	raw = (raw or "").strip()
	m = re.search(r'content\s*=\s*["\']([^"\']+)["\']', raw)
	value = m.group(1) if m else raw
	return value if re.fullmatch(r"[A-Za-z0-9_\-]{8,128}", value) else ""
