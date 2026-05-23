from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("studio", "0017_activity_preview_image"),
    ]

    operations = [
        migrations.AlterField(
            model_name="activity",
            name="attachment",
            field=models.FileField(blank=True, max_length=255, null=True, upload_to="activity/"),
        ),
        migrations.AlterField(
            model_name="activity",
            name="preview_image",
            field=models.ImageField(blank=True, max_length=255, null=True, upload_to="activity/previews/"),
        ),
    ]
