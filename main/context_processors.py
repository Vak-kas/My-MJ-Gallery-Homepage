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


CARD_KEYS = {("blog", "index"): ("page", "blog"), ("blog", "all"): ("page", "all"), ("blog", "tech"): ("page", "tech"), ("blog", "algorithm"): ("page", "algorithm"), ("blog", "paper"): ("page", "paper"),
			 ("blog", "life"): ("page", "life"), ("tools", "index"): ("tool", "index"), ("main", "photos"): ("page", "gallery"),
			 ("games", "index"): ("page", "games")}


PAGE_TITLES = {
	("blog", "index"): ("Blog", "기술 글, 알고리즘, 논문 리뷰, 일상 기록을 모은 서민재의 블로그."),
	("blog", "all"): ("All Posts", "모든 카테고리의 글을 한곳에서."),
	("blog", "tech"): ("Tech Blog", "트러블슈팅·네트워크·보안 등 기술 글."),
	("blog", "algorithm"): ("Algorithm", "알고리즘 문제 풀이와 개념 정리."),
	("blog", "paper"): ("Paper Review", "읽은 논문을 정리한 리뷰 글."),
	("blog", "life"): ("Life", "일상 · 후기 · 자유 글."),
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
