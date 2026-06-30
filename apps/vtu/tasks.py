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


def _format_phone(raw_phone: str) -> str:
    """
    Formats phone number to standard 11-digit local format (e.g. 08012345678)
    expected by CheapDataHub to prevent digital signature / phone validation errors.
    """
    if not raw_phone:
        return ""
    phone = str(raw_phone).replace("+", "").replace(" ", "").strip()
    if phone.startswith("234"):
        phone = "0" + phone[3:]
    if len(phone) == 10 and not phone.startswith("0"):
        phone = "0" + phone
    return phone


@shared_task(bind=True, max_retries=3)
def process_vtu_order(self, order_id):
    """
    Processes a customer VTU order atomically.
    1. Debits the customer's wallet.
    2. Sends the request to the Sabuss API with synchronous retries.
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

    api_key = getattr(settings, "SABUSS_API_KEY", "")
    pin = getattr(settings, "SABUSS_PIN", "")
    base_url = getattr(settings, "SABUSS_BASE_URL", "https://sabuss.com")

    if not api_key:
        logger.info("Sabuss API Key is not set or mocked. Simulating VTU success.")
        order.status = VTUOrder.Status.SUCCESS
        order.provider_ref = "MOCK-SABUSS-12345"
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

    url = f"{base_url}/vtu/api/buy/{api_key}"
    payload = {
        "pin": pin,
        "plan_id": str(order.plan_id),
        "phone": _format_phone(order.recipient),
        "reference": order.reference
    }

    max_attempts = 3
    for attempt in range(1, max_attempts + 1):
        try:
            logger.info("VTU order %s: calling Sabuss API (attempt %s/%s)", order_id, attempt, max_attempts)
            response = requests.post(url, data=payload, timeout=25)
            
            if response.status_code not in [200, 201]:
                raise Exception(f"Vending gateway connection error [{response.status_code}]")
            
            try:
                response_data = response.json()
            except ValueError:
                raise Exception("Vending gateway returned invalid JSON response")

            code = str(response_data.get("code"))
            if code in ["200", "400"]:
                order.status = VTUOrder.Status.SUCCESS
                order.provider_ref = response_data.get("reference", response_data.get("id", order.reference))
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
                msg = response_data.get("response", "Provider declined the request")
                raise Exception(f"Vending request failed: {msg}")

        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError, Exception) as exc:
            logger.warning("VTU order %s: attempt %s of %s failed: %s", order_id, attempt, max_attempts, str(exc))
            exc_str = str(exc)
            
            is_definitive = any(kw in exc_str.lower() for kw in [
                "invalid plan", "invalid line", "invalid mobile", "unauthorized", "insufficient", "wallet", "wrong pin"
            ])
            if attempt == max_attempts or is_definitive:
                logger.error("VTU order %s exceeded all retries or encountered definitive failure. Failing and refunding. Reason: %s", order_id, exc_str)
                order.status = VTUOrder.Status.FAILED
                
                clean_reason = "Vending network declined request"
                if "invalid line" in exc_str.lower():
                    clean_reason = "Invalid phone number for the selected network"
                elif "invalid plan" in exc_str.lower():
                    clean_reason = "Selected plan is currently unavailable"
                
                order.provider_ref = clean_reason
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
                description=f"Refund · {order.plan_name} to {order.recipient}"
            )

            # Dynamic Warning Notification
            try:
                from apps.notifications.models import Notification
                reason = order.provider_ref or "vending network error"
                Notification.add(
                    user=order.user,
                    title="VTU Order Failed - Refunded",
                    description=f"Your purchase of {order.plan_name} to {order.recipient} could not be completed (Reason: {reason}). ₦{order.amount:,.2f} has been fully refunded.",
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
    Daily / 6-hourly background synchronization with Sabuss active data plans.
    """
    logger.info("Sabuss VTU data plans synchronization triggered.")
    api_key = getattr(settings, "SABUSS_API_KEY", "")
    pin = getattr(settings, "SABUSS_PIN", "")
    base_url = getattr(settings, "SABUSS_BASE_URL", "https://sabuss.com")
    margin = Decimal(str(getattr(settings, "SABUSS_PROFIT_MARGIN", "0.10")))
    
    if not api_key:
        logger.warning("Sabuss API Key is not set. Skipping plan synchronization.")
        return

    url = f"{base_url}/vtu/api/plans/{api_key}"
    try:
        response = requests.post(url, data={'pin': pin, 'category': 'data'}, timeout=25)
        if response.status_code == 200:
            plans_data = response.json()
            if isinstance(plans_data, list) and len(plans_data) > 0:
                active_plan_ids = []
                import re
                for p in plans_data:
                    plan_id = str(p.get("plan_id"))
                    name = p.get("name", "")
                    amount_str = str(p.get("amount", "0"))
                    try:
                        provider_price = Decimal(amount_str)
                    except Exception:
                        provider_price = Decimal("0.00")
                    
                    # Compute customer retail price
                    subhero_price = (provider_price * (Decimal("1") + margin)).quantize(Decimal("0.01"))
                    
                    # Validity detection from name (e.g. "30 Days", "7 Days")
                    validity = ""
                    if "day" in name.lower():
                        match = re.search(r'(\d+)\s*days?', name, re.IGNORECASE)
                        if match:
                            validity = f"{match.group(1)} Days"
                        else:
                            validity = "1 Day" if "1day" in name.lower() or "1 day" in name.lower() else ""
                    elif "month" in name.lower():
                        match = re.search(r'(\d+)\s*months?', name, re.IGNORECASE)
                        if match:
                            validity = f"{int(match.group(1)) * 30} Days"
                        else:
                            validity = "30 Days"
                    
                    network = ""
                    plan_type = ""
                    name_lower = name.lower()
                    if "mtn" in name_lower:
                        network = "mtn"
                    elif "airtel" in name_lower:
                        network = "airtel"
                    elif "glo" in name_lower:
                        network = "glo"
                    elif "9mobile" in name_lower or "etisalat" in name_lower:
                        network = "9mobile"
                    else:
                        network = "other"

                    # Detect plan category/type from name
                    if "sme2" in name_lower or "sme 2" in name_lower:
                        plan_type = "SME2"
                    elif "sme" in name_lower:
                        plan_type = "SME"
                    elif "smart" in name_lower:
                        plan_type = "SMART"
                    elif "awoof" in name_lower:
                        plan_type = "AWOOF"
                    elif " cg" in name_lower or name_lower.endswith("cg"):
                        plan_type = "CG"
                    elif "gifting" in name_lower or "gift" in name_lower:
                        plan_type = "GIFTING"
                    elif "corporate" in name_lower:
                        plan_type = "CORPORATE"
                    else:
                        plan_type = "DATA"

                    VTUPlan.objects.update_or_create(
                        plan_id=plan_id,
                        defaults={
                            "network": network,
                            "plan_type": plan_type,
                            "name": name,
                            "provider_price": provider_price,
                            "subhero_price": subhero_price,
                            "validity": validity,
                            "is_active": True
                        }
                    )
                    active_plan_ids.append(plan_id)
                
                # Deactivate plans that were not in the sync response
                VTUPlan.objects.exclude(plan_id__in=active_plan_ids).update(is_active=False)
                logger.info("Successfully synced %s plans from Sabuss.", len(active_plan_ids))
                return
            else:
                logger.error("Sabuss plans endpoint returned an empty or invalid list.")
                return
        
        raise Exception(f"Failed to fetch plans: status={response.status_code}")
    except Exception as e:
        logger.error("Error syncing plans from Sabuss: %s. Keeping existing plans active.", str(e))


@shared_task
def check_api_wallet_balance():
    """
    Every 2 hours, check the pre-funded Naira wallet balance on Sabuss.
    Alert admin if balance drops below ₦10,000.
    """
    logger.info("Checking VTU Sabuss API wallet balance...")
    api_key = getattr(settings, "SABUSS_API_KEY", "")
    pin = getattr(settings, "SABUSS_PIN", "")
    base_url = getattr(settings, "SABUSS_BASE_URL", "https://sabuss.com")
    
    if not api_key:
        logger.warning("Sabuss API Key is not set. Skipping balance warning check.")
        return

    url = f"{base_url}/vtu/api/balance/{api_key}"
    try:
        response = requests.post(url, data={'pin': pin}, timeout=15)
        if response.status_code == 200:
            response_data = response.json()
            if str(response_data.get("code")) == "200":
                balance = Decimal(str(response_data.get("balance", "0")))
                logger.info("Sabuss balance check: ₦%s", balance)
                if balance < 10000:
                    logger.error("URGENT: Sabuss API wallet balance low: ₦%s. Please top up immediately.", balance)
            else:
                logger.error("Failed to check Sabuss API balance: %s", response_data.get("response"))
        else:
            logger.error("Failed to check Sabuss API balance: HTTP %s", response.status_code)
    except Exception as e:
        logger.error("Failed to check Sabuss API wallet balance: %s", str(e))



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
            description=f"Refund · {order_type_label} order {order.reference}",
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
    """Purchases airtime via Sabuss with synchronous retries and handles refunds."""
    try:
        order = AirtimeOrder.objects.get(id=order_id)
    except AirtimeOrder.DoesNotExist:
        logger.error("AirtimeOrder not found: %s", order_id)
        return

    if order.status != AirtimeOrder.Status.PROCESSING:
        return

    api_key = getattr(settings, "SABUSS_API_KEY", "")
    pin = getattr(settings, "SABUSS_PIN", "")
    base_url = getattr(settings, "SABUSS_BASE_URL", "https://sabuss.com")

    if not api_key:
        logger.info("Sabuss API Key is not set or mocked. Simulating Airtime success.")
        order.status = AirtimeOrder.Status.SUCCESS
        order.provider_ref = "MOCK-SABUSS-AIRTIME"
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

    net_map = {
        "mtn": "10",
        "airtel": "11",
        "glo": "12",
        "9mobile": "1651"
    }
    plan_id = net_map.get(order.network.lower())
    if not plan_id:
        logger.error("Unknown network for airtime: %s", order.network)
        order.status = AirtimeOrder.Status.FAILED
        order.provider_ref = "Invalid network"
        order.save(update_fields=["status", "provider_ref"])
        refund_airtime_order(order_id)
        return

    url = f"{base_url}/vtu/api/buy/{api_key}"
    payload = {
        "pin": pin,
        "plan_id": plan_id,
        "phone": _format_phone(order.recipient),
        "amount": str(int(order.amount)),
        "reference": order.reference
    }

    max_attempts = 3
    for attempt in range(1, max_attempts + 1):
        try:
            logger.info("Airtime order %s: calling Sabuss API (attempt %s/%s)", order_id, attempt, max_attempts)
            response = requests.post(url, data=payload, timeout=25)
            
            if response.status_code not in [200, 201]:
                raise Exception(f"Vending gateway connection error [{response.status_code}]")
            
            try:
                data = response.json()
            except ValueError:
                raise Exception("Vending gateway returned invalid JSON response")

            code = str(data.get("code"))
            if code in ["200", "400"]:
                order.status = AirtimeOrder.Status.SUCCESS
                order.provider_ref = data.get("reference", data.get("id", order.reference))
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
                msg = data.get("response", "Provider declined the request")
                raise Exception(f"Airtime vending request failed: {msg}")

        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError, Exception) as exc:
            logger.warning("Airtime order %s: attempt %s of %s failed: %s", order_id, attempt, max_attempts, str(exc))
            exc_str = str(exc)
            
            is_definitive = any(kw in exc_str.lower() for kw in [
                "invalid plan", "invalid line", "invalid mobile", "unauthorized", "insufficient", "wallet", "wrong pin"
            ])
            if attempt == max_attempts or is_definitive:
                logger.error("Airtime order %s exceeded all retries or encountered definitive failure. Failing and refunding. Reason: %s", order_id, exc_str)
                order.status = AirtimeOrder.Status.FAILED
                
                clean_reason = "Vending network declined request"
                if "invalid line" in exc_str.lower():
                    clean_reason = "Invalid phone number for the selected network"
                elif "invalid plan" in exc_str.lower():
                    clean_reason = "Selected airtime product is currently unavailable"

                order.provider_ref = clean_reason
                order.save(update_fields=["status", "provider_ref"])
                refund_airtime_order(order_id)
                return
            time.sleep(2)


@shared_task
def refund_airtime_order(order_id):
    try:
        with transaction.atomic():
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
        "phone_number": _format_phone(order.phone),
    }

    max_attempts = 3
    for attempt in range(1, max_attempts + 1):
        try:
            logger.info("Cable order %s: calling CheapDataHub API (attempt %s/%s)", order_id, attempt, max_attempts)
            response = requests.post(url, json=payload, headers=headers, timeout=20)
            
            if response.status_code not in [200, 201]:
                msg = response.text[:150] if response.text else "No response body"
                raise Exception(f"Vending gateway error [{response.status_code}]: {msg}")
            
            try:
                data = response.json()
            except ValueError:
                raise Exception(f"Vending gateway returned invalid response [{response.status_code}]")

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
                raise Exception(f"Cable TV subscription request failed: {msg}")

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
                order.provider_ref = f"Failed: {exc_str}"[:100]
                order.save(update_fields=["status", "provider_ref"])
                refund_cable_order(order_id)
                return
            time.sleep(2)


@shared_task
def refund_cable_order(order_id):
    try:
        with transaction.atomic():
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
        "phone_number": _format_phone(order.phone),
    }

    max_attempts = 3
    for attempt in range(1, max_attempts + 1):
        try:
            logger.info("Electricity order %s: calling CheapDataHub API (attempt %s/%s)", order_id, attempt, max_attempts)
            response = requests.post(url, json=payload, headers=headers, timeout=30)
            
            if response.status_code not in [200, 201]:
                msg = response.text[:150] if response.text else "No response body"
                raise Exception(f"Vending gateway error [{response.status_code}]: {msg}")
            
            try:
                data = response.json()
            except ValueError:
                raise Exception(f"Vending gateway returned invalid response [{response.status_code}]")

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
                raise Exception(f"Electricity vending request failed: {msg}")

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
                order.provider_ref = f"Failed: {exc_str}"[:100]
                order.save(update_fields=["status", "provider_ref"])
                refund_electricity_order(order_id)
                return
            time.sleep(2)


@shared_task
def refund_electricity_order(order_id):
    try:
        with transaction.atomic():
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
                raise Exception(f"Vending gateway error [{response.status_code}]: {msg}")
            
            try:
                data = response.json()
            except ValueError:
                raise Exception(f"Vending gateway returned invalid response [{response.status_code}]")

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
                raise Exception(f"Exam PIN vending request failed: {msg}")

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
                order.provider_ref = f"Failed: {exc_str}"[:100]
                order.save(update_fields=["status", "provider_ref"])
                refund_exam_pin_order(order_id)
                return
            time.sleep(2)


@shared_task
def refund_exam_pin_order(order_id):
    try:
        with transaction.atomic():
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

