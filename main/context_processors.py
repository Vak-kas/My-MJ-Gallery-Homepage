from . import seo


def _tool_meta(url_name):
	from tools.registry import TOOLS

	for tool in TOOLS:
		if tool["url_name"] == f"tools:{url_name}":
			return seo.build(f"{tool['title']} · Tool", tool["description"], path="")
	return None


PAGE_TITLES = {
	("blog", "index"): ("Blog", "기술 글, 자유게시판, 일상 기록을 모은 서민재의 블로그."),
	("blog", "tech"): ("Tech Blog", "트러블슈팅·네트워크·보안 등 기술 글."),
	("blog", "board"): ("자유게시판", None),
	("blog", "life"): ("Life", "기록 · 생각 · 메모."),
	("tools", "index"): ("Tool", "계산기·네트워크 진단·QR·암호화 키 생성 등 직접 만든 웹 도구 모음."),
	("main", "photos"): ("Gallery", "사진 갤러리."),
}


def seo_meta(request):
	match = getattr(request, "resolver_match", None)
	ns, name = (match.namespace, match.url_name) if match else ("", "")
	meta = None
	if (ns, name) in PAGE_TITLES:
		title, desc = PAGE_TITLES[(ns, name)]
		meta = seo.build(title, desc, path=request.path)
	elif ns == "tools":
		meta = _tool_meta(name)
	meta = meta or seo.build(path=request.path)
	meta["url"] = seo.absolute(request.path)
	meta["noindex"] = request.path.startswith(seo.NOINDEX_PREFIXES)
	return {"default_meta": meta}
