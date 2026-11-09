"""블로그 허브의 "Topic Map" — Tech 글을 태그가 비슷한 것끼리 자동으로 묶어 보여 줌.

1. 글마다 태그 모음: 글 태그 + 제목 앞 말머리(`[wifi] ...` → wifi). 띄어쓰기·하이픈·점·대소문자는 무시
   (`Wi-Fi`·`WIFI` → wifi, `5G NR`·`5GNR` → 5gnr)
2. 두 글의 비슷함 = 겹친 태그 무게 합 / 태그가 적은 쪽의 무게 합 (무게 = 드문 태그일수록 큼, IDF)
3. 평균 연결(average linkage) 군집: 가장 비슷한 두 묶음을 MERGE_MIN 이상인 동안 계속 합침
4. 묶음 이름 = 그 묶음에서 가장 많이 나온 태그(같으면 더 드문 태그). 혼자 남은 글은 "기타"
5. 글끼리 선: 같은 시리즈(앞뒤)·본문 링크·태그 비슷함(EDGE_MIN 이상), 글마다 강한 것 6개까지
"""

import math
import re
from collections import Counter, defaultdict
from urllib.parse import unquote

from django.urls import reverse

from .models import Post

POST_LIMIT = 300
MERGE_MIN = 0.2
EDGE_MIN = 0.3
EDGE_PER_POST = 6
MAX_GROUPS = 8
LINK_RE = re.compile(r"/blog/post/([^/\"'\s?#<>\\]+)/")
PREFIX_RE = re.compile(r"^\s*\[([^\]]{1,20})\]")


def norm(tag):
	return re.sub(r"[\s\-_.·]+", "", (tag or "").strip().lower())


def post_terms(post):
	terms = {}
	for t in post.tags.all():
		key = norm(t.name)
		if key:
			terms.setdefault(key, t.name.strip())
	m = PREFIX_RE.match(post.title or "")
	if m and norm(m.group(1)):
		terms.setdefault(norm(m.group(1)), m.group(1).strip())
	return terms   # 정규화한 키 → 보여 줄 이름


def _hub_url():
	"""묶음 원을 누르면 갈 곳: Topic Map 카테고리가 하나면 그 목록, 여럿이면 전체"""
	from . import categories

	slugs = categories.topic_map_slugs()
	return reverse("blog:category", args=[slugs[0]]) if len(slugs) == 1 else reverse("blog:all")


def build_map(posts_qs):
	from . import categories

	hub_url = _hub_url()
	posts = list(
		posts_qs.filter(category__in=categories.topic_map_slugs())
		.order_by("-published_at", "-id")
		.only("id", "title", "slug", "category", "series", "series_order", "content", "published_at")
		.prefetch_related("tags")[:POST_LIMIT]
	)
	terms = {p.id: post_terms(p) for p in posts}
	df = Counter(k for t in terms.values() for k in t)
	n = max(len(posts), 1)
	idf = {k: math.log(1 + n / c) for k, c in df.items()}
	# 같은 태그의 여러 표기(WIFI·Wi-Fi·wifi) 중 제목에 쓰인 모양 → 없으면 가장 많이 쓴 모양
	variants = defaultdict(Counter)
	for t in terms.values():
		for k, name in t.items():
			variants[k][name] += 1
	titles = " ".join(p.title or "" for p in posts)
	display = {}
	for k, c in variants.items():
		in_title = [v for v in c if v in titles]
		display[k] = max(in_title or c, key=lambda v: (c[v], v != v.upper()))
	title_norm = {p.id: norm(p.title) for p in posts}

	def sim(a, b):
		ta, tb = terms[a], terms[b]
		if not ta or not tb:
			return 0.0
		inter = sum(idf[k] for k in ta.keys() & tb.keys())
		small = min(sum(idf[k] for k in ta), sum(idf[k] for k in tb))
		return inter / small if small else 0.0   # 태그가 적은 쪽 대비 겹친 비율 (태그를 많이 단 글이 불리하지 않게)

	ids = [p.id for p in posts]
	S = {(a, b): sim(a, b) for i, a in enumerate(ids) for b in ids[i + 1:]}
	pair = lambda a, b: S.get((a, b), S.get((b, a), 0.0))

	# 평균 연결 군집
	clusters = [[i] for i in ids]
	while len(clusters) > 1:
		best, bi, bj = MERGE_MIN, -1, -1
		for i in range(len(clusters)):
			for j in range(i + 1, len(clusters)):
				ci, cj = clusters[i], clusters[j]
				avg = sum(pair(a, b) for a in ci for b in cj) / (len(ci) * len(cj))
				if avg > best:
					best, bi, bj = avg, i, j
		if bi < 0:
			break
		clusters[bi] += clusters.pop(bj)

	groups = sorted([c for c in clusters if len(c) > 1], key=len, reverse=True)
	rest = [i for c in clusters if len(c) == 1 for i in c]
	if len(groups) > MAX_GROUPS:
		rest += [i for c in groups[MAX_GROUPS:] for i in c]
		groups = groups[:MAX_GROUPS]

	hubs, hub_of = [], {}
	for gi, members in enumerate(groups):
		counts = Counter(k for m in members for k in terms[m])
		in_titles = {k: sum(1 for m in members if k in title_norm[m]) for k in counts}
		# 이름: 많이 나온 태그 → 제목에도 나오는 태그 → 더 드문 태그
		top = sorted(counts, key=lambda k: (-counts[k], -in_titles[k], df[k], k))[:3]
		key = f"g{gi}"
		hubs.append({"key": key, "label": display[top[0]], "tags": [display[k] for k in top], "count": len(members), "icon": "#", "url": hub_url})
		for m in members:
			hub_of[m] = key
	if rest:
		hubs.append({"key": "etc", "label": "기타", "tags": [], "count": len(rest), "icon": "…", "url": hub_url})
		for m in rest:
			hub_of[m] = "etc"

	# 글끼리 선
	score, kinds = defaultdict(float), defaultdict(set)

	def link(a, b, kind, w):
		if a == b:
			return
		k = (min(a, b), max(a, b))
		score[k] += w
		kinds[k].add(kind)

	by_slug = {p.slug: p for p in posts}
	series = defaultdict(list)
	for p in posts:
		if p.series_id:
			series[p.series_id].append(p)
	for items in series.values():
		items.sort(key=lambda p: (p.series_order or 0, p.published_at))
		for a, b in zip(items, items[1:]):
			link(a.id, b.id, "series", 1.0)
	for p in posts:
		for slug in set(LINK_RE.findall(p.content or "")):
			t = by_slug.get(unquote(slug))
			if t:
				link(p.id, t.id, "link", 1.0)
	for (a, b), s in S.items():
		if s >= EDGE_MIN:
			link(a, b, "tag", s)

	per_post = defaultdict(list)
	for k, w in score.items():
		per_post[k[0]].append((w, k))
		per_post[k[1]].append((w, k))
	keep = set()
	for items in per_post.values():
		items.sort(reverse=True)
		keep.update(k for _, k in items[:EDGE_PER_POST])
	edges = [{"a": a, "b": b, "w": round(score[(a, b)], 3), "kinds": sorted(kinds[(a, b)])} for a, b in sorted(keep)]
	connected = {e["a"] for e in edges} | {e["b"] for e in edges}

	nodes = [{
		"id": p.id, "title": p.title, "hub": hub_of[p.id],
		"url": reverse("blog:post_detail", args=[p.slug]),
		"connected": p.id in connected,
		"tags": list(terms[p.id].values())[:5],
	} for p in posts]
	return {
		"hubs": hubs,
		"nodes": nodes,
		"edges": edges,
		"stats": {"groups": len(groups), "posts": len(nodes), "edges": len(edges)},
	}
