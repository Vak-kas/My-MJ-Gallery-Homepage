"""태그 이름 앞의 # 떼기 (#3GPP → 3GPP). 같은 이름이 이미 있으면 글을 옮기고 합침."""

from django.db import migrations
from django.utils.text import slugify


def strip_hashes(apps, schema_editor):
	Tag = apps.get_model("blog", "Tag")
	for tag in Tag.objects.filter(name__startswith="#"):
		name = " ".join(tag.name.lstrip("#").split())[:40]
		if not name:
			tag.delete()
			continue
		slug = slugify(name, allow_unicode=True) or name[:60]
		other = Tag.objects.filter(name=name).exclude(pk=tag.pk).first() or Tag.objects.filter(slug=slug).exclude(pk=tag.pk).first()
		if other:
			for post in tag.posts.all():
				post.tags.add(other)
			tag.delete()
		else:
			tag.name, tag.slug = name, slug
			tag.save(update_fields=["name", "slug"])


class Migration(migrations.Migration):
	dependencies = [("blog", "0011_post_series_order_series_post_series_and_more")]
	operations = [migrations.RunPython(strip_hashes, migrations.RunPython.noop)]
