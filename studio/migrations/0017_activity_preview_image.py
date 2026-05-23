from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("studio", "0016_activity_attachment"),
    ]

    operations = [
        migrations.AddField(
            model_name="activity",
            name="preview_image",
            field=models.ImageField(blank=True, null=True, upload_to="activity/previews/"),
        ),
    ]
