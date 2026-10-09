from django.db import migrations


def forward(apps, schema_editor):
	"""예전 등급 그룹 'friends'(친한 사람)를 'vip'(VIP 회원)로 이름만 바꿈 — 지정해 둔 회원은 그대로."""
	Group = apps.get_model("auth", "Group")
	old = Group.objects.filter(name="friends").first()
	if not old:
		return
	new = Group.objects.filter(name="vip").first()
	if new:
		new.user_set.add(*old.user_set.all())
		old.delete()
	else:
		old.name = "vip"
		old.save(update_fields=["name"])


def backward(apps, schema_editor):
	Group = apps.get_model("auth", "Group")
	Group.objects.filter(name="vip").update(name="friends")


class Migration(migrations.Migration):
	dependencies = [
		("auth", "0012_alter_user_first_name_max_length"),
		("tools", "0006_aiusage_ocr"),
	]

	operations = [migrations.RunPython(forward, backward)]
