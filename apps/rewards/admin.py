"""Admin config for reward credits."""
from django.contrib import admin

from .models import RewardCreditLedger


@admin.register(RewardCreditLedger)
class RewardCreditLedgerAdmin(admin.ModelAdmin):
    list_display = ("user", "amount", "source", "status", "reference_id", "created_at")
    list_filter = ("source", "status")
    search_fields = ("user__email", "reference_id")
    readonly_fields = ("created_at",)
    date_hierarchy = "created_at"
