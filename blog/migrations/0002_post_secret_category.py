from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("blog", "0001_initial"),
    ]

    operations = [
        migrations.AlterField(
            model_name="post",
            name="category",
            field=models.CharField(
                choices=[
                    ("tech", "Tech"),
                    ("board", "Board"),
                    ("life", "Life"),
                    ("secret", "Secret"),
                ],
                db_index=True,
                max_length=20,
            ),
        ),
    ]
