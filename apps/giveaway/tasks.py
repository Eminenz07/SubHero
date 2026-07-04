import logging
from decimal import Decimal
from celery import shared_task
from django.db import transaction
from django.db.models import F
from django.utils.timezone import now
from apps.giveaway.models import Giveaway, GiveawayClaim, GiveawayEscrow
from apps.wallet.models import WalletTransaction
from apps.vtu.services import CheapDataHubService
from apps.notifications.services import send_notification

logger = logging.getLogger(__name__)

@shared_task
def process_giveaway_claim(claim_id):
    """
    Processes a claimed slot: purchases data/airtime, marks claim success/failure.
    Uses VTU/CheapDataHub APIs.
    """
    try:
        claim = GiveawayClaim.objects.select_related('giveaway', 'giveaway__escrow').get(id=claim_id)
    except GiveawayClaim.DoesNotExist:
        logger.error(f"GiveawayClaim {claim_id} not found.")
        return

    giveaway = claim.giveaway
    escrow = giveaway.escrow
    service = CheapDataHubService()

    try:
        if giveaway.giveaway_type == 'DATA':
            # Purchase data via VTUService or CheapDataHubService
            success, provider_ref, _ = service.buy_data(
                network=giveaway.network,
                phone=claim.phone_number,
                plan_id=giveaway.plan_id
            )
        else:
            # Purchase airtime
            success, provider_ref, _ = service.buy_airtime(
                network=giveaway.network,
                phone=claim.phone_number,
                amount=giveaway.amount_per_slot
            )
            
        if success:
            with transaction.atomic():
                # Mark claim success
                claim.status = 'SUCCESS'
                claim.provider_ref = provider_ref
                claim.save(update_fields=['status', 'provider_ref'])
                
                # Update escrow (release funds as spent)
                escrow.released_amount += giveaway.amount_per_slot
                escrow.save(update_fields=['released_amount'])
                
                # Update giveaway spent
                giveaway.total_spent += giveaway.amount_per_slot
                giveaway.save(update_fields=['total_spent'])
                
            # SMS follow up handled separately if needed, but per instructions we keep OTP/Follow ups
            # We could send an SMS here if we wanted.
            logger.info(f"Giveaway claim {claim_id} successful.")
        else:
            with transaction.atomic():
                # API failure, rollback claim slot
                claim.status = 'FAILED'
                claim.save(update_fields=['status'])
                
                # Un-claim the slot so someone else can claim it
                giveaway.claimed_slots -= 1
                giveaway.save(update_fields=['claimed_slots'])
                
            logger.error(f"Giveaway claim {claim_id} failed API purchase.")
            
    except Exception as e:
        logger.exception(f"Error processing claim {claim_id}: {str(e)}")
        with transaction.atomic():
            claim.status = 'FAILED'
            claim.save(update_fields=['status'])
            giveaway.claimed_slots -= 1
            giveaway.save(update_fields=['claimed_slots'])


@shared_task
def expire_giveaways():
    """
    Finds active giveaways that have reached expiry date, marks them EXPIRED,
    and refunds unused escrow balances.
    """
    expired_giveaways = Giveaway.objects.filter(
        status='ACTIVE',
        expires_at__lt=now()
    )
    
    for giveaway in expired_giveaways:
        refund_giveaway_unused_slots.delay(giveaway.id)

    # Also close giveaways that are fully claimed
    completed_giveaways = Giveaway.objects.filter(
        status='ACTIVE',
        claimed_slots__gte=F('total_slots')
    )
    for giveaway in completed_giveaways:
        giveaway.status = 'COMPLETED'
        giveaway.save(update_fields=['status'])


@shared_task
def refund_giveaway_unused_slots(giveaway_id):
    """
    Refunds the remaining balance from the giveaway escrow back to the host's wallet.
    """
    with transaction.atomic():
        try:
            giveaway = Giveaway.objects.select_for_update().get(id=giveaway_id, status='ACTIVE')
        except Giveaway.DoesNotExist:
            return

        giveaway.status = 'EXPIRED'
        giveaway.save(update_fields=['status'])

        escrow = GiveawayEscrow.objects.select_for_update().get(giveaway=giveaway)
        wallet = escrow.wallet
        
        # Calculate unused amount
        # Note: claimed_slots might be pending, we only refund what's truly unspent 
        # minus whatever might still be processing.
        # A safer approach: unused = total_locked - (claimed_slots * amount_per_slot)
        # But if some claims failed, claimed_slots is decremented.
        # So we just refund (total_slots - claimed_slots) * amount_per_slot
        unused_amount = (giveaway.total_slots - giveaway.claimed_slots) * giveaway.amount_per_slot
        
        if unused_amount > 0:
            # Credit wallet
            balance_before = wallet.balance
            wallet.balance += unused_amount
            wallet.save(update_fields=['balance'])
            
            # Record transaction
            WalletTransaction.objects.create(
                wallet=wallet,
                txn_type=WalletTransaction.TxnType.REFUND,
                amount=unused_amount,
                balance_before=balance_before,
                balance_after=wallet.balance,
                status=WalletTransaction.Status.SUCCESS,
                reference=f"REFUND_GWY_{giveaway.slug}",
                description=f"Refund for unused giveaway slots: {giveaway.title}"
            )
            
            # Notify Host (via SMTP Email preferably, per instructions)
            send_notification(
                user=giveaway.host,
                title="Giveaway Expired",
                message=f"Your giveaway '{giveaway.title}' has expired. ₦{unused_amount} has been refunded to your wallet."
            )
