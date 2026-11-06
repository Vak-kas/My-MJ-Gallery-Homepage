"""Free(자유게시판, "board") 를 Life 로 합치고 논문 리뷰 카테고리 Paper("paper") 를 새로 만듦.

- board 글 → life (글·댓글·태그는 그대로, 카테고리 값만 바꿈)
- Tech 글 중 제목이 "[논문 리뷰]" 로 시작하는 글 → paper
- 되돌리면 paper → tech 만 되돌림 (어느 글이 원래 board 였는지는 남지 않음)
- 사이트 설정의 주간 목표에 남은 "board" 키는 지움
"""

from django.db import migrations, models

PAPER_PREFIX = "[논문 리뷰]"


def forwards(apps, schema_editor):
	Post = apps.get_model("blog", "Post")
	Post.objects.filter(category="board").update(category="life")
	Post.objects.filter(category="tech", title__startswith=PAPER_PREFIX).update(category="paper")
	try:
		SiteSetting = apps.get_model("studio", "SiteSetting")
	except LookupError:
		return
	for row in SiteSetting.objects.all():
		goals = row.blog_goals or {}
		if "board" in goals:
			goals.pop("board")
			row.blog_goals = goals
			row.save(update_fields=["blog_goals"])


def backwards(apps, schema_editor):
	Post = apps.get_model("blog", "Post")
	Post.objects.filter(category="paper").update(category="tech")


class Migration(migrations.Migration):

	dependencies = [
		("blog", "0013_post_category_free"),
		("studio", "0035_site_blog_goals"),
	]

	operations = [
		migrations.AlterField(
			model_name="post",
			name="category",
			field=models.CharField(choices=[("tech", "Tech"), ("paper", "Paper"), ("life", "Life"), ("secret", "Secret")], db_index=True, max_length=20),
		),
		migrations.RunPython(forwards, backwards),
	]
