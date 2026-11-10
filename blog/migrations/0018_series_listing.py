from django.db import migrations, models


def number_existing(apps, schema_editor):
	"""있던 시리즈는 최근에 만든 것부터 순서를 매김 (Studio › Series 에서 바꿀 수 있음)"""
	Series = apps.get_model("blog", "Series")
	for order, s in enumerate(Series.objects.order_by("-created_at", "-id")):
		s.order = order
		s.save(update_fields=["order"])


class Migration(migrations.Migration):

	dependencies = [
		("blog", "0017_category_table"),
	]

	operations = [
		migrations.AlterModelOptions(name="series", options={"ordering": ["order", "-id"]}),
		migrations.AddField(model_name="series", name="order", field=models.PositiveIntegerField(default=0)),
		migrations.AddField(model_name="series", name="is_listed", field=models.BooleanField(default=True, verbose_name="시리즈 모음에 보이기")),
		migrations.AddField(model_name="series", name="show_on_hub", field=models.BooleanField(default=True, verbose_name="블로그 허브에 보이기")),
		migrations.RunPython(number_existing, migrations.RunPython.noop),
	]
