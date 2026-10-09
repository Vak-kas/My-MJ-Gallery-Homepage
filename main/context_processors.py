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


CARD_KEYS = {("blog", "index"): ("page", "blog"), ("blog", "tech"): ("page", "tech"), ("blog", "board"): ("page", "board"),
			 ("blog", "life"): ("page", "life"), ("tools", "index"): ("tool", "index"), ("main", "photos"): ("page", "gallery"),
			 ("games", "index"): ("page", "games")}


PAGE_TITLES = {
	("blog", "index"): ("Blog", "기술 글, 자유게시판, 일상 기록을 모은 서민재의 블로그."),
	("blog", "tech"): ("Tech Blog", "트러블슈팅·네트워크·보안 등 기술 글."),
	("blog", "board"): ("자유게시판", None),
	("blog", "life"): ("Life", "기록 · 생각 · 메모."),
	("tools", "index"): ("Tool", "살면서 ‘이런 게 있었으면’ 싶었던 것들을 직접 만들어 모아둔 곳. 문서·사진·학점, 파일 공유, 네트워크, 개발 도구."),
	("main", "photos"): ("Gallery", "사진 갤러리."),
	("games", "index"): ("Game", "사다리타기·돌림판 같은 모임 게임과 혼자 하기·같이 하기 게임, 추억의 게임관."),
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
	return {"default_meta": meta}
