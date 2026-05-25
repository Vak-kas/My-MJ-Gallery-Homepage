from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("studio", "0022_award_category"),
    ]

    operations = [
        migrations.CreateModel(
            name="Certification",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=200)),
                ("issuer", models.CharField(blank=True, max_length=200)),
                ("score", models.CharField(blank=True, max_length=80)),
                ("acquired_date", models.DateField(blank=True, null=True)),
                ("expiration_date", models.DateField(blank=True, null=True)),
                ("credential_id", models.CharField(blank=True, max_length=120)),
                ("url", models.URLField(blank=True)),
                ("description", models.TextField(blank=True)),
                ("is_visible", models.BooleanField(default=True)),
                ("order", models.PositiveIntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"ordering": ["order", "-acquired_date", "id"]},
        ),
    ]
