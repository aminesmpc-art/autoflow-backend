"""Admin config for reward credits — with status badges."""
from django.contrib import admin
from django.utils.html import format_html
from unfold.admin import ModelAdmin

from .models import RewardCreditLedger


@admin.register(RewardCreditLedger)
class RewardCreditLedgerAdmin(ModelAdmin):
    list_display = ("user", "amount_badge", "source", "status_badge", "reference_id", "created_at")
    list_filter = ("source", "status")
    search_fields = ("user__email", "reference_id")
    readonly_fields = ("created_at",)
    date_hierarchy = "created_at"
    list_per_page = 50

    @admin.display(description="Amount")
    def amount_badge(self, obj):
        if obj.amount > 0:
            return format_html(
                '<span style="color:#10b981;font-weight:600;">+{}</span>', obj.amount
            )
        return format_html(
            '<span style="color:#dc2626;font-weight:600;">{}</span>', obj.amount
        )

    @admin.display(description="Status")
    def status_badge(self, obj):
        colors = {
            "active": ("#065f46", "#6ee7b7"),
            "expired": ("#7f1d1d", "#fca5a5"),
            "used": ("#374151", "#6b7280"),
        }
        bg, fg = colors.get(obj.status, ("#374151", "#9ca3af"))
        return format_html(
            '<span style="background:{};color:{};padding:2px 8px;border-radius:4px;font-size:11px;">{}</span>',
            bg, fg, obj.status.title(),
        )
