from django.db import migrations

EXPR = "to_tsvector('english', coalesce(clause, '') || ' ' || coalesce(title, '') || ' ' || text)"


def forwards(apps, schema_editor):
	# PostgreSQL 에서만: 표준 서재 전문 검색용 GIN 색인 (SQLite 는 icontains 로 대신 찾음)
	if schema_editor.connection.vendor == "postgresql":
		schema_editor.execute(f"CREATE INDEX IF NOT EXISTS tools_stdchunk_fts ON tools_stdchunk USING GIN ({EXPR})")


def backwards(apps, schema_editor):
	if schema_editor.connection.vendor == "postgresql":
		schema_editor.execute("DROP INDEX IF EXISTS tools_stdchunk_fts")


class Migration(migrations.Migration):
	dependencies = [("tools", "0010_stdlib")]
	operations = [migrations.RunPython(forwards, backwards)]
