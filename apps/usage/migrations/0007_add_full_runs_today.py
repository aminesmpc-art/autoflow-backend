from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("usage", "0006_dailyusage_flow_runs_today_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="dailyusage",
            name="full_runs_today",
            field=models.PositiveIntegerField(default=0, help_text="Full queue runs today"),
        ),
    ]
