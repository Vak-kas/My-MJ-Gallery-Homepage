from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("studio", "0009_education_degree"),
    ]

    operations = [
        migrations.AddField(
            model_name="internship",
            name="country",
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AlterField(
            model_name="internship",
            name="position",
            field=models.CharField(blank=True, max_length=200),
        ),
    ]
