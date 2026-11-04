# (예전) 기본 템플릿을 넣던 마이그레이션 — 템플릿 기능을 뺐으므로 아무것도 안 함 (이력만 유지)
from django.db import migrations


class Migration(migrations.Migration):
	dependencies = [("webmail", "0002_prefs_templates_contacts_schedule")]
	operations = [migrations.RunPython(migrations.RunPython.noop, migrations.RunPython.noop)]
