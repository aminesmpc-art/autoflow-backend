"""Admin config for profiles and plans."""
from django.contrib import admin

from .models import Profile


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "plan_type", "is_pro_active", "fair_use_flag", "last_seen_at", "created_at")
    list_filter = ("plan_type", "is_pro_active", "fair_use_flag")
    search_fields = ("user__email", "display_name")
    readonly_fields = ("created_at", "updated_at")
    list_editable = ("plan_type", "is_pro_active", "fair_use_flag")

    fieldsets = (
        (None, {"fields": ("user", "display_name", "plan_type", "is_pro_active")}),
        ("Behavior", {"fields": ("fair_use_flag", "timezone", "last_seen_at")}),
        ("Whop", {"fields": ("whop_user_id", "whop_membership_id")}),
        ("Dates", {"fields": ("created_at", "updated_at")}),
    )
