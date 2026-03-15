"""Admin config for users — full-featured interface with inline profile."""
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.utils.html import format_html
from unfold.admin import ModelAdmin, StackedInline

from apps.plans.models import Profile
from .models import CustomUser, EmailVerificationToken


class ProfileInline(StackedInline):
    """Show profile directly on the user edit page."""
    model = Profile
    can_delete = False
    verbose_name = "Profile & Plan"
    verbose_name_plural = "Profile & Plan"
    readonly_fields = ("created_at", "updated_at")
    fieldsets = (
        ("Plan", {"fields": ("plan_type", "is_pro_active", "display_name")}),
        ("Behavior", {"fields": ("fair_use_flag", "timezone", "last_seen_at")}),
        ("Whop", {"fields": ("whop_user_id", "whop_membership_id")}),
        ("Dates", {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )


@admin.register(CustomUser)
class CustomUserAdmin(BaseUserAdmin, ModelAdmin):
    list_display = ("email", "plan_badge", "is_active_badge", "is_staff", "last_seen", "created_at")
    list_filter = ("is_active", "is_staff", "is_superuser", "profile__plan_type", "profile__is_pro_active")
    search_fields = ("email",)
    ordering = ("-created_at",)
    readonly_fields = ("created_at", "updated_at")
    list_per_page = 25
    inlines = [ProfileInline]
    actions = ["activate_users", "deactivate_users", "grant_pro", "revoke_pro"]

    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Status", {"fields": ("is_active", "is_staff", "is_superuser")}),
        ("Dates", {"fields": ("created_at", "updated_at", "last_login")}),
        ("Permissions", {"fields": ("groups", "user_permissions"), "classes": ("collapse",)}),
    )

    add_fieldsets = (
        (None, {
            "classes": ("wide",),
            "fields": ("email", "password1", "password2", "is_active", "is_staff"),
        }),
    )

    @admin.display(description="Plan", ordering="profile__plan_type")
    def plan_badge(self, obj):
        try:
            profile = obj.profile
            if profile.is_pro_active:
                return format_html(
                    '<span style="background:#06b6d4;color:#fff;padding:2px 8px;border-radius:4px;font-size:11px;font-weight:600;">⚡ PRO</span>'
                )
            return format_html(
                '<span style="background:#374151;color:#9ca3af;padding:2px 8px;border-radius:4px;font-size:11px;">Free</span>'
            )
        except Profile.DoesNotExist:
            return format_html(
                '<span style="background:#7f1d1d;color:#fca5a5;padding:2px 8px;border-radius:4px;font-size:11px;">No Profile</span>'
            )

    @admin.display(description="Active", boolean=True)
    def is_active_badge(self, obj):
        return obj.is_active

    @admin.display(description="Last Seen")
    def last_seen(self, obj):
        try:
            seen = obj.profile.last_seen_at
            if seen:
                from django.utils.timesince import timesince
                return f"{timesince(seen)} ago"
            return "Never"
        except Profile.DoesNotExist:
            return "—"

    @admin.action(description="✅ Activate selected users")
    def activate_users(self, request, queryset):
        count = queryset.update(is_active=True)
        self.message_user(request, f"{count} user(s) activated.")

    @admin.action(description="❌ Deactivate selected users")
    def deactivate_users(self, request, queryset):
        count = queryset.update(is_active=False)
        self.message_user(request, f"{count} user(s) deactivated.")

    @admin.action(description="⚡ Grant Pro to selected users")
    def grant_pro(self, request, queryset):
        count = 0
        for user in queryset:
            Profile.objects.filter(user=user).update(plan_type="pro", is_pro_active=True)
            count += 1
        self.message_user(request, f"Pro granted to {count} user(s).")

    @admin.action(description="🔒 Revoke Pro from selected users")
    def revoke_pro(self, request, queryset):
        count = 0
        for user in queryset:
            Profile.objects.filter(user=user).update(plan_type="free", is_pro_active=False)
            count += 1
        self.message_user(request, f"Pro revoked from {count} user(s).")


@admin.register(EmailVerificationToken)
class EmailVerificationTokenAdmin(ModelAdmin):
    list_display = ("user", "token_short", "expires_at", "used_at", "is_valid_display", "created_at")
    list_filter = ("used_at",)
    search_fields = ("user__email", "token")
    readonly_fields = ("created_at",)
    list_per_page = 25

    def token_short(self, obj):
        return obj.token[:12] + "…"
    token_short.short_description = "Token"

    def is_valid_display(self, obj):
        return obj.is_valid
    is_valid_display.boolean = True
    is_valid_display.short_description = "Valid?"
