import logging
from datetime import date
from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Sum

from apps.usage.models import DailyUsage, UsageEvent

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = "Recalculates granular prompt usage metrics from UsageEvent records for all DailyUsage entries."

    def handle(self, *args, **options):
        self.stdout.write("Starting usage recalculation...")
        
        daily_usages = DailyUsage.objects.all()
        updated_count = 0

        with transaction.atomic():
            for usage in daily_usages:
                user = usage.user
                usage_date = usage.date

                # Find all consume events for this user on this date
                consume_events = UsageEvent.objects.filter(
                    user=user,
                    event_type=UsageEvent.EventType.CONSUME_PROMPT,
                    created_at__date=usage_date
                )

                # Find all download events for this user on this date
                download_events = UsageEvent.objects.filter(
                    user=user,
                    event_type=UsageEvent.EventType.DOWNLOAD_COMPLETED,
                    created_at__date=usage_date
                )

                # Tally up prompts
                text_prompts = 0
                full_prompts = 0
                free_prompts = 0
                reward_prompts = 0
                total_prompts = 0

                for event in consume_events:
                    count = event.prompt_count
                    total_prompts += count
                    
                    meta = event.metadata or {}
                    prompt_type = meta.get("prompt_type", "text")
                    source_used = meta.get("source_used", "free")
                    
                    if prompt_type == "full":
                        full_prompts += count
                    else:
                        text_prompts += count
                        
                    if source_used == "free":
                        free_prompts += count
                    elif source_used == "reward":
                        reward_prompts += count

                # Tally up downloads
                downloads = download_events.aggregate(total=Sum("prompt_count"))["total"] or 0

                # Update usage record if it needs it
                if (usage.text_prompts_used != text_prompts or 
                    usage.full_prompts_used != full_prompts or 
                    usage.free_prompts_used != free_prompts or
                    usage.reward_prompts_used != reward_prompts or
                    usage.total_prompts_used != total_prompts or
                    usage.downloads_used != downloads):
                    
                    usage.text_prompts_used = text_prompts
                    usage.full_prompts_used = full_prompts
                    usage.free_prompts_used = free_prompts
                    usage.reward_prompts_used = reward_prompts
                    usage.total_prompts_used = total_prompts
                    usage.downloads_used = downloads
                    usage.save()
                    updated_count += 1

        self.stdout.write(self.style.SUCCESS(f"✅ Successfully recalculated {updated_count} DailyUsage records."))
