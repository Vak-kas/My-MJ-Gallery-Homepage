from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("studio", "0010_internship_country_and_position_blank"),
    ]

    operations = [
        migrations.AlterField(
            model_name="research",
            name="lab_name",
            field=models.CharField(blank=True, max_length=200),
        ),
        migrations.AlterField(
            model_name="research",
            name="role",
            field=models.CharField(blank=True, max_length=200),
        ),
    ]
