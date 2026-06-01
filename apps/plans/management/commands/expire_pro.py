"""Management command to expire time-limited Pro access.

Finds users whose pro_expires_at has passed but still have is_pro_active=True,
then downgrades them to Free. Covers both review reward users and any
paid users who slipped through webhook deactivation.

Run on a cron schedule (recommended: every 6 hours):
    python manage.py expire_pro

Or with dry-run to see who would be affected:
    python manage.py expire_pro --dry-run
"""
import logging

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.plans.models import Profile, PlanType

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Downgrade users whose time-limited Pro has expired (reward + stale paid)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show who would be affected without making changes",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        now = timezone.now()

        self.stdout.write(self.style.MIGRATE_HEADING(
            f"\n{'[DRY RUN] ' if dry_run else ''}Checking expired Pro users — {now.strftime('%Y-%m-%d %H:%M:%S UTC')}"
        ))

        # ── 0. Safety: Paying users who also had a reward — clear stale expiry ──
        # If a user has a Whop membership AND an expired pro_expires_at,
        # they paid after the reward. Clear the expiry so they stay Pro.
        hybrid_users = Profile.objects.filter(
            is_pro_active=True,
            whop_membership_id__isnull=False,
            pro_expires_at__isnull=False,
            pro_expires_at__lt=now,
        )
        hybrid_count = hybrid_users.count()
        if hybrid_count:
            self.stdout.write(self.style.WARNING(
                f"\n🔒 Found {hybrid_count} paying user(s) with stale reward expiry — clearing:"
            ))
            for profile in hybrid_users:
                self.stdout.write(f"  • {profile.user.email} (Whop: {profile.whop_membership_id})")
                if not dry_run:
                    profile.pro_expires_at = None
                    profile.save(update_fields=["pro_expires_at", "updated_at"])

        # ── 1. Reward-only users: pro_expires_at passed, no Whop membership ──
        expired_reward = Profile.objects.filter(
            is_pro_active=True,
            pro_expires_at__isnull=False,
            pro_expires_at__lt=now,
            whop_membership_id__isnull=True,  # NEVER touch paying users
        )

        reward_count = expired_reward.count()
        if reward_count:
            self.stdout.write(self.style.WARNING(
                f"\n⏰ Found {reward_count} expired reward user(s):"
            ))
            for profile in expired_reward:
                days_over = (now - profile.pro_expires_at).days
                self.stdout.write(
                    f"  • {profile.user.email} — expired {days_over} day(s) ago "
                    f"(was until {profile.pro_expires_at.strftime('%b %d, %Y')})"
                )

                if not dry_run:
                    profile.plan_type = PlanType.FREE
                    profile.is_pro_active = False
                    profile.save(update_fields=["plan_type", "is_pro_active", "updated_at"])
                    logger.info("Expired reward Pro: %s (was until %s)", profile.user.email, profile.pro_expires_at)
        else:
            self.stdout.write(self.style.SUCCESS("  ✓ No expired reward users found"))

        # ── 2. Stale paid users: is_pro_active but no Whop membership & no expiry ──
        # These are users marked Pro but have no Whop ID and no expiry date
        # (possibly from manual grants that were never cleaned up)
        stale_pro = Profile.objects.filter(
            is_pro_active=True,
            plan_type=PlanType.PRO,
            whop_membership_id__isnull=True,
            whop_user_id__isnull=True,
            pro_expires_at__isnull=True,
        ).exclude(user__is_staff=True)  # Don't touch admin accounts

        stale_count = stale_pro.count()
        if stale_count:
            self.stdout.write(self.style.WARNING(
                f"\n⚠️  Found {stale_count} Pro user(s) with NO Whop ID and NO expiry (possible stale grants):"
            ))
            for profile in stale_pro:
                last_seen = profile.last_seen_at.strftime('%b %d') if profile.last_seen_at else "never"
                self.stdout.write(
                    f"  • {profile.user.email} — last seen: {last_seen}, created: {profile.created_at.strftime('%b %d, %Y')}"
                )
            self.stdout.write(self.style.NOTICE(
                "  ℹ️  These users are NOT auto-downgraded — review manually in admin."
            ))
        else:
            self.stdout.write(self.style.SUCCESS("  ✓ No stale Pro users without Whop found"))

        # ── Summary ──
        if dry_run:
            self.stdout.write(self.style.NOTICE(
                f"\n[DRY RUN] Would downgrade {reward_count} expired reward user(s). No changes made."
            ))
        else:
            self.stdout.write(self.style.SUCCESS(
                f"\n✅ Done. Downgraded {reward_count} expired reward user(s). "
                f"Flagged {stale_count} stale Pro user(s) for review."
            ))
