from django.db import migrations

EXPR = "to_tsvector('english', coalesce(clause, '') || ' ' || coalesce(title, '') || ' ' || text)"


def forwards(apps, schema_editor):
	# PostgreSQL 에서만: 3GPP 본문 검색용 GIN 색인 (SQLite 는 icontains 로 대신 찾음)
	if schema_editor.connection.vendor == "postgresql":
		schema_editor.execute(f"CREATE INDEX IF NOT EXISTS tools_specchunk_fts ON tools_specchunk USING GIN ({EXPR})")


def backwards(apps, schema_editor):
	if schema_editor.connection.vendor == "postgresql":
		schema_editor.execute("DROP INDEX IF EXISTS tools_specchunk_fts")


class Migration(migrations.Migration):
	dependencies = [("tools", "0015_specdocs")]
	operations = [migrations.RunPython(forwards, backwards)]
