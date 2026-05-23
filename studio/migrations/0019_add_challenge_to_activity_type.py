from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("studio", "0018_alter_activity_file_field_lengths"),
    ]

    operations = [
        migrations.AlterField(
            model_name="activity",
            name="activity_type",
            field=models.CharField(
                choices=[
                    ("external_program", "External Program"),
                    ("community", "Community"),
                    ("seminar", "Seminar"),
                    ("volunteer", "Volunteer"),
                    ("challenge", "Challenge"),
                    ("other", "Other"),
                ],
                default="external_program",
                max_length=20,
            ),
        ),
    ]
