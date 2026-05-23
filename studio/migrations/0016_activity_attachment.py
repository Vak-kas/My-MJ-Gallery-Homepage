from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("studio", "0015_remove_contest_from_activity_type"),
    ]

    operations = [
        migrations.AddField(
            model_name="activity",
            name="attachment",
            field=models.FileField(blank=True, null=True, upload_to="activity/"),
        ),
    ]
