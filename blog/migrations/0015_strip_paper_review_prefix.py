"""Paper(논문 리뷰) 카테고리가 생겨서 제목 앞 "[논문 리뷰]" 말머리는 뺌. 주소(slug)는 그대로 둬서 옛 링크 유지.

되돌리면 Paper 글 중 말머리가 없는 글 앞에 다시 붙임.
"""

from django.db import migrations

PREFIX = "[논문 리뷰]"


def forwards(apps, schema_editor):
	Post = apps.get_model("blog", "Post")
	for post in Post.objects.filter(category="paper", title__startswith=PREFIX):
		title = post.title[len(PREFIX):].strip()
		if title:
			post.title = title
			post.save(update_fields=["title"])   # updated_at 은 안 건드려서 '수정됨' 표시가 안 생김


def backwards(apps, schema_editor):
	Post = apps.get_model("blog", "Post")
	for post in Post.objects.filter(category="paper").exclude(title__startswith=PREFIX):
		post.title = f"{PREFIX} {post.title}"
		post.save(update_fields=["title"])


class Migration(migrations.Migration):

	dependencies = [
		("blog", "0014_paper_category_merge_free"),
	]

	operations = [
		migrations.RunPython(forwards, backwards),
	]
