from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("studio", "0008_education_internship_leadership_research_teaching_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="education",
            name="degree",
            field=models.CharField(
                choices=[
                    ("none", "- (해당없음)"),
                    ("bachelor", "학부"),
                    ("master", "석사"),
                    ("phd", "박사"),
                ],
                default="none",
                max_length=20,
            ),
        ),
    ]
