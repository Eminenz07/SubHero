"""
Accounts — Signals
===================
Post-registration actions: wallet creation, referral code.
"""

import logging

from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver

logger = logging.getLogger(__name__)


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_wallet_on_registration(sender, instance, created, **kwargs):
    """
    PRD Section 6.1.1: A wallet is auto-created on registration completion.
    Only creates if the wallet app models are available (Phase 2+).
    """
    if created:
        try:
            from apps.wallet.models import Wallet

            Wallet.objects.get_or_create(user=instance)
            logger.info("Wallet created for user %s", instance.id)
        except Exception:
            # Wallet app may not be fully configured in Phase 1
            logger.debug("Wallet creation skipped (wallet app not ready)")
