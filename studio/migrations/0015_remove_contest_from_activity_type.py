from django.db import migrations, models


def move_contest_to_other(apps, schema_editor):
    Activity = apps.get_model("studio", "Activity")
    Activity.objects.filter(activity_type="contest").update(activity_type="other")


class Migration(migrations.Migration):

    dependencies = [
        ("studio", "0014_alter_activity_activity_type"),
    ]

    operations = [
        migrations.RunPython(move_contest_to_other, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="activity",
            name="activity_type",
            field=models.CharField(
                choices=[
                    ("external_program", "External Program"),
                    ("community", "Community"),
                    ("seminar", "Seminar"),
                    ("volunteer", "Volunteer"),
                    ("other", "Other"),
                ],
                default="external_program",
                max_length=20,
            ),
        ),
    ]
