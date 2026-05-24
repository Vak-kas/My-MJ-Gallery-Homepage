from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("studio", "0021_publication"),
    ]

    operations = [
        migrations.AddField(
            model_name="award",
            name="award_category",
            field=models.CharField(
                choices=[("campus", "교내"), ("external", "대외"), ("other", "기타")],
                default="other",
                max_length=20,
            ),
        ),
    ]
