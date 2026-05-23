from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("studio", "0011_research_optional_affiliation_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="teaching",
            name="end_date",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="teaching",
            name="is_current",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="teaching",
            name="start_date",
            field=models.DateField(blank=True, null=True),
        ),
    ]
