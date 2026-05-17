"""Send the YouTube video blast via Resend Marketing Broadcast API.

This avoids spam folders by:
1. Using plain-text formatting (no heavy HTML/images).
2. Using Resend's Broadcast API which automatically handles unsubscribes.
3. Keeping the message simple and personal.

Usage:
    python manage.py send_youtube_broadcast --dry-run
    python manage.py send_youtube_broadcast
"""
import logging
import time

from django.conf import settings
from django.core.management.base import BaseCommand

from apps.users.models import CustomUser

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Send a plain-text YouTube video broadcast to all active users via Resend Marketing API."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Preview contacts and audience creation without sending.",
        )

    def handle(self, *args, **options):
        import resend

        dry_run = options["dry_run"]
        api_key = getattr(settings, "RESEND_API_KEY", "")
        if not api_key:
            self.stderr.write(self.style.ERROR("RESEND_API_KEY not configured!"))
            return

        resend.api_key = api_key
        from_email = getattr(settings, "DEFAULT_FROM_EMAIL", "AutoFlow <noreply@auto-flow.studio>")

        recipients = list(CustomUser.objects.filter(is_active=True).values_list("email", flat=True))
        total = len(recipients)
        self.stdout.write(f"Found {total} active users for the broadcast.")

        if dry_run:
            self.stdout.write(self.style.WARNING("Dry run -- exiting before API calls."))
            return

        # 1. Find or create Audience
        audience_name = "AutoFlow Users"
        self.stdout.write(f"Fetching Audiences to find '{audience_name}'...")
        
        try:
            audiences = resend.Audiences.list()
            # The python SDK returns an object, usually accessible via dict or dot notation.
            # E.g. audiences['data'] or audiences.data
            data = audiences.get("data", []) if isinstance(audiences, dict) else getattr(audiences, "data", [])
            
            target_audience = next((a for a in data if (a.get("name") if isinstance(a, dict) else a.name) == audience_name), None)
            
            if target_audience:
                aud_id = target_audience.get("id") if isinstance(target_audience, dict) else target_audience.id
                self.stdout.write(f"Found existing audience: {aud_id}")
            else:
                self.stdout.write("Creating new audience...")
                new_aud = resend.Audiences.create({"name": audience_name})
                aud_id = new_aud.get("id") if isinstance(new_aud, dict) else new_aud.id
                self.stdout.write(f"Created audience: {aud_id}")
        except Exception as e:
            self.stderr.write(self.style.ERROR(f"Failed to fetch/create audience: {e}"))
            return

        # 2. Add Contacts to Audience
        self.stdout.write("Syncing contacts to audience (this may take a minute)...")
        synced = 0
        for email in recipients:
            try:
                resend.Contacts.create({
                    "audience_id": aud_id,
                    "email": email,
                    "unsubscribed": False
                })
                synced += 1
                if synced % 20 == 0:
                    self.stdout.write(f"  Synced {synced}/{total}...")
                time.sleep(0.1) # Small delay to avoid aggressive rate limits on contact creation
            except Exception as e:
                # Often it errors if the contact already exists. We can ignore or log.
                pass
                
        self.stdout.write(self.style.SUCCESS(f"Finished syncing contacts. Total synced/existing: {total}"))

        # 3. Create and Send Broadcast
        subject = "did you see this workflow?"
        text_body = """Hey,

I recorded a quick video today showing the exact background workflow we use to generate AI videos hands-free.

I thought you'd find it useful since you're already using the extension. It basically runs the prompts for you on autopilot.

Here is the YouTube link:
https://www.youtube.com/watch?v=nVhWOscBCgM

Let me know what you think!
- AutoFlow
"""

        self.stdout.write("Sending Broadcast campaign...")
        try:
            broadcast = resend.Broadcasts.send({
                "audience_id": aud_id,
                "from": from_email,
                "subject": subject,
                "text": text_body,
                "name": "YouTube Demo Blast"
            })
            b_id = broadcast.get("id") if isinstance(broadcast, dict) else broadcast.id
            self.stdout.write(self.style.SUCCESS(f"Broadcast sent successfully! ID: {b_id}"))
            self.stdout.write(self.style.SUCCESS("Check your Resend Dashboard under 'Marketing' to track opens/clicks."))
        except Exception as e:
            self.stderr.write(self.style.ERROR(f"Failed to send broadcast: {e}"))
            self.stderr.write(self.style.WARNING("Note: If you get a Quota Exceeded error, you must wait 24 hours for your free limit to reset, or upgrade your plan."))

