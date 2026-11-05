"""블로그 허브의 "연결 지도" — 카테고리를 큰 원(허브), 글을 그 둘레의 점으로 두고 글끼리의 연결을 선으로.

글끼리 연결로 보는 것 (세 가지):
- 같은 시리즈: 시리즈 순서대로 앞뒤 글끼리
- 본문 링크: 본문(링크·링크 카드)에 다른 글 주소 `/blog/post/<slug>/` 가 있으면
- 태그 공유: 같은 태그를 단 글끼리. 글이 너무 많이 달린 태그(TAG_MAX_POSTS 초과)는 너무 넓어서 뺌
글마다 선은 많아야 EDGE_PER_POST 개(겹치는 근거가 많은 것부터).

구성은 minter-v1.com (github.com/Minter-v1/Minter-blog) 의 지식 지도를 참고해 직접 구현
"""

import re
from collections import defaultdict
from urllib.parse import unquote

from django.urls import reverse

from .collections import CATEGORY_CARDS
from .models import Post

POST_LIMIT = 300
TAG_MAX_POSTS = 12
EDGE_PER_POST = 6
LINK_RE = re.compile(r"/blog/post/([^/\"'\s?#<>\\]+)/")
WEIGHT = {"series": 3, "link": 3, "tag": 1}


def build_map(posts_qs, include_secret=False):
	posts = list(
		posts_qs.order_by("-published_at", "-id")
		.only("id", "title", "slug", "category", "series", "series_order", "content", "published_at")
		.prefetch_related("tags")[:POST_LIMIT]
	)
	if not include_secret:
		posts = [p for p in posts if p.category != Post.CATEGORY_SECRET]
	by_slug = {p.slug: p for p in posts}

	score = defaultdict(int)       # (작은 id, 큰 id) → 무게
	kinds = defaultdict(set)

	def link(a, b, kind):
		if a.id == b.id:
			return
		key = (min(a.id, b.id), max(a.id, b.id))
		score[key] += WEIGHT[kind]
		kinds[key].add(kind)

	series = defaultdict(list)
	for p in posts:
		if p.series_id:
			series[p.series_id].append(p)
	for items in series.values():
		items.sort(key=lambda p: (p.series_order or 0, p.published_at))
		for a, b in zip(items, items[1:]):
			link(a, b, "series")

	for p in posts:
		for slug in set(LINK_RE.findall(p.content or "")):
			target = by_slug.get(unquote(slug))
			if target:
				link(p, target, "link")

	tag_posts = defaultdict(list)
	for p in posts:
		for t in p.tags.all():
			tag_posts[t.name].append(p)
	for items in tag_posts.values():
		if len(items) > TAG_MAX_POSTS:
			continue
		for i, a in enumerate(items):
			for b in items[i + 1:]:
				link(a, b, "tag")

	# 글마다 강한 선부터 EDGE_PER_POST 개까지만
	per_post = defaultdict(list)
	for key, w in score.items():
		per_post[key[0]].append((w, key))
		per_post[key[1]].append((w, key))
	keep = set()
	for items in per_post.values():
		items.sort(reverse=True)
		keep.update(k for _, k in items[:EDGE_PER_POST])
	edges = [{"a": a, "b": b, "w": score[(a, b)], "kinds": sorted(kinds[(a, b)])} for a, b in sorted(keep)]
	connected = {e["a"] for e in edges} | {e["b"] for e in edges}

	hubs = []
	for value, label in Post.CATEGORY_CHOICES:
		if value == Post.CATEGORY_SECRET and not include_secret:
			continue
		count = sum(1 for p in posts if p.category == value)
		icon, _desc, url_name = CATEGORY_CARDS[value]
		hubs.append({"key": value, "label": label, "icon": icon, "count": count, "url": reverse(url_name)})

	nodes = [{
		"id": p.id, "title": p.title, "hub": p.category,
		"url": reverse("blog:post_detail", args=[p.slug]),
		"connected": p.id in connected,
	} for p in posts]
	return {
		"hubs": hubs,
		"nodes": nodes,
		"edges": edges,
		"stats": {"connected": len(connected), "alone": len(nodes) - len(connected), "edges": len(edges)},
	}
