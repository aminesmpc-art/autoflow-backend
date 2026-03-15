"""Admin config for profiles and plans — with colored badges and quick actions."""
from django.contrib import admin
from django.utils.html import format_html
from unfold.admin import ModelAdmin

from .models import Profile, PlanType


@admin.register(Profile)
class ProfileAdmin(ModelAdmin):
    list_display = ("user", "plan_badge", "pro_status", "fair_use_flag", "whop_status", "last_seen_at", "created_at")
    list_filter = ("plan_type", "is_pro_active", "fair_use_flag")
    search_fields = ("user__email", "display_name", "whop_user_id")
    readonly_fields = ("created_at", "updated_at")
    list_editable = ("fair_use_flag",)
    list_per_page = 25
    actions = ["set_pro", "set_free", "clear_fair_use"]

    fieldsets = (
        ("User", {"fields": ("user", "display_name")}),
        ("Plan", {"fields": ("plan_type", "is_pro_active")}),
        ("Behavior", {"fields": ("fair_use_flag", "timezone", "last_seen_at")}),
        ("Whop Integration", {"fields": ("whop_user_id", "whop_membership_id")}),
        ("Dates", {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )

    @admin.display(description="Plan")
    def plan_badge(self, obj):
        if obj.plan_type == PlanType.PRO:
            return format_html(
                '<span style="background:#06b6d4;color:#fff;padding:2px 8px;border-radius:4px;font-size:11px;font-weight:600;">⚡ PRO</span>'
            )
        return format_html(
            '<span style="background:#374151;color:#9ca3af;padding:2px 8px;border-radius:4px;font-size:11px;">Free</span>'
        )

    @admin.display(description="Active", boolean=True)
    def pro_status(self, obj):
        return obj.is_pro_active

    @admin.display(description="Whop")
    def whop_status(self, obj):
        if obj.whop_membership_id:
            return format_html(
                '<span style="background:#065f46;color:#6ee7b7;padding:2px 8px;border-radius:4px;font-size:11px;">Connected</span>'
            )
        return format_html(
            '<span style="background:#374151;color:#6b7280;padding:2px 8px;border-radius:4px;font-size:11px;">—</span>'
        )

    @admin.action(description="⚡ Set selected profiles to Pro")
    def set_pro(self, request, queryset):
        count = queryset.update(plan_type=PlanType.PRO, is_pro_active=True)
        self.message_user(request, f"{count} profile(s) upgraded to Pro.")

    @admin.action(description="🔒 Set selected profiles to Free")
    def set_free(self, request, queryset):
        count = queryset.update(plan_type=PlanType.FREE, is_pro_active=False)
        self.message_user(request, f"{count} profile(s) set to Free.")

    @admin.action(description="🏳️ Clear fair-use flag")
    def clear_fair_use(self, request, queryset):
        count = queryset.update(fair_use_flag=False)
        self.message_user(request, f"Fair-use flag cleared for {count} profile(s).")
