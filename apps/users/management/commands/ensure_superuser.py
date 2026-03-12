"""Auto-create superuser if one doesn't exist (for Railway deployment)."""
from django.core.management.base import BaseCommand
from apps.users.models import CustomUser
from apps.plans.models import Profile


class Command(BaseCommand):
    help = "Create a default superuser if none exists"

    def handle(self, *args, **options):
        email = "admin@auto-flow.studio"
        if CustomUser.objects.filter(is_superuser=True).exists():
            self.stdout.write(self.style.WARNING("Superuser already exists, skipping."))
            return

        user = CustomUser.objects.create_superuser(
            email=email,
            password="AutoFlow2026!",
        )
        Profile.objects.get_or_create(user=user)
        self.stdout.write(self.style.SUCCESS(f"Superuser created: {email}"))
        self.stdout.write(self.style.WARNING("⚠️  Change the password via /admin/ immediately!"))
