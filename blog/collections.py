"""블로그 허브의 "컬렉션" 카드 — 카테고리(Tech·Free·Life·관리자에겐 Secret)와 시리즈를 같은 모양의 카드로.

카드마다 아이콘·글 수·이름·설명·최근 글 3개·전체 보기 링크. 검색어와 상관없이 볼 수 있는 글 전체 기준.
구성은 minter-v1.com (github.com/Minter-v1/Minter-blog) 의 컬렉션 카드를 참고해 직접 구현
"""

from datetime import timedelta

from django.urls import reverse
from django.utils import timezone

from .models import Post

CATEGORY_CARDS = {
	Post.CATEGORY_TECH: ("🛠️", "기술 노트 · 개발 · 트러블슈팅", "blog:tech"),
	Post.CATEGORY_BOARD: ("💬", "자유게시판 · 회원 누구나", "blog:board"),
	Post.CATEGORY_LIFE: ("🌿", "일상과 생각 기록", "blog:life"),
	Post.CATEGORY_SECRET: ("🔒", "관리자 비공개 메모", "blog:secret"),
}
SERIES_LIMIT = 6
RECENT = 3


def _recent(posts, new_cutoff):
	return [{"title": p.title, "url": reverse("blog:post_detail", args=[p.slug]), "is_new": bool(p.published_at and p.published_at >= new_cutoff)} for p in posts[:RECENT]]


def build_collections(posts_qs, include_secret=False):
	posts = list(posts_qs.select_related("series").order_by("-published_at", "-id").only("title", "slug", "category", "series", "published_at"))
	new_cutoff = timezone.now() - timedelta(days=3)
	cards = []
	for value, label in Post.CATEGORY_CHOICES:
		if value == Post.CATEGORY_SECRET and not include_secret:
			continue
		icon, desc, url_name = CATEGORY_CARDS[value]
		items = [p for p in posts if p.category == value]
		cards.append({
			"kind": "secret" if value == Post.CATEGORY_SECRET else "category",
			"title": label, "desc": desc, "icon": icon, "count": len(items),
			"recent": _recent(items, new_cutoff), "url": reverse(url_name),
		})

	by_series = {}
	for p in posts:
		if p.series_id:
			by_series.setdefault(p.series_id, []).append(p)
	# 최근에 글이 올라온 시리즈부터
	for items in sorted(by_series.values(), key=lambda ps: ps[0].published_at or timezone.now(), reverse=True)[:SERIES_LIMIT]:
		series = items[0].series
		cards.append({
			"kind": "series", "title": series.name, "desc": series.description or f"시리즈 · {len(items)}편",
			"icon": "📚", "count": len(items), "recent": _recent(items, new_cutoff),
			"url": reverse("blog:series", args=[series.slug]),
		})
	return cards
