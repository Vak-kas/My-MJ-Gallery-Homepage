"""블로그 허브의 "이번 주 기록" 카드 — 사이트 주인(관리자)이 쓴 글을 주 단위로 셈.

- 주는 월요일 시작, 서울 시간 기준
- 카테고리별 이번 주 글 수 / 목표 (목표·아이콘은 Studio › Categories)
- 최근 26주 막대, 연속 기록(이번 주에 아직 안 썼으면 지난주까지 이어진 만큼)
- 관리자 전용 카테고리(Secret 등)는 관리자에게만 보임

구성은 minter-v1.com (github.com/Minter-v1/Minter-blog) 의 주간 기록 카드를 참고해 직접 구현
"""

from datetime import timedelta

from django.utils import timezone

from . import categories
from .models import Post

WEEKS = 26


def week_start(day):
	return day - timedelta(days=day.weekday())


def weekly_stats(goals=None, include_secret=False, today=None):
	"""goals 를 안 주면 각 카테고리의 주간 목표(Category.weekly_goal)를 씀"""
	today = today or timezone.localdate()
	this_week = week_start(today)
	first_week = this_week - timedelta(weeks=WEEKS - 1)

	qs = Post.objects.filter(
		is_published=True,
		author__is_superuser=True,
		published_at__date__gte=first_week,
	)
	if not include_secret:
		qs = qs.filter(category__in=categories.public_slugs())

	per_week = [0] * WEEKS
	this_week_by_cat = {}
	for published_at, category in qs.values_list("published_at", "category"):
		day = timezone.localtime(published_at).date()
		idx = (week_start(day) - first_week).days // 7
		if 0 <= idx < WEEKS:
			per_week[idx] += 1
			if idx == WEEKS - 1:
				this_week_by_cat[category] = this_week_by_cat.get(category, 0) + 1

	rows = []
	for c in categories.all_categories():
		if c.is_private and not include_secret:
			continue
		goal = int((goals.get(c.slug) if goals is not None else c.weekly_goal) or 0)
		count = this_week_by_cat.get(c.slug, 0)
		if goal or count:
			rows.append({"key": c.slug, "label": c.name, "icon": c.icon, "count": count, "goal": goal, "done": goal and count >= goal})

	total = per_week[-1]
	goal_total = sum(r["goal"] for r in rows)

	# 연속 기록: 이번 주에 썼으면 이번 주부터, 아니면 지난주부터 거꾸로
	streak = 0
	start = WEEKS - 1 if per_week[-1] else WEEKS - 2
	for i in range(start, -1, -1):
		if not per_week[i]:
			break
		streak += 1

	peak = max(per_week) or 1
	bars = []
	prev_month = None
	for i, n in enumerate(per_week):
		monday = first_week + timedelta(weeks=i)
		month_label = f"{monday.month}월" if monday.month != prev_month else ""
		prev_month = monday.month
		bars.append({
			"count": n,
			"height": round(100 * n / peak) if n else 0,
			"label": "이번 주" if i == WEEKS - 1 else month_label,
			"current": i == WEEKS - 1,
			"title": f"{monday:%m.%d} 주 · {n}개",
		})

	return {
		"total": total,
		"goal_total": goal_total,
		"percent": min(100, round(100 * total / goal_total)) if goal_total else (100 if total else 0),
		"rows": rows,
		"streak": streak,
		"bars": bars,
	}
