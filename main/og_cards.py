"""페이지별 링크 미리보기 카드 (Tool 목록·각 도구·블로그·갤러리·시리즈).

/og/<kind>/<key>.png 로 그려서 media/og/pages/ 에 저장해 두고 재사용. 내용이 바뀌면 파일 이름(해시)이 바뀜.
"""

import hashlib

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.urls import reverse

BLUE, GREEN, ORANGE, PURPLE, GOLD = (10, 132, 255), (16, 185, 129), (249, 115, 22), (139, 92, 246), (212, 175, 55)

PAGES = {
    "blog": {"title": "Blog", "subtitle": "기술 글 · 일상 기록", "pill": "BLOG", "accent": BLUE, "eyebrow": "SMJ GALLERY"},
    "all": {"title": "All Posts", "subtitle": "모든 카테고리의 글", "pill": "ALL", "accent": BLUE, "eyebrow": "SMJ GALLERY · BLOG"},
    "series": {"title": "Series", "subtitle": "주제별로 이어서 읽는 글 묶음", "pill": "SERIES", "accent": BLUE, "eyebrow": "SMJ GALLERY · BLOG"},
    "gallery": {"title": "Gallery", "subtitle": "사진으로 남긴 순간들", "pill": "PHOTO", "accent": GOLD, "eyebrow": "SMJ GALLERY"},
    "games": {"title": "Game", "subtitle": "사다리타기 · 돌림판 · 2048 · 한글 타자 연습", "pill": "GAME", "accent": GREEN, "eyebrow": "SMJ GALLERY"},
}


def tool_spec(slug):
    from tools.registry import TOOLS

    if slug == "index":
        return {"title": "Tool", "subtitle": "살면서 ‘이런 게 있었으면’ 싶었던 것들을 하나씩 직접 만들어 모아두었습니다", "pill": f"{len(TOOLS)} TOOLS",
                "accent": PURPLE, "eyebrow": "SMJ GALLERY", "footer": "로그인 없이 바로 쓰는 도구도 많아요"}
    tool = next((t for t in TOOLS if t["slug"] == slug), None)
    if not tool:
        return None
    member = tool.get("access") == "member"
    return {"title": tool["title"], "subtitle": tool["description"], "pill": "회원 전용" if member else "TOOL",
            "accent": ORANGE if member else PURPLE, "eyebrow": "SMJ GALLERY · TOOL", "footer": " · ".join(tool.get("tags", []))}


def series_spec(slug):
    from blog.models import Post, Series

    series = Series.objects.filter(slug=slug).first()
    if not series:
        return None
    count = Post.objects.filter(series=series, is_published=True, visibility=Post.VISIBILITY_PUBLIC).count()
    if not count:
        return None
    author = series.author.first_name or series.author.username if series.author else ""
    return {"title": series.name, "subtitle": series.description, "pill": f"{count}편 시리즈", "accent": BLUE,
            "eyebrow": "SMJ GALLERY · SERIES", "footer": author}


def game_spec(slug):
    from games.registry import GAMES

    game = next((g for g in GAMES if g["slug"] == slug and g["url_name"]), None)
    if not game:
        return None
    return {"title": game["title"], "subtitle": game["description"], "pill": "GAME", "accent": GREEN,
            "eyebrow": "SMJ GALLERY · GAME", "footer": " · ".join(game.get("tags", []))}


def _category_names():
    from blog.categories import all_categories

    return " · ".join(c.name for c in all_categories() if not c.is_private)


def category_spec(slug):
    """블로그 카테고리 목록 카드 — 이름·설명·색은 Studio › Categories 값. 관리자 전용은 없음"""
    from blog.categories import exists, get, hex_to_rgb

    if not exists(slug):
        return None
    info = get(slug)
    if info.is_private:
        return None
    return {"title": info.name, "subtitle": info.description, "pill": info.name.upper(), "accent": hex_to_rgb(info.color),
            "eyebrow": "SMJ GALLERY · BLOG"}


def spec(kind, key):
    if kind == "page":
        page = PAGES.get(key)
        if page and key in ("blog", "all"):   # 카테고리 이름은 Studio 에서 바뀌므로 그때그때
            page = {**page, "subtitle": _category_names() or page["subtitle"]}
        return page
    if kind == "category":
        return category_spec(key)
    if kind == "tool":
        return tool_spec(key)
    if kind == "series":
        return series_spec(key)
    if kind == "game":
        return game_spec(key)
    return None


def _key(spec_dict):
    raw = "v1|" + "|".join(str(spec_dict.get(k, "")) for k in ("title", "subtitle", "pill", "accent", "eyebrow", "footer"))
    return hashlib.sha1(raw.encode()).hexdigest()[:10]


def image_url(kind, key):
    """og:image 에 넣을 주소 (내용 해시를 붙여 카톡 캐시도 갱신)."""
    s = spec(kind, key)
    if not s:
        return None
    return reverse("og_card", args=[kind, key]) + f"?v={_key(s)}"


def get_or_create(kind, key):
    from blog.og_image import render_card

    s = spec(kind, key)
    if not s:
        return None
    path = f"og/pages/{kind}-{key}-{_key(s)}.png"
    if not default_storage.exists(path):
        default_storage.save(path, ContentFile(render_card(**{k: s[k] for k in ("title", "subtitle", "pill", "accent", "eyebrow", "footer") if k in s})))
    return path
