"""카테고리를 코드에서 표(Category)로 옮김 — Studio › Categories 에서 관리.

지금 있는 Tech · Algorithm · Paper · Life · Secret 를 그대로 만들고(색·설명·아이콘·노출 그대로),
주간 목표는 사이트 설정(SiteSetting.blog_goals)에 있던 값을 옮김. 글 데이터는 바꾸지 않음.
"""

from django.db import migrations, models

SEED = [
	# slug, 이름, 설명, 색, 아이콘, 관리자 전용, 허브 카드, 홈 바로가기, Topic Map, 기본 주간 목표
	("tech", "Tech", "기술 블로그 · 개발 노트 · 트러블슈팅", "#0066cc", "🛠️", False, True, True, True, 1),
	("algorithm", "Algorithm", "문제 풀이 · 개념 정리", "#0d9488", "🧩", False, True, True, False, 0),
	("paper", "Paper", "논문 리뷰 · 읽은 논문 정리", "#8b5cf6", "📄", False, True, True, False, 0),
	("life", "Life", "일상 · 후기 · 자유 글", "#10b981", "🌿", False, True, True, False, 1),
	("secret", "Secret", "너드인의 새벽 · 관리자 비공개 메모 공간", "#dc2626", "🔒", True, True, False, False, 0),
]


def seed(apps, schema_editor):
	Category = apps.get_model("blog", "Category")
	goals = {}
	try:
		SiteSetting = apps.get_model("studio", "SiteSetting")
		row = SiteSetting.objects.first()
		goals = (row.blog_goals or {}) if row else {}
	except LookupError:
		pass
	for order, (slug, name, desc, color, icon, private, hub, home, topic, goal) in enumerate(SEED):
		saved = goals.get(slug, goal)
		Category.objects.get_or_create(slug=slug, defaults=dict(
			name=name, description=desc, color=color, icon=icon, order=order, is_private=private,
			show_on_hub=hub, show_on_home=home, in_topic_map=topic,
			weekly_goal=max(0, min(50, int(saved))) if str(saved).isdigit() else goal,
		))


class Migration(migrations.Migration):

	dependencies = [
		("blog", "0016_algorithm_category"),
		("studio", "0035_site_blog_goals"),
	]

	operations = [
		migrations.CreateModel(
			name="Category",
			fields=[
				("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
				("slug", models.SlugField(max_length=30, unique=True, verbose_name="주소")),
				("name", models.CharField(max_length=30, verbose_name="이름")),
				("description", models.CharField(blank=True, max_length=120, verbose_name="설명")),
				("color", models.CharField(default="#0066cc", max_length=7, verbose_name="색")),
				("icon", models.CharField(blank=True, default="📝", max_length=8, verbose_name="아이콘")),
				("order", models.PositiveIntegerField(default=0)),
				("is_private", models.BooleanField(default=False, verbose_name="관리자 전용")),
				("show_on_hub", models.BooleanField(default=True, verbose_name="블로그 허브 카드")),
				("show_on_home", models.BooleanField(default=True, verbose_name="홈 블로그 바로가기")),
				("in_topic_map", models.BooleanField(default=False, verbose_name="Topic Map 포함")),
				("weekly_goal", models.PositiveSmallIntegerField(default=0, verbose_name="주간 목표")),
				("created_at", models.DateTimeField(auto_now_add=True)),
			],
			options={"ordering": ["order", "id"]},
		),
		migrations.AlterField(
			model_name="post",
			name="category",
			field=models.CharField(db_index=True, max_length=30),
		),
		migrations.RunPython(seed, migrations.RunPython.noop),
	]
