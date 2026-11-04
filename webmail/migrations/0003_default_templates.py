# 기본 템플릿 6개 (없을 때만)
from django.db import migrations


def seed(apps, schema_editor):
	from webmail.models import DEFAULT_TEMPLATES

	MailTemplate = apps.get_model("webmail", "MailTemplate")
	if MailTemplate.objects.exists():
		return
	for name, subject, body in DEFAULT_TEMPLATES:
		MailTemplate.objects.create(name=name, subject=subject, body=body)


class Migration(migrations.Migration):
	dependencies = [("webmail", "0002_prefs_templates_contacts_schedule")]
	operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
