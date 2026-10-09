"""링크 미리보기(Open Graph·트위터 카드)와 검색 노출용 메타 정보.

- 기본값은 context processor(`seo_meta`)가 페이지마다 채우고, 글 상세처럼 내용이 있는 페이지는 뷰가 `meta` 로 덮어씀
- 링크로 여는 개인 페이지(관리·로그인·공유 링크 등)는 검색에 안 나오게 noindex
"""

from django.conf import settings
from django.templatetags.static import static

SITE_NAME = "서민재 갤러리"
DEFAULT_DESCRIPTION = "네트워크·보안을 공부하는 서민재의 포트폴리오와 기술 블로그, 그리고 직접 만든 웹 도구 모음."
NOINDEX_PREFIXES = (
	"/studio/", "/accounts/", "/notifications/", "/admin/", "/s/",
	"/tools/share/", "/tools/secret/", "/tools/live/", "/tools/stream/", "/tools/clipboard/",
)


def absolute(url):
	if not url:
		return ""
	if url.startswith(("http://", "https://")):
		return url
	return settings.SITE_URL.rstrip("/") + ("" if url.startswith("/") else "/") + url


def default_image():
	return absolute(static("images/og-default.png"))


def build(title=None, description=None, image=None, kind="website", path="/", **extra):
	full_title = f"{title} — {SITE_NAME}" if title else SITE_NAME
	return {
		"title": full_title,
		"og_title": title or SITE_NAME,
		"description": (description or DEFAULT_DESCRIPTION)[:200],
		"image": absolute(image) if image else default_image(),
		"type": kind,
		"url": absolute(path),
		"noindex": path.startswith(NOINDEX_PREFIXES),
		**extra,
	}


def post_meta(post, locked=False):
	"""블로그 글 미리보기. 비밀번호 글은 내용·이미지를 숨김."""
	from django.urls import reverse

	from blog.content import parse_content, tiptap_cover_image, tiptap_plain_text

	path = reverse("blog:post_detail", args=[post.slug])
	if locked or post.visibility != post.VISIBILITY_PUBLIC:
		return build(post.title, "🔒 비밀번호로 보호된 글이에요.", path=path, kind="article")
	fmt, data = parse_content(post.content)
	text = post.summary or (tiptap_plain_text(data) if fmt == "tiptap" else "")
	image = post.cover_image.url if post.cover_image else (tiptap_cover_image(data) if fmt == "tiptap" else "")
	return build(
		post.title,
		text[:160] + ("…" if len(text) > 160 else ""),
		image,
		kind="article",
		path=path,
		published=post.published_at.isoformat() if post.published_at else "",
		author=post.author.get_full_name() or post.author.username if post.author else "",
		tags=[t.name for t in post.tags.all()],
	)
