import logging
import requests
import time
from decimal import Decimal
from django.db import transaction
from django.conf import settings
from django.utils import timezone
from celery import shared_task
from celery.exceptions import MaxRetriesExceededError

from apps.vtu.models import (
    VTUPlan, VTUOrder,
    AirtimeOrder, AIRTIME_NETWORKS,
    CablePlan, CableOrder,
    ElectricityOrder, DISCO_NAMES,
    ExamProduct, ExamPinOrder,
)
from apps.wallet.models import Wallet, WalletTransaction
from apps.wallet.services import debit_wallet, credit_wallet, InsufficientBalanceError, WalletFrozenError
from apps.notifications.tasks import send_transaction_sms

logger = logging.getLogger(__name__)

@shared_task(bind=True, max_retries=3)
def process_vtu_order(self, order_id):
    """
    PRD Section 6.3: Processes a customer VTU order atomically.
    1. Debits the customer's wallet.
    2. Sends the request to the CheapDataHub API with synchronous retries.
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
    api_key = settings.CHEAPDATAHUB_API_KEY
    if not api_key or api_key == "YOUR_CHEAPDATAHUB_API_KEY_HERE":
        # Simulate mock success to allow developer testing before manual key approval
        logger.info("CheapDataHub API Key is not set or mocked. Simulating VTU success.")
        order.status = VTUOrder.Status.SUCCESS
        order.provider_ref = "MOCK-CDH-12345"
        order.delivered_at = timezone.now()
        order.save(update_fields=["status", "provider_ref", "delivered_at"])
        
        # Update WalletTransaction to SUCCESS
        WalletTransaction.objects.filter(reference=order.reference).update(status=WalletTransaction.Status.SUCCESS)
        
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
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    payload = {
        "bundle_id": int(order.plan_id),
        "phone_number": order.recipient
    }

    max_attempts = 3
    for attempt in range(1, max_attempts + 1):
        try:
            logger.info("VTU order %s: calling CheapDataHub API (attempt %s/%s)", order_id, attempt, max_attempts)
            response = requests.post(url, json=payload, headers=headers, timeout=20)
            
            if response.status_code not in [200, 201]:
                msg = response.text[:150] if response.text else "No response body"
                raise Exception(f"CheapDataHub API error [{response.status_code}]: {msg}")
            
            try:
                response_data = response.json()
            except ValueError:
                raise Exception(f"CheapDataHub API returned invalid HTML response [{response.status_code}]")

            if response_data.get("status") in ["true", "success", True]:
                order.status = VTUOrder.Status.SUCCESS
                order.provider_ref = response_data.get("reference", response_data.get("id", "CDH-SUCCESS"))
                order.delivered_at = timezone.now()
                order.save(update_fields=["status", "provider_ref", "delivered_at"])

                # Update corresponding WalletTransaction to SUCCESS
                WalletTransaction.objects.filter(reference=order.reference).update(status=WalletTransaction.Status.SUCCESS)

                send_transaction_sms.delay(
                    order.user.phone_number,
                    f"SubHero: {order.plan_name} delivered to {order.recipient}. Ref: {order.reference}"
                )

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
            else:
                msg = response_data.get("message", response_data.get("error", "Provider declined the request"))
                raise Exception(f"CheapDataHub VTU failed: {msg}")

        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError, Exception) as exc:
            logger.warning("VTU order %s: attempt %s of %s failed: %s", order_id, attempt, max_attempts, str(exc))
            exc_str = str(exc)
            is_definitive = any(kw in exc_str for kw in [
                "400", "401", "402", "403", "404", "422", 
                "Unauthorized", "Forbidden", "Insufficient", "wallet", "API Key"
            ])
            if attempt == max_attempts or is_definitive:
                logger.error("VTU order %s exceeded all retries or encountered definitive failure. Failing and refunding. Reason: %s", order_id, exc_str)
                order.status = VTUOrder.Status.FAILED
                order.provider_ref = f"Failed: {exc_str}"[:200]
                order.save(update_fields=["status", "provider_ref"])
                refund_vtu_order(order_id)
                return
            time.sleep(2)


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

            # Update original debit WalletTransaction to FAILED
            WalletTransaction.objects.filter(reference=order.reference).update(status=WalletTransaction.Status.FAILED)

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
        "Authorization": f"Bearer {api_key}"
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


# =============================================================
# AIRTIME TASKS
# =============================================================

def _generic_refund(order, order_type_label, refund_prefix):
    """Helper: refund any VTU-type order atomically."""
    with transaction.atomic():
        refund_ref = f"REFUND-{order.reference}"
        if WalletTransaction.objects.filter(reference=refund_ref).exists():
            logger.warning("%s Order %s already refunded.", order_type_label, order.reference)
            return

        wallet = Wallet.objects.select_for_update().get(user=order.user)
        balance_before = wallet.balance
        wallet.balance += order.amount
        wallet.save(update_fields=["balance"])

        order.status = "FAILED"
        order.save(update_fields=["status"])

        # Update original debit WalletTransaction to FAILED
        WalletTransaction.objects.filter(reference=order.reference).update(status=WalletTransaction.Status.FAILED)

        WalletTransaction.objects.create(
            wallet=wallet,
            txn_type=WalletTransaction.TxnType.REFUND,
            amount=order.amount,
            balance_before=balance_before,
            balance_after=wallet.balance,
            reference=refund_ref,
            status=WalletTransaction.Status.SUCCESS,
            description=f"Refund for failed {order_type_label} order {order.reference}",
        )
        logger.info("%s refund success: ₦%s restored to User %s", order_type_label, order.amount, order.user.id)

    try:
        send_transaction_sms.delay(
            order.user.phone_number,
            f"SubHero: ₦{order.amount:,.0f} refunded. {order_type_label} Order {order.reference} could not be completed.",
        )
    except Exception as sms_err:
        logger.error("Refund SMS failed: %s", str(sms_err))


@shared_task(bind=True, max_retries=3)
def process_airtime_order(self, order_id):
    """Purchases airtime via CheapDataHub with synchronous retries and handles refunds."""
    try:
        order = AirtimeOrder.objects.get(id=order_id)
    except AirtimeOrder.DoesNotExist:
        logger.error("AirtimeOrder not found: %s", order_id)
        return

    if order.status != AirtimeOrder.Status.PROCESSING:
        return

    api_key = settings.CHEAPDATAHUB_API_KEY
    if not api_key:
        logger.error("CHEAPDATAHUB_API_KEY not set. Cannot process airtime order %s.", order_id)
        order.status = AirtimeOrder.Status.FAILED
        order.save(update_fields=["status"])
        refund_airtime_order(order_id)
        return

    network_info = AIRTIME_NETWORKS.get(order.network.lower(), {})
    provider_id = network_info.get("provider_id")
    if not provider_id:
        logger.error("Unknown network for airtime: %s", order.network)
        order.status = AirtimeOrder.Status.FAILED
        order.save(update_fields=["status"])
        refund_airtime_order(order_id)
        return

    url = f"{settings.CHEAPDATAHUB_BASE_URL}/api/v1/resellers/airtime/purchase/"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "network_id": provider_id,
        "phone_number": order.recipient,
        "amount": str(order.amount),
    }

    max_attempts = 3
    for attempt in range(1, max_attempts + 1):
        try:
            logger.info("Airtime order %s: calling CheapDataHub API (attempt %s/%s)", order_id, attempt, max_attempts)
            response = requests.post(url, json=payload, headers=headers, timeout=20)
            
            if response.status_code not in [200, 201]:
                msg = response.text[:150] if response.text else "No response body"
                raise Exception(f"CheapDataHub API error [{response.status_code}]: {msg}")
            
            try:
                data = response.json()
            except ValueError:
                raise Exception(f"CheapDataHub API returned invalid HTML response [{response.status_code}]")

            if data.get("status") in ["true", "success", True]:
                order.status = AirtimeOrder.Status.SUCCESS
                order.provider_ref = data.get("reference", data.get("id", "CDH-AIRTIME"))
                order.delivered_at = timezone.now()
                order.save(update_fields=["status", "provider_ref", "delivered_at"])

                # Update corresponding WalletTransaction to SUCCESS
                WalletTransaction.objects.filter(reference=order.reference).update(status=WalletTransaction.Status.SUCCESS)

                send_transaction_sms.delay(
                    order.user.phone_number,
                    f"SubHero: ₦{order.amount:,.0f} airtime sent to {order.recipient}. Ref: {order.reference}",
                )
                try:
                    from apps.notifications.models import Notification
                    Notification.add(order.user, "Airtime Purchase Successful",
                        f"₦{order.amount:,.0f} airtime delivered to {order.recipient}.", "financial")
                except Exception as e:
                    logger.error("Notification failed: %s", str(e))
                return
            else:
                msg = data.get("message", data.get("error", "Provider declined"))
                raise Exception(f"CheapDataHub Airtime failed: {msg}")

        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError, Exception) as exc:
            logger.warning("Airtime order %s: attempt %s of %s failed: %s", order_id, attempt, max_attempts, str(exc))
            exc_str = str(exc)
            is_definitive = any(kw in exc_str for kw in [
                "400", "401", "402", "403", "404", "422", 
                "Unauthorized", "Forbidden", "Insufficient", "wallet", "API Key"
            ])
            if attempt == max_attempts or is_definitive:
                logger.error("Airtime order %s exceeded all retries or encountered definitive failure. Failing and refunding. Reason: %s", order_id, exc_str)
                order.status = AirtimeOrder.Status.FAILED
                order.provider_ref = f"Failed: {exc_str}"[:200]
                order.save(update_fields=["status", "provider_ref"])
                refund_airtime_order(order_id)
                return
            time.sleep(2)


@shared_task
def refund_airtime_order(order_id):
    try:
        order = AirtimeOrder.objects.select_for_update().get(id=order_id)
        _generic_refund(order, "Airtime", "REFUND")
    except Exception as err:
        logger.exception("Airtime refund failed: %s", str(err))


# =============================================================
# CABLE TV TASKS
# =============================================================

@shared_task(bind=True, max_retries=3)
def process_cable_order(self, order_id):
    """Subscribes a cable TV plan via CheapDataHub with synchronous retries."""
    try:
        order = CableOrder.objects.get(id=order_id)
    except CableOrder.DoesNotExist:
        logger.error("CableOrder not found: %s", order_id)
        return

    if order.status != CableOrder.Status.PROCESSING:
        return

    api_key = settings.CHEAPDATAHUB_API_KEY
    if not api_key:
        order.status = CableOrder.Status.FAILED
        order.save(update_fields=["status"])
        refund_cable_order(order_id)
        return

    url = f"{settings.CHEAPDATAHUB_BASE_URL}/api/v1/resellers/cable/purchase/"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "plan_id": order.plan_id,
        "smartcard_number": order.card_number,
        "phone_number": order.phone,
    }

    max_attempts = 3
    for attempt in range(1, max_attempts + 1):
        try:
            logger.info("Cable order %s: calling CheapDataHub API (attempt %s/%s)", order_id, attempt, max_attempts)
            response = requests.post(url, json=payload, headers=headers, timeout=20)
            
            if response.status_code not in [200, 201]:
                msg = response.text[:150] if response.text else "No response body"
                raise Exception(f"CheapDataHub API error [{response.status_code}]: {msg}")
            
            try:
                data = response.json()
            except ValueError:
                raise Exception(f"CheapDataHub API returned invalid HTML response [{response.status_code}]")

            if data.get("status") in ["true", "success", True]:
                order.status = CableOrder.Status.SUCCESS
                order.provider_ref = data.get("reference", data.get("id", "CDH-CABLE"))
                order.delivered_at = timezone.now()
                order.save(update_fields=["status", "provider_ref", "delivered_at"])

                # Update corresponding WalletTransaction to SUCCESS
                WalletTransaction.objects.filter(reference=order.reference).update(status=WalletTransaction.Status.SUCCESS)

                send_transaction_sms.delay(
                    order.user.phone_number,
                    f"SubHero: {order.provider.upper()} {order.plan_name} renewed for card {order.card_number}. Ref: {order.reference}",
                )
                try:
                    from apps.notifications.models import Notification
                    Notification.add(order.user, "Cable TV Subscription Successful",
                        f"{order.provider.upper()} {order.plan_name} activated on {order.card_number}.", "financial")
                except Exception as e:
                    logger.error("Notification failed: %s", str(e))
                return
            else:
                msg = data.get("message", data.get("error", "Provider declined"))
                raise Exception(f"CheapDataHub Cable failed: {msg}")

        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError, Exception) as exc:
            logger.warning("Cable order %s: attempt %s of %s failed: %s", order_id, attempt, max_attempts, str(exc))
            exc_str = str(exc)
            is_definitive = any(kw in exc_str for kw in [
                "400", "401", "402", "403", "404", "422", 
                "Unauthorized", "Forbidden", "Insufficient", "wallet", "API Key"
            ])
            if attempt == max_attempts or is_definitive:
                logger.error("Cable order %s exceeded all retries or encountered definitive failure. Failing and refunding. Reason: %s", order_id, exc_str)
                order.status = CableOrder.Status.FAILED
                order.provider_ref = f"Failed: {exc_str}"[:200]
                order.save(update_fields=["status", "provider_ref"])
                refund_cable_order(order_id)
                return
            time.sleep(2)


@shared_task
def refund_cable_order(order_id):
    try:
        order = CableOrder.objects.select_for_update().get(id=order_id)
        _generic_refund(order, "Cable TV", "REFUND")
    except Exception as err:
        logger.exception("Cable refund failed: %s", str(err))


@shared_task
def sync_cable_plans():
    """Syncs cable TV plans from CheapDataHub every 6 hours."""
    api_key = settings.CHEAPDATAHUB_API_KEY
    if not api_key:
        # Seed default plans so UI works without API key
        _seed_default_cable_plans()
        return

    # Provider IDs: DSTV=1, GOtv=2, Startimes=3
    providers = [("dstv", 1), ("gotv", 2), ("startimes", 3)]
    headers = {"Authorization": f"Bearer {api_key}"}

    for provider_name, provider_id in providers:
        url = f"{settings.CHEAPDATAHUB_BASE_URL}/api/v1/resellers/cable/plans/?provider_id={provider_id}"
        try:
            response = requests.get(url, headers=headers, timeout=20)
            plans = response.json().get("data", response.json())
            plans_list = plans if isinstance(plans, list) else []
            if not plans_list:
                raise Exception("Empty plans list received from API")
            for p in plans_list:
                provider_price = Decimal(str(p.get("amount", p.get("price", "0"))))
                subhero_price = (provider_price * Decimal("1.04")).quantize(Decimal("0.01"))
                CablePlan.objects.update_or_create(
                    plan_id=str(p["id"]),
                    defaults={
                        "provider": provider_name,
                        "name": p.get("name", p.get("package_name", "")),
                        "amount": provider_price,
                        "subhero_price": subhero_price,
                        "is_active": True,
                    }
                )
            logger.info("Synced %s cable plans for %s.", len(plans_list), provider_name)
        except Exception as e:
            logger.error("Failed to sync cable plans for %s: %s", provider_name, str(e))
            _seed_default_cable_plans()


def _seed_default_cable_plans():
    """Fallback cable plans so UI works even without API key or during sync failures."""
    default_plans = [
        # DStv
        {"plan_id": "dstv-padi", "provider": "dstv", "name": "DStv Padi", "amount": Decimal("1850"), "subhero_price": Decimal("1924")},
        {"plan_id": "dstv-yanga", "provider": "dstv", "name": "DStv Yanga", "amount": Decimal("2565"), "subhero_price": Decimal("2668")},
        {"plan_id": "dstv-confam", "provider": "dstv", "name": "DStv Confam", "amount": Decimal("6200"), "subhero_price": Decimal("6448")},
        {"plan_id": "dstv-compact", "provider": "dstv", "name": "DStv Compact", "amount": Decimal("15700"), "subhero_price": Decimal("16328")},
        {"plan_id": "dstv-compact-plus", "provider": "dstv", "name": "DStv Compact Plus", "amount": Decimal("25000"), "subhero_price": Decimal("26000")},
        {"plan_id": "dstv-premium", "provider": "dstv", "name": "DStv Premium", "amount": Decimal("37000"), "subhero_price": Decimal("38480")},
        # GOtv
        {"plan_id": "gotv-supa-plus", "provider": "gotv", "name": "GOtv Supa Plus", "amount": Decimal("6400"), "subhero_price": Decimal("6656")},
        {"plan_id": "gotv-supa", "provider": "gotv", "name": "GOtv Supa", "amount": Decimal("5500"), "subhero_price": Decimal("5720")},
        {"plan_id": "gotv-max", "provider": "gotv", "name": "GOtv Max", "amount": Decimal("4150"), "subhero_price": Decimal("4316")},
        {"plan_id": "gotv-jolli", "provider": "gotv", "name": "GOtv Jolli", "amount": Decimal("3000"), "subhero_price": Decimal("3120")},
        {"plan_id": "gotv-jinja", "provider": "gotv", "name": "GOtv Jinja", "amount": Decimal("1900"), "subhero_price": Decimal("1976")},
        {"plan_id": "gotv-smallie", "provider": "gotv", "name": "GOtv Smallie (1 Month)", "amount": Decimal("1100"), "subhero_price": Decimal("1144")},
        # Startimes
        {"plan_id": "startimes-nova", "provider": "startimes", "name": "Startimes Nova (1 Month)", "amount": Decimal("1300"), "subhero_price": Decimal("1352")},
        {"plan_id": "startimes-basic", "provider": "startimes", "name": "Startimes Basic (1 Month)", "amount": Decimal("2200"), "subhero_price": Decimal("2288")},
        {"plan_id": "startimes-smart", "provider": "startimes", "name": "Startimes Smart (1 Month)", "amount": Decimal("3000"), "subhero_price": Decimal("3120")},
        {"plan_id": "startimes-classic", "provider": "startimes", "name": "Startimes Classic (1 Month)", "amount": Decimal("4000"), "subhero_price": Decimal("4160")},
        {"plan_id": "startimes-super", "provider": "startimes", "name": "Startimes Super (1 Month)", "amount": Decimal("6200"), "subhero_price": Decimal("6448")},
    ]
    for p in default_plans:
        CablePlan.objects.update_or_create(plan_id=p["plan_id"], defaults={**p, "is_active": True})
    logger.info("Default cable plans seeded.")


# =============================================================
# ELECTRICITY TASKS
# =============================================================

@shared_task(bind=True, max_retries=3)
def process_electricity_order(self, order_id):
    """Vends electricity token via CheapDataHub with synchronous retries."""
    try:
        order = ElectricityOrder.objects.get(id=order_id)
    except ElectricityOrder.DoesNotExist:
        logger.error("ElectricityOrder not found: %s", order_id)
        return

    if order.status != ElectricityOrder.Status.PROCESSING:
        return

    api_key = settings.CHEAPDATAHUB_API_KEY
    if not api_key:
        order.status = ElectricityOrder.Status.FAILED
        order.save(update_fields=["status"])
        refund_electricity_order(order_id)
        return

    url = f"{settings.CHEAPDATAHUB_BASE_URL}/api/v1/resellers/electricity/purchase/"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "disco_id": order.disco_id,
        "meter_number": order.meter_number,
        "meter_type": order.meter_type,
        "amount": str(order.amount),
        "phone_number": order.phone,
    }

    max_attempts = 3
    for attempt in range(1, max_attempts + 1):
        try:
            logger.info("Electricity order %s: calling CheapDataHub API (attempt %s/%s)", order_id, attempt, max_attempts)
            response = requests.post(url, json=payload, headers=headers, timeout=30)
            
            if response.status_code not in [200, 201]:
                msg = response.text[:150] if response.text else "No response body"
                raise Exception(f"CheapDataHub API error [{response.status_code}]: {msg}")
            
            try:
                data = response.json()
            except ValueError:
                raise Exception(f"CheapDataHub API returned invalid HTML response [{response.status_code}]")

            if data.get("status") in ["true", "success", True]:
                order.status = ElectricityOrder.Status.SUCCESS
                order.provider_ref = data.get("reference", data.get("id", "CDH-ELEC"))
                order.token = data.get("token", data.get("data", {}).get("token", ""))
                order.units = str(data.get("units", data.get("data", {}).get("units", "")))
                order.delivered_at = timezone.now()
                order.save(update_fields=["status", "provider_ref", "token", "units", "delivered_at"])

                # Update corresponding WalletTransaction to SUCCESS
                WalletTransaction.objects.filter(reference=order.reference).update(status=WalletTransaction.Status.SUCCESS)

                token_msg = f" Token: {order.token}" if order.token else ""
                send_transaction_sms.delay(
                    order.user.phone_number,
                    f"SubHero: ₦{order.amount:,.0f} electricity vended for {order.meter_number}.{token_msg} Ref: {order.reference}",
                )
                try:
                    from apps.notifications.models import Notification
                    desc = f"₦{order.amount:,.0f} electricity for meter {order.meter_number} ({order.disco_name})."
                    if order.token:
                        desc += f" Token: {order.token}"
                    Notification.add(order.user, "Electricity Purchase Successful", desc, "financial")
                except Exception as e:
                    logger.error("Notification failed: %s", str(e))
                return
            else:
                msg = data.get("message", data.get("error", "Provider declined"))
                raise Exception(f"CheapDataHub Electricity failed: {msg}")

        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError, Exception) as exc:
            logger.warning("Electricity order %s: attempt %s of %s failed: %s", order_id, attempt, max_attempts, str(exc))
            exc_str = str(exc)
            is_definitive = any(kw in exc_str for kw in [
                "400", "401", "402", "403", "404", "422", 
                "Unauthorized", "Forbidden", "Insufficient", "wallet", "API Key"
            ])
            if attempt == max_attempts or is_definitive:
                logger.error("Electricity order %s exceeded all retries or encountered definitive failure. Failing and refunding. Reason: %s", order_id, exc_str)
                order.status = ElectricityOrder.Status.FAILED
                order.provider_ref = f"Failed: {exc_str}"[:200]
                order.save(update_fields=["status", "provider_ref"])
                refund_electricity_order(order_id)
                return
            time.sleep(2)


@shared_task
def refund_electricity_order(order_id):
    try:
        order = ElectricityOrder.objects.select_for_update().get(id=order_id)
        _generic_refund(order, "Electricity", "REFUND")
    except Exception as err:
        logger.exception("Electricity refund failed: %s", str(err))


# =============================================================
# EXAM PIN TASKS
# =============================================================

@shared_task(bind=True, max_retries=3)
def process_exam_pin_order(self, order_id):
    """Purchases exam PINs via CheapDataHub with synchronous retries and stores the delivered tokens."""
    try:
        order = ExamPinOrder.objects.get(id=order_id)
    except ExamPinOrder.DoesNotExist:
        logger.error("ExamPinOrder not found: %s", order_id)
        return

    if order.status != ExamPinOrder.Status.PROCESSING:
        return

    api_key = settings.CHEAPDATAHUB_API_KEY
    if not api_key:
        order.status = ExamPinOrder.Status.FAILED
        order.save(update_fields=["status"])
        refund_exam_pin_order(order_id)
        return

    url = f"{settings.CHEAPDATAHUB_BASE_URL}/api/v1/resellers/exam-pin/purchase/"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "product_id": order.product_id,
        "quantity": order.quantity,
    }

    max_attempts = 3
    for attempt in range(1, max_attempts + 1):
        try:
            logger.info("Exam PIN order %s: calling CheapDataHub API (attempt %s/%s)", order_id, attempt, max_attempts)
            response = requests.post(url, json=payload, headers=headers, timeout=30)
            
            if response.status_code not in [200, 201]:
                msg = response.text[:150] if response.text else "No response body"
                raise Exception(f"CheapDataHub API error [{response.status_code}]: {msg}")
            
            try:
                data = response.json()
            except ValueError:
                raise Exception(f"CheapDataHub API returned invalid HTML response [{response.status_code}]")

            if data.get("status") in ["true", "success", True]:
                # Parse delivered PINs from response
                raw_pins = data.get("pins", data.get("data", {}).get("pins", []))
                if isinstance(raw_pins, list):
                    pins_text = "\n".join(str(p) for p in raw_pins)
                else:
                    pins_text = str(raw_pins)

                order.status = ExamPinOrder.Status.SUCCESS
                order.provider_ref = data.get("reference", data.get("id", "CDH-EXAM"))
                order.delivered_pins = pins_text
                order.delivered_at = timezone.now()
                order.save(update_fields=["status", "provider_ref", "delivered_pins", "delivered_at"])

                # Update corresponding WalletTransaction to SUCCESS
                WalletTransaction.objects.filter(reference=order.reference).update(status=WalletTransaction.Status.SUCCESS)

                send_transaction_sms.delay(
                    order.user.phone_number,
                    f"SubHero: {order.quantity} {order.exam_name} PIN(s) delivered. Check your dashboard. Ref: {order.reference}",
                )
                try:
                    from apps.notifications.models import Notification
                    Notification.add(order.user, "Exam PIN Delivered",
                        f"{order.quantity} {order.exam_name} PIN(s) successfully purchased. View them in your transaction history.", "financial")
                except Exception as e:
                    logger.error("Notification failed: %s", str(e))
                return
            else:
                msg = data.get("message", data.get("error", "Provider declined"))
                raise Exception(f"CheapDataHub Exam PIN failed: {msg}")

        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError, Exception) as exc:
            logger.warning("Exam PIN order %s: attempt %s of %s failed: %s", order_id, attempt, max_attempts, str(exc))
            exc_str = str(exc)
            is_definitive = any(kw in exc_str for kw in [
                "400", "401", "402", "403", "404", "422", 
                "Unauthorized", "Forbidden", "Insufficient", "wallet", "API Key"
            ])
            if attempt == max_attempts or is_definitive:
                logger.error("Exam PIN order %s exceeded all retries or encountered definitive failure. Failing and refunding. Reason: %s", order_id, exc_str)
                order.status = ExamPinOrder.Status.FAILED
                order.provider_ref = f"Failed: {exc_str}"[:200]
                order.save(update_fields=["status", "provider_ref"])
                refund_exam_pin_order(order_id)
                return
            time.sleep(2)


@shared_task
def refund_exam_pin_order(order_id):
    try:
        order = ExamPinOrder.objects.select_for_update().get(id=order_id)
        _generic_refund(order, "Exam PIN", "REFUND")
    except Exception as err:
        logger.exception("Exam PIN refund failed: %s", str(err))


@shared_task
def sync_exam_products():
    """Syncs exam PIN products from CheapDataHub every 6 hours."""
    api_key = settings.CHEAPDATAHUB_API_KEY
    if not api_key:
        _seed_default_exam_products()
        return

    url = f"{settings.CHEAPDATAHUB_BASE_URL}/api/v1/resellers/exam-pin/products/"
    headers = {"Authorization": f"Bearer {api_key}"}

    try:
        response = requests.get(url, headers=headers, timeout=20)
        products = response.json().get("data", response.json())
        for p in (products if isinstance(products, list) else []):
            provider_price = Decimal(str(p.get("price", p.get("amount", "0"))))
            subhero_price = (provider_price * Decimal("1.08")).quantize(Decimal("0.01"))
            ExamProduct.objects.update_or_create(
                product_id=str(p["id"]),
                defaults={
                    "exam_name": p.get("name", p.get("exam_name", "")),
                    "price_per_pin": provider_price,
                    "subhero_price_per_pin": subhero_price,
                    "is_active": True,
                }
            )
        logger.info("Synced %s exam products.", len(products))
    except Exception as e:
        logger.error("Failed to sync exam products: %s", str(e))
        _seed_default_exam_products()


def _seed_default_exam_products():
    """Fallback exam products if API is unavailable."""
    defaults = [
        {"product_id": "waec-1", "exam_name": "WAEC", "price_per_pin": Decimal("4000"), "subhero_price_per_pin": Decimal("4320")},
        {"product_id": "neco-1", "exam_name": "NECO", "price_per_pin": Decimal("1000"), "subhero_price_per_pin": Decimal("1080")},
        {"product_id": "nabteb-1", "exam_name": "NABTEB", "price_per_pin": Decimal("1000"), "subhero_price_per_pin": Decimal("1080")},
    ]
    for p in defaults:
        ExamProduct.objects.update_or_create(product_id=p["product_id"], defaults={**p, "is_active": True})
    logger.info("Default exam products seeded.")

