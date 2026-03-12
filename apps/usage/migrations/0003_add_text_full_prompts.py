"""Add text_prompts_used and full_prompts_used to DailyUsage."""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("usage", "0002_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="dailyusage",
            name="text_prompts_used",
            field=models.PositiveIntegerField(default=0, help_text="Text-to-video prompts (no images)"),
        ),
        migrations.AddField(
            model_name="dailyusage",
            name="full_prompts_used",
            field=models.PositiveIntegerField(default=0, help_text="Full-feature prompts (with images/frames)"),
        ),
    ]
