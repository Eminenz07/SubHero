"""
Management Command: create_missing_wallets
=============================================
Backfills wallets for existing verified users who don't have one.
Useful after deploying Phase 2 with existing Phase 1 users in the DB.
"""

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from apps.wallet.services import create_wallet

User = get_user_model()


class Command(BaseCommand):
    help = "Create wallets (with virtual accounts) for verified users who don't have one."

    def handle(self, *args, **options):
        users_without_wallet = User.objects.filter(
            is_verified=True,
            wallet__isnull=True,
        )

        count = users_without_wallet.count()
        if count == 0:
            self.stdout.write(self.style.SUCCESS("All verified users already have wallets."))
            return

        self.stdout.write(f"Found {count} verified user(s) without wallets. Creating...")

        created = 0
        failed = 0
        for user in users_without_wallet:
            try:
                create_wallet(user)
                created += 1
                self.stdout.write(f"  ✓ Created wallet for {user.phone_number}")
            except Exception as e:
                failed += 1
                self.stderr.write(f"  ✗ Failed for {user.phone_number}: {str(e)}")

        self.stdout.write(
            self.style.SUCCESS(f"\nDone. Created: {created}, Failed: {failed}")
        )
