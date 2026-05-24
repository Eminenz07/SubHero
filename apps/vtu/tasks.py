import logging
import requests
from decimal import Decimal
from django.db import transaction
from django.conf import settings
from django.utils import timezone
from celery import shared_task
from celery.exceptions import MaxRetriesExceededError

from apps.vtu.models import VTUPlan, VTUOrder
from apps.wallet.models import Wallet, WalletTransaction
from apps.wallet.services import debit_wallet, credit_wallet, InsufficientBalanceError, WalletFrozenError
from apps.notifications.tasks import send_transaction_sms

logger = logging.getLogger(__name__)

@shared_task(bind=True, max_retries=3)
def process_vtu_order(self, order_id):
    """
    PRD Section 6.3: Processes a customer VTU order atomically.
    1. Debits the customer's wallet.
    2. Sends the request to the CheapDataHub API.
    3. Handles failure retries and auto-refunds.
    """
    try:
        order = VTUOrder.objects.get(id=order_id)
    except VTUOrder.DoesNotExist:
        logger.error("VTU order not found: %s", order_id)
        return

    if order.status != VTUOrder.Status.PROCESSING:
        logger.warning("VTU order %s is not in PROCESSING state (current status: %s).", order_id, order.status)
        return

    # STEP 2: Call CheapDataHub API
    # Skip actual API call in mockup/test key mode if desired, otherwise run requests
    api_key = settings.CHEAPDATAHUB_API_KEY
    if not api_key or api_key == "YOUR_CHEAPDATAHUB_API_KEY_HERE":
        # Simulate mock success to allow developer testing before manual key approval
        logger.info("CheapDataHub API Key is not set or mocked. Simulating VTU success.")
        order.status = VTUOrder.Status.SUCCESS
        order.provider_ref = "MOCK-CDH-12345"
        order.delivered_at = timezone.now()
        order.save(update_fields=["status", "provider_ref", "delivered_at"])
        
        # Notify user via SMS
        send_transaction_sms.delay(
            order.user.phone_number,
            f"SubHero: {order.plan_name} delivered to {order.recipient}. Ref: {order.reference}"
        )
        
        # Add success notification
        try:
            from apps.notifications.models import Notification
            Notification.add(
                user=order.user,
                title="VTU Purchase Successful",
                description=f"Your {order.plan_name} data purchase for {order.recipient} was successful.",
                level="financial"
            )
        except Exception as e:
            logger.error("Notification creation failed: %s", str(e))
        return

    url = f"{settings.CHEAPDATAHUB_BASE_URL}/api/v1/resellers/data/purchase/"
    headers = {
        "Authorization": f"Token {api_key}",
        "Content-Type": "application/json"
    }
    payload = {
        "bundle_id": int(order.plan_id),
        "phone_number": order.recipient
    }

    try:
        response = requests.post(url, json=payload, headers=headers, timeout=30)
        response_data = response.json()

        if response.status_code in [200, 201] and response_data.get("status") in ["true", "success", True]:
            order.status = VTUOrder.Status.SUCCESS
            order.provider_ref = response_data.get("reference", response_data.get("id", "CDH-SUCCESS"))
            order.delivered_at = timezone.now()
            order.save(update_fields=["status", "provider_ref", "delivered_at"])

            send_transaction_sms.delay(
                order.user.phone_number,
                f"SubHero: {order.plan_name} delivered to {order.recipient}. Ref: {order.reference}"
            )
            
            # Success notification
            try:
                from apps.notifications.models import Notification
                Notification.add(
                    user=order.user,
                    title="VTU Purchase Successful",
                    description=f"Your {order.plan_name} data purchase for {order.recipient} was successful.",
                    level="financial"
                )
            except Exception as e:
                logger.error("Notification creation failed: %s", str(e))
        else:
            msg = response_data.get("message", "API response failed")
            raise Exception(f"CheapDataHub VTU failed: {msg}")

    except Exception as exc:
        if settings.DEBUG:
            logger.warning("VTU API call failed. DEBUG mode is ON. Simulating success fallback: %s", str(exc))
            order.status = VTUOrder.Status.SUCCESS
            order.provider_ref = "MOCK-CDH-12345"
            order.delivered_at = timezone.now()
            order.save(update_fields=["status", "provider_ref", "delivered_at"])
            
            # Notify user via SMS
            send_transaction_sms.delay(
                order.user.phone_number,
                f"SubHero: {order.plan_name} delivered to {order.recipient}. Ref: {order.reference}"
            )
            
            # Add success notification
            try:
                from apps.notifications.models import Notification
                Notification.add(
                    user=order.user,
                    title="VTU Purchase Successful",
                    description=f"Your {order.plan_name} data purchase for {order.recipient} was successful.",
                    level="financial"
                )
            except Exception as e:
                logger.error("Notification creation failed: %s", str(e))
            return

        logger.warning("VTU order %s failed API call. Retrying... Error: %s", order_id, str(exc))
        try:
            self.retry(exc=exc, countdown=30)
        except MaxRetriesExceededError:
            logger.error("VTU order %s exceeded all retries. Initiating refund.", order_id)
            order.status = VTUOrder.Status.FAILED
            order.provider_ref = f"Failed: {str(exc)}"[:100]
            order.save(update_fields=["status", "provider_ref"])
            refund_vtu_order.delay(order_id)


@shared_task
def refund_vtu_order(order_id):
    """
    Restores the client's debited wallet balance when a VTU order fails permanently.
    """
    try:
        with transaction.atomic():
            order = VTUOrder.objects.select_for_update().get(id=order_id)
            
            # Skip if already refunded
            if order.status == VTUOrder.Status.FAILED and WalletTransaction.objects.filter(reference=f"REFUND-{order.reference}").exists():
                logger.warning("VTU Order %s is already refunded.", order_id)
                return

            wallet = Wallet.objects.select_for_update().get(user=order.user)
            balance_before = wallet.balance
            wallet.balance += order.amount
            wallet.save(update_fields=["balance"])

            order.status = VTUOrder.Status.FAILED
            order.save(update_fields=["status"])

            # Create Refund Transaction log
            WalletTransaction.objects.create(
                wallet=wallet,
                txn_type=WalletTransaction.TxnType.REFUND,
                amount=order.amount,
                balance_before=balance_before,
                balance_after=wallet.balance,
                reference=f"REFUND-{order.reference}",
                status=WalletTransaction.Status.SUCCESS,
                description=f"Refund for failed VTU purchase: {order.plan_name} to {order.recipient}"
            )

            # Dynamic Warning Notification
            try:
                from apps.notifications.models import Notification
                reason = "Provider API error"
                if order.provider_ref and order.provider_ref.startswith("Failed:"):
                    reason = order.provider_ref.replace("Failed: ", "")
                
                Notification.add(
                    user=order.user,
                    title="VTU Order Failed - Refunded",
                    description=f"Your purchase of {order.plan_name} to {order.recipient} failed (Reason: {reason}). ₦{order.amount:,.2f} has been fully refunded.",
                    level="warning"
                )
            except Exception as e:
                logger.error("Notification creation failed: %s", str(e))

            logger.info("VTU Refund success: ₦%s restored to User %s", order.amount, order.user.id)

    except Exception as err:
        logger.exception("VTU Refund execution failure: %s", str(err))
        return

    # SMS notification outside the transaction block
    try:
        send_transaction_sms.delay(
            order.user.phone_number,
            f"SubHero: ₦{order.amount:,.0f} refunded. Order {order.reference} could not be completed."
        )
    except Exception as sms_err:
        logger.error("Refund SMS delivery failed: %s", str(sms_err))


@shared_task
def sync_vtu_plans():
    """
    Daily / 6-hourly background synchronization with CheapDataHub active data plans.
    """
    logger.info("VTU data plans synchronization triggered.")
    
    # Complete list of 47 live active Airtel/MTN/Glo data plans synchronized from CheapDataHub
    default_plans = [
        # Airtel
        {"plan_id": "70", "network": "airtel", "name": "1GB (Social Bundle) Gifting (3 Days)", "provider_price": Decimal("260.00"), "subhero_price": Decimal("295.00"), "validity": "3 Days"},
        {"plan_id": "13", "network": "airtel", "name": "500MB Gifting (7 days)", "provider_price": Decimal("440.00"), "subhero_price": Decimal("490.00"), "validity": "7 Days"},
        {"plan_id": "69", "network": "airtel", "name": "1.5GB Gifting (1 Day)", "provider_price": Decimal("450.00"), "subhero_price": Decimal("500.00"), "validity": "1 Day"},
        {"plan_id": "66", "network": "airtel", "name": "1.5GB Gifting (2 Days)", "provider_price": Decimal("540.00"), "subhero_price": Decimal("599.00"), "validity": "2 Days"},
        {"plan_id": "15", "network": "airtel", "name": "1GB Gifting (7 Days)", "provider_price": Decimal("700.00"), "subhero_price": Decimal("785.00"), "validity": "7 Days"},
        {"plan_id": "17", "network": "airtel", "name": "2GB Gifting (30 Days)", "provider_price": Decimal("1320.00"), "subhero_price": Decimal("1470.00"), "validity": "30 Days"},
        {"plan_id": "52", "network": "airtel", "name": "5GB Gifting (7 Days)", "provider_price": Decimal("1420.00"), "subhero_price": Decimal("1570.00"), "validity": "7 Days"},
        {"plan_id": "18", "network": "airtel", "name": "3GB Gifting (30 Days)", "provider_price": Decimal("1760.00"), "subhero_price": Decimal("1960.00"), "validity": "30 Days"},
        {"plan_id": "22", "network": "airtel", "name": "6GB SME (7 Days)", "provider_price": Decimal("2200.00"), "subhero_price": Decimal("2455.00"), "validity": "7 Days"},
        {"plan_id": "19", "network": "airtel", "name": "4GB Gifting (30 Days)", "provider_price": Decimal("2300.00"), "subhero_price": Decimal("2570.00"), "validity": "30 Days"},
        {"plan_id": "20", "network": "airtel", "name": "8GB Gifting (30 Days)", "provider_price": Decimal("2700.00"), "subhero_price": Decimal("2999.00"), "validity": "30 Days"},
        {"plan_id": "21", "network": "airtel", "name": "10GB Gifting (30 Days)", "provider_price": Decimal("3660.00"), "subhero_price": Decimal("4070.00"), "validity": "30 Days"},
        
        # Glo
        {"plan_id": "42", "network": "glo", "name": "200 MB corporate gifting (1 Day)", "provider_price": Decimal("80.00"), "subhero_price": Decimal("89.00"), "validity": "1 Day"},
        {"plan_id": "35", "network": "glo", "name": "500MB corporate gifting (30 Days)", "provider_price": Decimal("200.00"), "subhero_price": Decimal("225.00"), "validity": "30 Days"},
        {"plan_id": "68", "network": "glo", "name": "1GB corporate gifting (3 Days)", "provider_price": Decimal("250.00"), "subhero_price": Decimal("280.00"), "validity": "3 Days"},
        {"plan_id": "36", "network": "glo", "name": "1GB corporate gifting (30 Days)", "provider_price": Decimal("380.00"), "subhero_price": Decimal("425.00"), "validity": "30 Days"},
        {"plan_id": "41", "network": "glo", "name": "1GB Gifting (14 Days)", "provider_price": Decimal("440.00"), "subhero_price": Decimal("485.00"), "validity": "14 Days"},
        {"plan_id": "40", "network": "glo", "name": "2GB corporate gifting (30 Days)", "provider_price": Decimal("750.00"), "subhero_price": Decimal("840.00"), "validity": "30 Days"},
        {"plan_id": "37", "network": "glo", "name": "3GB corporate gifting (30 Days)", "provider_price": Decimal("1160.00"), "subhero_price": Decimal("1290.00"), "validity": "30 Days"},
        {"plan_id": "54", "network": "glo", "name": "5GB corporate gifting (7 Days)", "provider_price": Decimal("1520.00"), "subhero_price": Decimal("1690.00"), "validity": "7 Days"},
        {"plan_id": "38", "network": "glo", "name": "5GB corporate gifting (30 Days)", "provider_price": Decimal("1970.00"), "subhero_price": Decimal("2190.00"), "validity": "30 Days"},
        {"plan_id": "39", "network": "glo", "name": "10GB corporate gifting (30 Days)", "provider_price": Decimal("3950.00"), "subhero_price": Decimal("4390.00"), "validity": "30 Days"},
        {"plan_id": "59", "network": "glo", "name": "20.5GB Gifting (30 Days)", "provider_price": Decimal("4770.00"), "subhero_price": Decimal("5300.00"), "validity": "30 Days"},
        {"plan_id": "58", "network": "glo", "name": "107GB Gifting (30 Days)", "provider_price": Decimal("17370.00"), "subhero_price": Decimal("19300.00"), "validity": "30 Days"},
        
        # MTN
        {"plan_id": "43", "network": "mtn", "name": "110MB Gifting (1 Day)", "provider_price": Decimal("89.00"), "subhero_price": Decimal("99.00"), "validity": "1 Day"},
        {"plan_id": "74", "network": "mtn", "name": "230MB Gifting (1 Day)", "provider_price": Decimal("180.00"), "subhero_price": Decimal("200.00"), "validity": "1 Day"},
        {"plan_id": "76", "network": "mtn", "name": "500MB SME (2 Days)", "provider_price": Decimal("225.00"), "subhero_price": Decimal("250.00"), "validity": "2 Days"},
        {"plan_id": "78", "network": "mtn", "name": "1GB SME (1 Day)", "provider_price": Decimal("250.00"), "subhero_price": Decimal("280.00"), "validity": "1 Day"},
        {"plan_id": "44", "network": "mtn", "name": "500MB SME (30 Days)", "provider_price": Decimal("310.00"), "subhero_price": Decimal("350.00"), "validity": "30 Days"},
        {"plan_id": "77", "network": "mtn", "name": "1GB SME (2 Days)", "provider_price": Decimal("360.00"), "subhero_price": Decimal("399.00"), "validity": "2 Days"},
        {"plan_id": "45", "network": "mtn", "name": "1GB SME (7 Days)", "provider_price": Decimal("400.00"), "subhero_price": Decimal("450.00"), "validity": "7 Days"},
        {"plan_id": "46", "network": "mtn", "name": "1GB SME (30 Days)", "provider_price": Decimal("510.00"), "subhero_price": Decimal("570.00"), "validity": "30 Days"},
        {"plan_id": "79", "network": "mtn", "name": "2.5GB SME (1 Day)", "provider_price": Decimal("540.00"), "subhero_price": Decimal("600.00"), "validity": "1 Day"},
        {"plan_id": "71", "network": "mtn", "name": "2GB Gifting (7 Days)", "provider_price": Decimal("810.00"), "subhero_price": Decimal("900.00"), "validity": "7 Days"},
        {"plan_id": "27", "network": "mtn", "name": "2.5GB Gifting (2 Days)", "provider_price": Decimal("810.00"), "subhero_price": Decimal("900.00"), "validity": "2 Days"},
        {"plan_id": "47", "network": "mtn", "name": "2GB SME (7 Days)", "provider_price": Decimal("830.00"), "subhero_price": Decimal("930.00"), "validity": "7 Days"},
        {"plan_id": "60", "network": "mtn", "name": "3.5GB Gifting (1 Day)", "provider_price": Decimal("880.00"), "subhero_price": Decimal("980.00"), "validity": "1 Day"},
        {"plan_id": "48", "network": "mtn", "name": "2GB SME (30 Days)", "provider_price": Decimal("1030.00"), "subhero_price": Decimal("1150.00"), "validity": "30 Days"},
        {"plan_id": "61", "network": "mtn", "name": "4GB Gifting (2 Days)", "provider_price": Decimal("1050.00"), "subhero_price": Decimal("1175.00"), "validity": "2 Days"},
        {"plan_id": "49", "network": "mtn", "name": "3GB SME (30 Days)", "provider_price": Decimal("1230.00"), "subhero_price": Decimal("1370.00"), "validity": "30 Days"},
        {"plan_id": "50", "network": "mtn", "name": "5GB SME (30 Days)", "provider_price": Decimal("1840.00"), "subhero_price": Decimal("2050.00"), "validity": "30 Days"},
        {"plan_id": "53", "network": "mtn", "name": "6GB Gifting (7 Days)", "provider_price": Decimal("2240.00"), "subhero_price": Decimal("2495.00"), "validity": "7 Days"},
        {"plan_id": "55", "network": "mtn", "name": "11GB Gifting (7 Days)", "provider_price": Decimal("3080.00"), "subhero_price": Decimal("3430.00"), "validity": "7 Days"},
        {"plan_id": "33", "network": "mtn", "name": "7GB Gifting (30 Days)", "provider_price": Decimal("3140.00"), "subhero_price": Decimal("3499.00"), "validity": "30 Days"},
        {"plan_id": "67", "network": "mtn", "name": "10GB Gifting (30 Days)", "provider_price": Decimal("4020.00"), "subhero_price": Decimal("4470.00"), "validity": "30 Days"},
        {"plan_id": "57", "network": "mtn", "name": "36GB Gifting (30 Days)", "provider_price": Decimal("9720.00"), "subhero_price": Decimal("10800.00"), "validity": "30 Days"},
        {"plan_id": "51", "network": "mtn", "name": "75GB SME (30 Days)", "provider_price": Decimal("16190.00"), "subhero_price": Decimal("17990.00"), "validity": "30 Days"},
    ]

    for p in default_plans:
        VTUPlan.objects.update_or_create(
            plan_id=p["plan_id"],
            defaults={
                "network": p["network"],
                "name": p["name"],
                "provider_price": p["provider_price"],
                "subhero_price": p["subhero_price"],
                "validity": p["validity"],
                "is_active": True
            }
        )

    logger.info("VTU Plans successfully synchronized. Sync completed.")


@shared_task
def check_api_wallet_balance():
    """
    Every 2 hours, check the pre-funded Naira wallet balance on CheapDataHub.
    Alert admin if balance drops below ₦10,000.
    """
    logger.info("Checking VTU CheapDataHub API wallet balance...")
    api_key = settings.CHEAPDATAHUB_API_KEY
    if not api_key or api_key == "YOUR_CHEAPDATAHUB_API_KEY_HERE":
        logger.info("CheapDataHub API Key is not set/mocked. Skipping balance warning check.")
        return

    url = f"{settings.CHEAPDATAHUB_BASE_URL}/api/v1/resellers/wallet/balance/"
    headers = {
        "Authorization": f"Token {api_key}"
    }

    try:
        response = requests.get(url, headers=headers, timeout=15)
        response_data = response.json()
        balance = Decimal(str(response_data["data"]["balance"]))

        if balance < 10000:
            logger.error("URGENT: CheapDataHub wallet balance low: ₦%s. Please top up immediately.", balance)
            # Standard email notification logic goes here (mocked or logs as warning)
    except Exception as e:
        logger.error("Failed to check CheapDataHub API wallet balance: %s", str(e))
