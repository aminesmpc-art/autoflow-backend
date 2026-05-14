"""Admin config for reward credits — with premium status badges."""
from django.contrib import admin
from django.utils.html import format_html
from unfold.admin import ModelAdmin
from unfold.decorators import action

from .models import RewardCreditLedger, ReviewRewardClaim


@admin.register(RewardCreditLedger)
class RewardCreditLedgerAdmin(ModelAdmin):
    list_display = (
        "user_display", "amount_badge", "source_display",
        "status_badge", "reference_display", "created_display",
    )
    list_filter = ("source", "status")
    search_fields = ("user__email", "reference_id")
    readonly_fields = ("created_at",)
    date_hierarchy = "created_at"
    list_per_page = 50

    @admin.display(description="User", ordering="user__email")
    def user_display(self, obj):
        return format_html(
            '<span style="color:#34d399;font-weight:500;">{}</span>',
            obj.user.email,
        )

    @admin.display(description="Amount")
    def amount_badge(self, obj):
        if obj.amount > 0:
            return format_html(
                '<span style="background:#064e3b;color:#6ee7b7;padding:3px 10px;'
                'border-radius:6px;font-size:12px;font-weight:700;'
                'font-variant-numeric:tabular-nums;">+{}</span>',
                obj.amount,
            )
        return format_html(
            '<span style="background:#7f1d1d;color:#fca5a5;padding:3px 10px;'
            'border-radius:6px;font-size:12px;font-weight:700;'
            'font-variant-numeric:tabular-nums;">{}</span>',
            obj.amount,
        )

    @admin.display(description="Source")
    def source_display(self, obj):
        icons = {
            "rewarded_ad": ("🎬", "#f59e0b"),
            "manual_grant": ("🎁", "#10b981"),
            "prompt_consumption": ("📝", "#3b82f6"),
            "referral": ("🔗", "#8b5cf6"),
        }
        icon, color = icons.get(obj.source, ("•", "#6b7280"))
        label = obj.source.replace("_", " ").title()
        return format_html(
            '<span style="color:{};font-size:12px;font-weight:500;">{} {}</span>',
            color, icon, label,
        )

    @admin.display(description="Status")
    def status_badge(self, obj):
        styles = {
            "completed": ("#064e3b", "#6ee7b7", "✓ Completed"),
            "pending": ("#422006", "#fbbf24", "⏳ Pending"),
            "reversed": ("#7f1d1d", "#fca5a5", "↩ Reversed"),
        }
        bg, fg, label = styles.get(obj.status, ("#1f2937", "#9ca3af", obj.status.title()))
        return format_html(
            '<span style="background:{};color:{};padding:3px 8px;border-radius:6px;'
            'font-size:11px;font-weight:600;">{}</span>',
            bg, fg, label,
        )

    @admin.display(description="Reference")
    def reference_display(self, obj):
        if obj.reference_id:
            short = obj.reference_id[:16] + "…" if len(obj.reference_id) > 16 else obj.reference_id
            return format_html(
                '<code style="font-size:11px;background:#1e293b;color:#94a3b8;'
                'padding:3px 8px;border-radius:4px;">{}</code>',
                short,
            )
        return format_html('<span style="color:#4b5563;">—</span>')

    @admin.display(description="Created", ordering="created_at")
    def created_display(self, obj):
        return format_html(
            '<span style="color:#6b7280;font-size:12px;">{}</span>',
            obj.created_at.strftime("%b %d, %Y %H:%M"),
        )


@admin.register(ReviewRewardClaim)
class ReviewRewardClaimAdmin(ModelAdmin):
    list_display = (
        "user_display", "reviewer_name_display", "status_badge", "claimed_display", 
        "reviewed_display", "expires_display"
    )
    list_filter = ("status",)
    search_fields = ("user__email", "reviewer_name")
    readonly_fields = ("claimed_at", "reviewed_at", "pro_granted_until")
    date_hierarchy = "claimed_at"
    list_per_page = 50
    actions = ["approve_claims", "reject_claims"]

    def save_model(self, request, obj, form, change):
        from django.utils import timezone
        from datetime import timedelta
        from apps.plans.models import PlanType

        # If status is being changed to approved manually in the form
        if change and "status" in form.changed_data:
            if obj.status == "approved" and not obj.pro_granted_until:
                now = timezone.now()
                thirty_days = now + timedelta(days=30)
                
                obj.reviewed_at = now
                obj.pro_granted_until = thirty_days
                
                profile = obj.user.profile
                profile.plan_type = PlanType.PRO
                profile.is_pro_active = True
                profile.pro_expires_at = thirty_days
                profile.save()
                
                self.message_user(request, f"Pro granted automatically! {obj.user.email} given 30 days.")
            
            elif obj.status == "rejected":
                obj.reviewed_at = timezone.now()

        super().save_model(request, obj, form, change)

    @admin.display(description="User", ordering="user__email")
    def user_display(self, obj):
        return format_html(
            '<span style="color:#34d399;font-weight:500;">{}</span>',
            obj.user.email,
        )

    @admin.display(description="Chrome Name", ordering="reviewer_name")
    def reviewer_name_display(self, obj):
        if obj.reviewer_name:
            return format_html(
                '<span style="color:#60a5fa;font-weight:600;">{}</span>',
                obj.reviewer_name,
            )
        return format_html('<span style="color:#6b7280;font-style:italic;">—</span>')

    @admin.display(description="Status")
    def status_badge(self, obj):
        styles = {
            "pending": ("#422006", "#fbbf24", "⏳ Pending"),
            "approved": ("#064e3b", "#6ee7b7", "✓ Approved"),
            "rejected": ("#7f1d1d", "#fca5a5", "❌ Rejected"),
        }
        bg, fg, label = styles.get(obj.status, ("#1f2937", "#9ca3af", obj.status.title()))
        return format_html(
            '<span style="background:{};color:{};padding:3px 8px;border-radius:6px;'
            'font-size:11px;font-weight:600;">{}</span>',
            bg, fg, label,
        )

    @admin.display(description="Claimed", ordering="claimed_at")
    def claimed_display(self, obj):
        return format_html(
            '<span style="color:#6b7280;font-size:12px;">{}</span>',
            obj.claimed_at.strftime("%b %d, %Y"),
        )

    @admin.display(description="Reviewed", ordering="reviewed_at")
    def reviewed_display(self, obj):
        if not obj.reviewed_at:
            return format_html('<span style="color:#4b5563;">—</span>')
        return format_html(
            '<span style="color:#9ca3af;font-size:12px;">{}</span>',
            obj.reviewed_at.strftime("%b %d, %Y"),
        )

    @admin.display(description="Pro Expires", ordering="pro_granted_until")
    def expires_display(self, obj):
        if not obj.pro_granted_until:
            return format_html('<span style="color:#4b5563;">—</span>')
        return format_html(
            '<span style="color:#8b5cf6;font-size:12px;font-weight:500;">{}</span>',
            obj.pro_granted_until.strftime("%b %d, %Y"),
        )

    # ── Row Actions ──
    actions_row = ("approve_claim_row", "reject_claim_row")

    @action(description="✅ Approve", url_path="approve-claim")
    def approve_claim_row(self, request, object_id):
        from django.shortcuts import redirect
        from django.urls import reverse
        from django.utils import timezone
        from datetime import timedelta
        from apps.plans.models import PlanType
        
        claim = self.get_object(request, object_id)
        if claim and claim.status == "pending":
            now = timezone.now()
            thirty_days = now + timedelta(days=30)
            
            claim.status = "approved"
            claim.reviewed_at = now
            claim.pro_granted_until = thirty_days
            claim.save()
            
            profile = claim.user.profile
            profile.plan_type = PlanType.PRO
            profile.is_pro_active = True
            profile.pro_expires_at = thirty_days
            profile.save()
            
            self.message_user(request, f"Claim approved! {claim.user.email} granted 30 days of Pro.")
        
        return redirect(request.META.get('HTTP_REFERER', reverse('admin:rewards_reviewrewardclaim_changelist')))

    @action(description="❌ Reject", url_path="reject-claim")
    def reject_claim_row(self, request, object_id):
        from django.shortcuts import redirect
        from django.urls import reverse
        from django.utils import timezone
        
        claim = self.get_object(request, object_id)
        if claim and claim.status == "pending":
            claim.status = "rejected"
            claim.reviewed_at = timezone.now()
            claim.save()
            
            self.message_user(request, f"Claim for {claim.user.email} rejected.", level="warning")
            
        return redirect(request.META.get('HTTP_REFERER', reverse('admin:rewards_reviewrewardclaim_changelist')))

    # ── Bulk Actions ──
    @admin.action(description="✅ Approve selected claims (Grants 30 Days Pro)")
    def approve_claims(self, request, queryset):
        from django.utils import timezone
        from datetime import timedelta
        from apps.plans.models import PlanType

        now = timezone.now()
        thirty_days = now + timedelta(days=30)
        
        approved_count = 0
        for claim in queryset.filter(status="pending"):
            # Update claim
            claim.status = "approved"
            claim.reviewed_at = now
            claim.pro_granted_until = thirty_days
            claim.save()
            
            # Update user profile to Pro with expiry
            profile = claim.user.profile
            profile.plan_type = PlanType.PRO
            profile.is_pro_active = True
            profile.pro_expires_at = thirty_days
            profile.save()
            
            approved_count += 1
            
        self.message_user(request, f"{approved_count} claim(s) approved. Users granted 30 days of Pro.")

    @admin.action(description="❌ Reject selected claims")
    def reject_claims(self, request, queryset):
        from django.utils import timezone
        
        now = timezone.now()
        count = queryset.filter(status="pending").update(
            status="rejected", 
            reviewed_at=now
        )
        self.message_user(request, f"{count} claim(s) rejected.", level="warning")
