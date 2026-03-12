"""Admin config for usage tracking."""
from django.contrib import admin

from .models import DailyUsage, UsageEvent


@admin.register(DailyUsage)
class DailyUsageAdmin(admin.ModelAdmin):
    list_display = ("user", "date", "free_prompts_used", "reward_prompts_used", "total_prompts_used")
    list_filter = ("date",)
    search_fields = ("user__email",)
    readonly_fields = ("created_at", "updated_at")
    date_hierarchy = "date"


@admin.register(UsageEvent)
class UsageEventAdmin(admin.ModelAdmin):
    list_display = ("user", "event_type", "prompt_count", "created_at")
    list_filter = ("event_type", "created_at")
    search_fields = ("user__email",)
    readonly_fields = ("created_at",)
    date_hierarchy = "created_at"
