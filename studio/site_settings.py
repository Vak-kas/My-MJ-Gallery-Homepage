"""사이트 설정(내비 메뉴, 홈 섹션) 읽기·저장.

- 내비 메뉴 상태: public(모두) / members(로그인 회원만) / admin(숨김 — 관리자만 보고 들어갈 수 있음)
  숨기거나 회원 전용으로 하면 메뉴뿐 아니라 그 페이지 자체도 막힘 (middleware.SectionAccessMiddleware)
  - 회원만: 링크(토큰)로 여는 공유 페이지는 비로그인도 계속 열림
  - 숨김: 관리자 말고는 공유 링크까지 모두 막힘
- 홈 섹션: 켜기/끄기 + 순서 (끈 섹션도 관리자에게는 "숨김" 표시와 함께 보임)
- 관리자는 무엇을 닫아도 전부 볼 수 있음
"""

import re

from django.core.cache import cache
from django.urls import reverse

CACHE_KEY = "studio:site_settings"

NAV_DEFAULTS = [
    {"key": "home", "label": "Home", "url_name": "main:home", "state": "public", "fixed": True},
    {"key": "blog", "label": "Blog", "url_name": "blog:index", "state": "public"},
    {"key": "tool", "label": "Tool", "url_name": "tools:index", "state": "public"},
    {"key": "photo", "label": "Gallery", "url_name": "main:photos", "state": "public"},
    {"key": "game", "label": "Game", "url_name": "games:index", "state": "public"},
]
NAV_STATES = [("public", "모두에게 공개"), ("members", "로그인 회원만"), ("admin", "숨김 (관리자만)")]

# 메뉴 key → 막을 경로 접두사. 링크(토큰)로 여는 공유용 페이지는 메뉴를 숨겨도 계속 열림
SECTION_PATHS = {
    "blog": ["/blog/"],
    "tool": ["/tools/"],
    "photo": ["/photos/"],
    "game": ["/games/"],
}
ALWAYS_OPEN = [re.compile(p) for p in (
    r"^/tools/share/[^/]+/(download/)?$",          # 맡겨두기 다운로드
    r"^/tools/stream/[^/]+/(join/)?$",              # 데이터 전송 방 링크
    r"^/tools/secret/[^/]+/(reveal/)?$",            # 비밀 메모 열기
    r"^/tools/live/[^/]+/$",                        # 라이브 방송 시청 링크
    r"^/tools/meet/[^/]+/(state/|join/|save/|remove/)?$",  # 팀플 일정 참여 링크
    r"^/games/(omok|othello|catchmind)/(?!new/)[^/]+/$",    # 오목·오셀로·그림 맞추기 방 초대 링크
    r"^/blog/api/",                                 # 에디터 API (관리자 글쓰기)
)]

HOME_SECTION_DEFAULTS = [
    {"key": "profile", "label": "Profile · 소개", "enabled": True},
    {"key": "skill", "label": "Skills · 기술", "enabled": True},
    {"key": "career", "label": "Career · 경력", "enabled": True},
    {"key": "activity", "label": "Activity · 활동", "enabled": True},
    {"key": "award", "label": "Awards · 수상", "enabled": True},
    {"key": "publication", "label": "Publications · 논문", "enabled": True},
    {"key": "project", "label": "Projects · 프로젝트", "enabled": True},
    {"key": "blog_links", "label": "블로그 바로가기 (맨 아래 NEXT STEP)", "enabled": True},
]


def _merge(saved, defaults, keep_fields):
    """저장된 순서·값을 기본 목록에 입히기. 새로 생긴 항목은 뒤에, 없어진 항목은 버림."""
    by_key = {d["key"]: d for d in defaults}
    result, seen = [], set()
    for item in saved or []:
        key = item.get("key")
        if key in by_key and key not in seen:
            merged = dict(by_key[key])
            for f in keep_fields:
                if f in item:
                    merged[f] = item[f]
            result.append(merged)
            seen.add(key)
    result += [dict(d) for d in defaults if d["key"] not in seen]
    return result


def load():
    data = cache.get(CACHE_KEY)
    if data is None:
        from .models import SiteSetting
        row = SiteSetting.objects.first()
        data = {
            "nav": _merge(row.nav_items if row else [], NAV_DEFAULTS, ("label", "state")),
            "home": _merge(row.home_sections if row else [], HOME_SECTION_DEFAULTS, ("enabled",)),
        }
        for item in data["nav"]:
            if item.get("fixed"):
                item["state"] = "public"
            if item["state"] not in dict(NAV_STATES):
                item["state"] = "public"
        cache.set(CACHE_KEY, data, 300)
    return data


def save(nav, home):
    from .models import SiteSetting
    row = SiteSetting.objects.first() or SiteSetting()
    row.nav_items = [{"key": i["key"], "label": i["label"], "state": i["state"]} for i in nav]
    row.home_sections = [{"key": s["key"], "enabled": s["enabled"]} for s in home]
    row.save()
    cache.delete(CACHE_KEY)


def can_see(state, user):
    if state == "public":
        return True
    if state == "members":
        return user.is_authenticated
    return user.is_authenticated and user.is_superuser


def visible_nav(user):
    items = []
    for item in load()["nav"]:
        if can_see(item["state"], user):
            items.append({**item, "url": reverse(item["url_name"]), "restricted": item["state"] != "public"})
    return items


def section_for_path(path):
    """(메뉴 key, 링크로 여는 공유 페이지인지)"""
    for key, prefixes in SECTION_PATHS.items():
        if any(path.startswith(p) for p in prefixes):
            return key, any(p.match(path) for p in ALWAYS_OPEN)
    return None, False


def nav_state(key):
    return next((i["state"] for i in load()["nav"] if i["key"] == key), "public")


def home_sections(user):
    """보여줄 홈 섹션. 관리자에게는 끈 섹션도 hidden=True 로 함께 돌려줌."""
    is_admin = user.is_authenticated and user.is_superuser
    return [{**s, "hidden": not s["enabled"]} for s in load()["home"] if s["enabled"] or is_admin]
