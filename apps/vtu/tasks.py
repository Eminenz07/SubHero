import logging
import requests
import time
from datetime import timedelta
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
from apps.vtu.providers import get_provider
from apps.vtu.providers.base import PurchaseStatus, derive_network, derive_plan_type
from apps.vtu.providers.errors import (
    ProviderAuthError,
    ProviderDeclinedError,
    ProviderError,
    ProviderNotFoundError,
    ProviderRateLimitedError,
    ProviderTransientError,
    ProviderValidationError,
)
from apps.wallet.models import Wallet, WalletTransaction
from apps.wallet.services import debit_wallet, credit_wallet, InsufficientBalanceError, WalletFrozenError
from apps.notifications.tasks import send_transaction_sms

logger = logging.getLogger(__name__)

MAX_PROVIDER_ATTEMPTS = 3
RETRY_BACKOFF_SECONDS = 2


def _is_definitive(exc: Exception) -> bool:
    """True when retrying the same request cannot change the outcome."""
    return isinstance(
        exc,
        (
            ProviderAuthError,
            ProviderValidationError,
            ProviderNotFoundError,
            ProviderDeclinedError,
        ),
    )


def _clean_provider_message(exc: Exception, fallback: str) -> str:
    """Turn a provider exception into a short, customer-safe reason."""
    text = str(exc).strip()
    if not text:
        return fallback
    lowered = text.lower()
    if "not eligible" in lowered or "not allowed to migrate" in lowered:
        return "This number is not eligible for the selected bundle"
    if "invalid" in lowered and "phone" in lowered:
        return "Invalid phone number for the selected network"
    if "invalid" in lowered and "plan" in lowered:
        return "Selected plan is currently unavailable"
    if "insufficient" in lowered or "balance" in lowered:
        return "Provider wallet balance is too low"
    if "smartcard" in lowered or "decoder" in lowered:
        return "Invalid smart card number for the selected provider"
    if "meter" in lowered:
        return "Invalid meter number for the selected distribution company"
    return fallback


def _format_phone(raw_phone: str) -> str:
    """
    Formats phone number to standard 11-digit local format (e.g. 08012345678)
    expected by the VTU provider to prevent digital signature / phone validation errors.
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
    2. Sends the request to the configured VTU provider with synchronous retries.
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

    if getattr(settings, "VTU_MOCK", False):
        logger.info("VTU_MOCK is active. Simulating VTU success.")
        order.status = VTUOrder.Status.SUCCESS
        order.provider_ref = "MOCK-DANCITY-12345"
        order.delivered_at = timezone.now()
        order.save(update_fields=["status", "provider_ref", "delivered_at"])

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

    provider = get_provider()
    phone = _format_phone(order.recipient)

    for attempt in range(1, MAX_PROVIDER_ATTEMPTS + 1):
        try:
            logger.info(
                "VTU order %s: buying data via %s (attempt %s/%s)",
                order_id, provider.name, attempt, MAX_PROVIDER_ATTEMPTS,
            )
            result = provider.buy_data(order.plan_id, phone, order.reference)

            if result.status in (PurchaseStatus.PENDING, PurchaseStatus.PROCESSING):
                order.provider_ref = result.provider_ref or order.reference
                order.save(update_fields=["provider_ref"])
                logger.info("VTU order %s is still settling upstream (%s).", order_id, result.provider_ref)
                return

            order.status = VTUOrder.Status.SUCCESS
            order.provider_ref = result.provider_ref or order.reference
            if result.amount_paid is not None:
                order.api_cost = result.amount_paid
            order.delivered_at = timezone.now()
            order.save(update_fields=["status", "provider_ref", "api_cost", "delivered_at"])

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

        except Exception as exc:
            logger.warning(
                "VTU order %s: attempt %s of %s failed: %s",
                order_id, attempt, MAX_PROVIDER_ATTEMPTS, str(exc),
            )
            if attempt == MAX_PROVIDER_ATTEMPTS or _is_definitive(exc):
                logger.error("VTU order %s failed permanently: %s", order_id, str(exc))
                order.status = VTUOrder.Status.FAILED
                order.provider_ref = _clean_provider_message(exc, "Vending network declined request")
                order.save(update_fields=["status", "provider_ref"])
                refund_vtu_order(order_id)
                return
            time.sleep(RETRY_BACKOFF_SECONDS)


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

            # Send instant admin failure alert email
            try:
                from apps.notifications.services import send_admin_order_failure_alert
                send_admin_order_failure_alert(
                    order_type="VTU Data",
                    order_reference=order.reference,
                    user=order.user,
                    error_reason=order.provider_ref or "Vending gateway declined request",
                    details=f"Plan: {order.plan_name}, Recipient: {order.recipient}, Network: {order.network}"
                )
            except Exception as mail_err:
                logger.error("Failed to trigger admin VTU failure alert email: %s", str(mail_err))

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
    Background synchronisation of active data plans from the configured VTU provider.
    """
    provider = get_provider()
    logger.info("%s VTU data plans synchronization triggered.", provider.name)

    from apps.admin_panel.models import SystemSetting
    try:
        vtu_margin_pct = Decimal(SystemSetting.get("vtu_profit_margin", "10.00"))
    except Exception:
        vtu_margin_pct = Decimal("10.00")
    margin = vtu_margin_pct / Decimal("100")

    try:
        plans = provider.list_data_plans()
    except ProviderError as exc:
        logger.error("Error fetching data plans from %s: %s. Keeping existing plans active.", provider.name, exc)
        return
    except Exception as exc:
        logger.error("Unexpected error fetching data plans from %s: %s", provider.name, exc)
        return

    if not plans:
        logger.warning("%s returned an empty data plan catalogue. Keeping existing plans active.", provider.name)
        return

    active_plan_ids = []
    for plan in plans:
        provider_price = plan.price
        subhero_price = (provider_price * (Decimal("1") + margin)).quantize(Decimal("0.01"))

        VTUPlan.objects.update_or_create(
            plan_id=plan.plan_id,
            defaults={
                "provider_product": plan.provider_product,
                "network": derive_network(plan.provider_product) if plan.provider_product else "other",
                "plan_type": derive_plan_type(plan.provider_product) if plan.provider_product else "DATA",
                "name": plan.name[:100],
                "provider_price": provider_price,
                "subhero_price": subhero_price,
                "validity": plan.validity,
                "is_active": True,
            },
        )
        active_plan_ids.append(plan.plan_id)

    VTUPlan.objects.exclude(plan_id__in=active_plan_ids).update(is_active=False)
    logger.info("Successfully synced %s data plans from %s.", len(active_plan_ids), provider.name)


@shared_task
def check_api_wallet_balance():
    """
    Every 2 hours, checks VTU provider and JAP (USD) balances against AlertConfig thresholds.
    Dispatches admin alert email if limits are breached.
    """
    logger.info("Running scheduled API wallet balance verification task...")
    
    from apps.admin_panel.models import AlertConfig
    from apps.admin_panel.utils import syslog
    from django.core.mail import send_mail
    
    alert_config = AlertConfig.objects.first()
    if not alert_config:
        logger.warning("AlertConfig not found. Skipping balance verification checks.")
        return
 
    # 1. Fetch the VTU provider wallet balance
    provider_balance = Decimal("0.00")
    provider_label = getattr(settings, "VTU_PROVIDER", "dancity")
    try:
        provider_balance = get_provider().get_balance()
    except Exception as e:
        logger.error("Error fetching %s balance: %s", provider_label, str(e))

    # 2. Fetch Ogaviral NGN balance
    ogaviral_balance = Decimal("0.00")
    try:
        if getattr(settings, "OGAVIRAL_API_KEY", ""):
            r = requests.post(settings.OGAVIRAL_API_URL, data={
                "key": settings.OGAVIRAL_API_KEY, "action": "balance"
            }, timeout=15)
            if r.status_code == 200:
                ogaviral_balance = Decimal(str(r.json()['balance']))
    except Exception as e:
        logger.error("Error fetching Ogaviral balance: %s", str(e))

    logger.info(
        "Balances retrieved — %s: ₦%s, Ogaviral: ₦%s",
        provider_label, provider_balance, ogaviral_balance,
    )

    # 3. Check thresholds and alert
    alert_messages = []

    # VTU provider
    if provider_balance <= alert_config.provider_critical_threshold:
        alert_messages.append(f"CRITICAL: {provider_label} balance has dropped to ₦{provider_balance:,.2f} (Threshold: ₦{alert_config.provider_critical_threshold:,.2f})!")
        syslog("ERROR", "VTU", f"{provider_label} balance CRITICAL: ₦{provider_balance:,.2f}")
    elif provider_balance <= alert_config.provider_warning_threshold:
        alert_messages.append(f"WARNING: {provider_label} balance is low at ₦{provider_balance:,.2f} (Threshold: ₦{alert_config.provider_warning_threshold:,.2f})")
        syslog("WARNING", "VTU", f"{provider_label} balance low: ₦{provider_balance:,.2f}")
        
    # Ogaviral
    if ogaviral_balance <= alert_config.ogaviral_critical_threshold:
        alert_messages.append(f"CRITICAL: Ogaviral SMM balance has dropped to ₦{ogaviral_balance:,.2f} (Threshold: ₦{alert_config.ogaviral_critical_threshold:,.2f})!")
        syslog("ERROR", "SMM", f"Ogaviral balance CRITICAL: ₦{ogaviral_balance:,.2f}")
    elif ogaviral_balance <= alert_config.ogaviral_warning_threshold:
        alert_messages.append(f"WARNING: Ogaviral SMM balance is low at ₦{ogaviral_balance:,.2f} (Threshold: ₦{alert_config.ogaviral_warning_threshold:,.2f})")
        syslog("WARNING", "SMM", f"Ogaviral balance low: ₦{ogaviral_balance:,.2f}")

    if alert_messages:
        try:
            send_mail(
                subject="SubHero HQ: API Wallet Low Balance Alert",
                message="\n".join(alert_messages) + "\n\nPlease fund the provider wallets immediately to prevent system downtime.",
                from_email=getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@subhero.com.ng"),
                recipient_list=[alert_config.alert_email],
                fail_silently=False
            )
            logger.info("Sent balance alert notification email to %s", alert_config.alert_email)
        except Exception as e:
            logger.error("Failed to send balance alert email: %s", str(e))



# =============================================================
# AIRTIME TASKS
# =============================================================

def _generic_refund(order, order_type_label, refund_prefix, partial_amount=None):
    """Helper: refund a VTU-type order atomically.

    ``partial_amount`` refunds only part of the order value, used when a
    provider delivered some of a split purchase but not all of it.
    """
    amount = order.amount if partial_amount is None else Decimal(str(partial_amount))
    if amount <= 0:
        logger.info("%s Order %s has nothing left to refund.", order_type_label, order.reference)
        return

    with transaction.atomic():
        refund_ref = f"{refund_prefix}-{order.reference}"
        if WalletTransaction.objects.filter(reference=refund_ref).exists():
            logger.warning("%s Order %s already refunded.", order_type_label, order.reference)
            return

        wallet = Wallet.objects.select_for_update().get(user=order.user)
        balance_before = wallet.balance
        wallet.balance += amount
        wallet.save(update_fields=["balance"])

        order.status = "FAILED"
        order.save(update_fields=["status"])

        # Update original debit WalletTransaction to FAILED
        WalletTransaction.objects.filter(reference=order.reference).update(status=WalletTransaction.Status.FAILED)

        WalletTransaction.objects.create(
            wallet=wallet,
            txn_type=WalletTransaction.TxnType.REFUND,
            amount=amount,
            balance_before=balance_before,
            balance_after=wallet.balance,
            reference=refund_ref,
            status=WalletTransaction.Status.SUCCESS,
            description=f"Refund · {order_type_label} order {order.reference}",
        )
        logger.info("%s refund success: ₦%s restored to User %s", order_type_label, amount, order.user.id)

    try:
        send_transaction_sms.delay(
            order.user.phone_number,
            f"SubHero: ₦{amount:,.0f} refunded. {order_type_label} Order {order.reference} could not be completed.",
        )
    except Exception as sms_err:
        logger.error("Refund SMS failed: %s", str(sms_err))


def _split_airtime_chunks(amount: Decimal, max_amount: Decimal | None) -> list[Decimal]:
    """Split a top-up into provider-sized chunks, largest first."""
    if max_amount is None or amount <= max_amount:
        return [amount]

    chunks: list[Decimal] = []
    remaining = amount
    while remaining > 0:
        chunk = min(remaining, max_amount)
        chunks.append(chunk)
        remaining -= chunk
    return chunks


@shared_task(bind=True, max_retries=3)
def process_airtime_order(self, order_id):
    """Purchases airtime via the configured VTU provider with synchronous retries and handles refunds."""
    try:
        order = AirtimeOrder.objects.get(id=order_id)
    except AirtimeOrder.DoesNotExist:
        logger.error("AirtimeOrder not found: %s", order_id)
        return

    if order.status != AirtimeOrder.Status.PROCESSING:
        return

    if getattr(settings, "VTU_MOCK", False):
        logger.info("VTU_MOCK is active. Simulating Airtime success.")
        order.status = AirtimeOrder.Status.SUCCESS
        order.provider_ref = "MOCK-DANCITY-AIRTIME"
        order.delivered_at = timezone.now()
        order.save(update_fields=["status", "provider_ref", "delivered_at"])

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

    provider = get_provider()

    try:
        provider_product = order.provider_product or provider.resolve_airtime_product(order.network)
    except Exception as exc:
        logger.error("Airtime order %s: could not resolve provider product: %s", order_id, exc)
        order.status = AirtimeOrder.Status.FAILED
        order.provider_ref = "Selected airtime product is currently unavailable"
        order.save(update_fields=["status", "provider_ref"])
        refund_airtime_order(order_id)
        return

    phone = _format_phone(order.recipient)
    chunks = _split_airtime_chunks(order.amount, provider.max_airtime_amount)
    if len(chunks) > 1:
        logger.info(
            "Airtime order %s: splitting ₦%s into %s provider-sized transactions.",
            order_id, order.amount, len(chunks),
        )

    delivered_amount = Decimal("0")
    total_api_cost = Decimal("0")
    provider_refs: list[str] = []
    last_message = ""

    for chunk in chunks:
        result = None
        for attempt in range(1, MAX_PROVIDER_ATTEMPTS + 1):
            try:
                logger.info(
                    "Airtime order %s: buying ₦%s via %s (attempt %s/%s)",
                    order_id, chunk, provider.name, attempt, MAX_PROVIDER_ATTEMPTS,
                )
                result = provider.buy_airtime(provider_product, phone, chunk, order.reference)

                if result.status in (PurchaseStatus.PENDING, PurchaseStatus.PROCESSING):
                    order.provider_ref = result.provider_ref or order.reference
                    order.save(update_fields=["provider_ref"])
                    logger.info("Airtime order %s is still settling upstream (%s).", order_id, result.provider_ref)
                    return

                break

            except Exception as exc:
                last_message = _clean_provider_message(exc, "Vending network declined request")
                logger.warning(
                    "Airtime order %s: attempt %s of %s failed: %s",
                    order_id, attempt, MAX_PROVIDER_ATTEMPTS, str(exc),
                )
                if attempt == MAX_PROVIDER_ATTEMPTS or _is_definitive(exc):
                    logger.error("Airtime order %s failed permanently: %s", order_id, str(exc))
                    order.status = AirtimeOrder.Status.FAILED
                    order.provider_ref = last_message
                    order.save(update_fields=["status", "provider_ref"])
                    refund_airtime_order(order_id, partial_amount=order.amount - delivered_amount)
                    return
                time.sleep(RETRY_BACKOFF_SECONDS)

        if result is None:
            return

        delivered_amount += chunk
        if result.amount_paid is not None:
            total_api_cost += result.amount_paid
        if result.provider_ref:
            provider_refs.append(result.provider_ref)

    order.status = AirtimeOrder.Status.SUCCESS
    order.provider_ref = provider_refs[-1] if provider_refs else order.reference
    order.provider_product = provider_product
    order.api_cost = total_api_cost if total_api_cost else order.api_cost
    order.delivered_at = timezone.now()
    order.save(update_fields=["status", "provider_ref", "provider_product", "api_cost", "delivered_at"])

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


@shared_task
def refund_airtime_order(order_id, partial_amount=None):
    try:
        with transaction.atomic():
            order = AirtimeOrder.objects.select_for_update().get(id=order_id)
            _generic_refund(order, "Airtime", "REFUND", partial_amount=partial_amount)
    except Exception as err:
        logger.exception("Airtime refund failed: %s", str(err))


# =============================================================
# CABLE TV TASKS
# =============================================================

@shared_task(bind=True, max_retries=3)
def process_cable_order(self, order_id):
    """Subscribes a cable TV plan via the configured VTU provider with synchronous retries."""
    try:
        order = CableOrder.objects.get(id=order_id)
    except CableOrder.DoesNotExist:
        logger.error("CableOrder not found: %s", order_id)
        return

    if order.status != CableOrder.Status.PROCESSING:
        return

    if getattr(settings, "VTU_MOCK", False):
        logger.info("VTU_MOCK is active. Simulating Cable success.")
        order.status = CableOrder.Status.SUCCESS
        order.provider_ref = "MOCK-DANCITY-CABLE"
        order.delivered_at = timezone.now()
        order.save(update_fields=["status", "provider_ref", "delivered_at"])
        
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

    provider = get_provider()

    try:
        provider_product = order.provider_product or provider.resolve_cable_product(order.provider)
    except Exception as exc:
        logger.error("Cable order %s: could not resolve provider product: %s", order_id, exc)
        order.status = CableOrder.Status.FAILED
        order.provider_ref = "Selected package is currently unavailable"
        order.save(update_fields=["status", "provider_ref"])
        refund_cable_order(order_id)
        return

    customer_name = order.customer_name
    if not customer_name:
        try:
            customer_name = provider.validate_cable(order.card_number, provider_product)
        except Exception as exc:
            logger.error("Cable order %s: smartcard validation failed: %s", order_id, exc)
            order.status = CableOrder.Status.FAILED
            order.provider_ref = _clean_provider_message(exc, "Invalid smart card number")
            order.save(update_fields=["status", "provider_ref"])
            refund_cable_order(order_id)
            return

    for attempt in range(1, MAX_PROVIDER_ATTEMPTS + 1):
        try:
            logger.info(
                "Cable order %s: buying via %s (attempt %s/%s)",
                order_id, provider.name, attempt, MAX_PROVIDER_ATTEMPTS,
            )
            result = provider.buy_cable(
                order.plan_id, order.card_number, customer_name, order.reference
            )

            if result.status in (PurchaseStatus.PENDING, PurchaseStatus.PROCESSING):
                order.provider_ref = result.provider_ref or order.reference
                order.save(update_fields=["provider_ref"])
                logger.info("Cable order %s is still settling upstream (%s).", order_id, result.provider_ref)
                return

            order.status = CableOrder.Status.SUCCESS
            order.provider_ref = result.provider_ref or order.reference
            order.provider_product = provider_product
            order.customer_name = customer_name
            if result.amount_paid is not None:
                order.api_cost = result.amount_paid
            order.delivered_at = timezone.now()
            order.save(
                update_fields=[
                    "status", "provider_ref", "provider_product",
                    "customer_name", "api_cost", "delivered_at",
                ]
            )

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

        except Exception as exc:
            logger.warning(
                "Cable order %s: attempt %s of %s failed: %s",
                order_id, attempt, MAX_PROVIDER_ATTEMPTS, str(exc),
            )
            if attempt == MAX_PROVIDER_ATTEMPTS or _is_definitive(exc):
                logger.error("Cable order %s failed permanently: %s", order_id, str(exc))
                order.status = CableOrder.Status.FAILED
                order.provider_ref = _clean_provider_message(exc, "Cable TV subscription request failed")
                order.save(update_fields=["status", "provider_ref"])
                refund_cable_order(order_id)
                return
            time.sleep(RETRY_BACKOFF_SECONDS)


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
    """Syncs cable TV packages from the configured VTU provider every 6 hours."""
    provider = get_provider()

    try:
        plans = provider.list_cable_plans()
    except Exception as exc:
        logger.error("Failed to fetch cable plans from %s: %s", provider.name, exc)
        return

    if not plans:
        logger.warning("%s returned no cable packages. Keeping existing plans active.", provider.name)
        return

    active_plan_ids = []
    for plan in plans:
        provider_price = plan.price
        subhero_price = (provider_price * Decimal("1.04")).quantize(Decimal("0.01"))
        CablePlan.objects.update_or_create(
            plan_id=plan.plan_id,
            defaults={
                "provider": plan.provider,
                "provider_product": plan.provider_product,
                "name": plan.name[:150],
                "amount": provider_price,
                "subhero_price": subhero_price,
                "is_active": True,
            },
        )
        active_plan_ids.append(plan.plan_id)

    CablePlan.objects.exclude(plan_id__in=active_plan_ids).update(is_active=False)
    logger.info("Synced %s cable packages from %s.", len(active_plan_ids), provider.name)


# =============================================================
# ELECTRICITY TASKS
# =============================================================

@shared_task(bind=True, max_retries=3)
def process_electricity_order(self, order_id):
    """Vends electricity token via the configured VTU provider with synchronous retries."""
    try:
        order = ElectricityOrder.objects.get(id=order_id)
    except ElectricityOrder.DoesNotExist:
        logger.error("ElectricityOrder not found: %s", order_id)
        return

    if order.status != ElectricityOrder.Status.PROCESSING:
        return

    if getattr(settings, "VTU_MOCK", False):
        logger.info("VTU_MOCK is active. Simulating Electricity success.")
        order.status = ElectricityOrder.Status.SUCCESS
        order.provider_ref = "MOCK-DANCITY-ELEC"
        order.token = "4321-8765-0912-3456-7890"
        order.units = "45.8"
        order.delivered_at = timezone.now()
        order.save(update_fields=["status", "provider_ref", "token", "units", "delivered_at"])
        
        WalletTransaction.objects.filter(reference=order.reference).update(status=WalletTransaction.Status.SUCCESS)
        
        send_transaction_sms.delay(
            order.user.phone_number,
            f"SubHero: ₦{order.amount:,.0f} electricity vended for {order.meter_number}. Token: {order.token} Ref: {order.reference}",
        )
        try:
            from apps.notifications.models import Notification
            Notification.add(order.user, "Electricity Purchase Successful",
                f"₦{order.amount:,.0f} vended for meter {order.meter_number}. Token: {order.token}.", "financial")
        except Exception as e:
            logger.error("Notification failed: %s", str(e))
        return

    provider = get_provider()

    try:
        biller_code = provider.resolve_electricity_biller(order.disco_id)
    except Exception as exc:
        logger.error("Electricity order %s: could not resolve biller code: %s", order_id, exc)
        biller_code = order.disco_id

    customer_name = order.customer_name
    if not customer_name:
        try:
            customer_name = provider.validate_meter(
                order.meter_number, biller_code, order.amount, order.meter_type
            )
        except Exception as exc:
            logger.error("Electricity order %s: meter validation failed: %s", order_id, exc)
            order.status = ElectricityOrder.Status.FAILED
            order.provider_ref = _clean_provider_message(exc, "Invalid meter number")
            order.save(update_fields=["status", "provider_ref"])
            refund_electricity_order(order_id)
            return

    for attempt in range(1, MAX_PROVIDER_ATTEMPTS + 1):
        try:
            logger.info(
                "Electricity order %s: buying via %s (attempt %s/%s)",
                order_id, provider.name, attempt, MAX_PROVIDER_ATTEMPTS,
            )
            result = provider.buy_electricity(
                order.meter_number,
                biller_code,
                order.meter_type,
                order.amount,
                customer_name,
                order.address,
                order.reference,
            )

            if result.status in (PurchaseStatus.PENDING, PurchaseStatus.PROCESSING):
                order.provider_ref = result.provider_ref or order.reference
                order.save(update_fields=["provider_ref"])
                logger.info("Electricity order %s is still settling upstream (%s).", order_id, result.provider_ref)
                return

            order.status = ElectricityOrder.Status.SUCCESS
            order.provider_ref = result.provider_ref or order.reference
            order.customer_name = customer_name
            order.token = result.extra.get("token", "")
            order.units = result.extra.get("units", "")
            if result.amount_paid is not None:
                order.api_cost = result.amount_paid
            order.delivered_at = timezone.now()
            order.save(
                update_fields=[
                    "status", "provider_ref", "customer_name",
                    "token", "units", "api_cost", "delivered_at",
                ]
            )

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

        except Exception as exc:
            logger.warning(
                "Electricity order %s: attempt %s of %s failed: %s",
                order_id, attempt, MAX_PROVIDER_ATTEMPTS, str(exc),
            )
            if attempt == MAX_PROVIDER_ATTEMPTS or _is_definitive(exc):
                logger.error("Electricity order %s failed permanently: %s", order_id, str(exc))
                order.status = ElectricityOrder.Status.FAILED
                order.provider_ref = _clean_provider_message(exc, "Electricity vending request failed")
                order.save(update_fields=["status", "provider_ref"])
                refund_electricity_order(order_id)
                return
            time.sleep(RETRY_BACKOFF_SECONDS)


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
    """Purchases exam PINs via the configured VTU provider and stores the delivered tokens."""
    try:
        order = ExamPinOrder.objects.get(id=order_id)
    except ExamPinOrder.DoesNotExist:
        logger.error("ExamPinOrder not found: %s", order_id)
        return

    if order.status != ExamPinOrder.Status.PROCESSING:
        return

    if getattr(settings, "VTU_MOCK", False):
        logger.info("VTU_MOCK is active. Simulating Exam PIN success.")
        pins_list = [f"MOCK-PIN-{i}-12345-67890" for i in range(1, order.quantity + 1)]
        pins_text = "\n".join(pins_list)
        
        order.status = ExamPinOrder.Status.SUCCESS
        order.provider_ref = "MOCK-DANCITY-EXAM"
        order.delivered_pins = pins_text
        order.delivered_at = timezone.now()
        order.save(update_fields=["status", "provider_ref", "delivered_pins", "delivered_at"])
        
        WalletTransaction.objects.filter(reference=order.reference).update(status=WalletTransaction.Status.SUCCESS)
        
        send_transaction_sms.delay(
            order.user.phone_number,
            f"SubHero: {order.quantity} {order.exam_name} PIN(s) delivered. Check your dashboard. Ref: {order.reference}",
        )
        try:
            from apps.notifications.models import Notification
            Notification.add(order.user, "Exam PINs Purchased Successfully",
                f"Your purchase of {order.quantity} {order.exam_name} PIN(s) was successful.", "financial")
        except Exception as e:
            logger.error("Notification failed: %s", str(e))
        return

    provider = get_provider()

    for attempt in range(1, MAX_PROVIDER_ATTEMPTS + 1):
        try:
            logger.info(
                "Exam PIN order %s: buying via %s (attempt %s/%s)",
                order_id, provider.name, attempt, MAX_PROVIDER_ATTEMPTS,
            )
            result = provider.buy_exam_pin(
                order.exam_name, order.quantity, order.reference
            )

            if result.status in (PurchaseStatus.PENDING, PurchaseStatus.PROCESSING):
                order.provider_ref = result.provider_ref or order.reference
                order.save(update_fields=["provider_ref"])
                logger.info("Exam PIN order %s is still settling upstream (%s).", order_id, result.provider_ref)
                return

            raw_pins = result.extra.get("pins", "")
            if isinstance(raw_pins, (list, tuple)):
                pins_text = "\n".join(str(pin) for pin in raw_pins)
            elif raw_pins:
                pins_text = str(raw_pins)
            else:
                pins_text = ""

            order.status = ExamPinOrder.Status.SUCCESS
            order.provider_ref = result.provider_ref or order.reference
            order.delivered_pins = pins_text
            if result.amount_paid is not None:
                order.api_cost = result.amount_paid
            order.delivered_at = timezone.now()
            order.save(update_fields=["status", "provider_ref", "delivered_pins", "api_cost", "delivered_at"])

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

        except Exception as exc:
            logger.warning(
                "Exam PIN order %s: attempt %s of %s failed: %s",
                order_id, attempt, MAX_PROVIDER_ATTEMPTS, str(exc),
            )
            if attempt == MAX_PROVIDER_ATTEMPTS or _is_definitive(exc):
                logger.error("Exam PIN order %s failed permanently: %s", order_id, str(exc))
                order.status = ExamPinOrder.Status.FAILED
                order.provider_ref = _clean_provider_message(exc, "Exam PIN vending request failed")
                order.save(update_fields=["status", "provider_ref"])
                refund_exam_pin_order(order_id)
                return
            time.sleep(RETRY_BACKOFF_SECONDS)


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
    """Syncs exam PIN products from the configured VTU provider every 12 hours."""
    provider = get_provider()

    try:
        products = provider.list_exam_products()
    except Exception as exc:
        logger.error("Failed to fetch exam products from %s: %s", provider.name, exc)
        return

    if not products:
        logger.warning("%s returned no exam products. Keeping existing products active.", provider.name)
        return

    active_product_ids = []
    for product in products:
        provider_price = product.price
        if provider_price <= 0:
            logger.warning(
                "Skipping exam product '%s': provider did not expose a unit price.", product.name
            )
            continue

        subhero_price = (provider_price * Decimal("1.08")).quantize(Decimal("0.01"))
        ExamProduct.objects.update_or_create(
            product_id=product.name,
            defaults={
                "exam_name": product.name[:50],
                "price_per_pin": provider_price,
                "subhero_price_per_pin": subhero_price,
                "is_active": True,
            },
        )
        active_product_ids.append(product.name)

    ExamProduct.objects.exclude(product_id__in=active_product_ids).update(is_active=False)
    logger.info("Synced %s exam products from %s.", len(active_product_ids), provider.name)


# =============================================================
# PENDING ORDER RECONCILIATION
# =============================================================

_ORDER_MODELS_WITH_REFUNDS = (
    (VTUOrder, refund_vtu_order),
    (AirtimeOrder, refund_airtime_order),
    (CableOrder, refund_cable_order),
    (ElectricityOrder, refund_electricity_order),
    (ExamPinOrder, refund_exam_pin_order),
)


def _find_order_by_identifiers(identifiers: list[str]):
    """Find the SubHero order matching any provider-side identifier."""
    clean = [str(value).strip() for value in identifiers if value and str(value).strip()]
    if not clean:
        return None, None

    for model, refund_task in _ORDER_MODELS_WITH_REFUNDS:
        order = model.objects.filter(reference__in=clean).first()
        if order is None:
            order = model.objects.filter(provider_ref__in=clean).first()
        if order is not None:
            return order, refund_task
    return None, None


@shared_task
def reconcile_dancity_event(event: str, data: dict):
    """
    Applies a provider webhook event to the matching SubHero order.

    Events are idempotent: the same delivery may arrive more than once.
    """
    status = str(data.get("status") or "").strip().lower()
    event = (event or "").strip().lower()

    succeeded = status == "success" or event == "transaction.success"
    failed = status in ("failed", "cancelled") or event == "transaction.failed"

    if not succeeded and not failed:
        logger.info("Ignoring Dancity webhook event %s with status %s.", event, status or "none")
        return

    identifiers = [
        data.get("customerRef"),
        data.get("reference"),
        data.get("transactionId"),
        data.get("tranxId"),
    ]

    order, refund_task = _find_order_by_identifiers(identifiers)

    if order is None:
        # The webhook carries Dancity-side identifiers only, so recover our
        # customerRef by asking the provider about the transaction.
        try:
            provider = get_provider()
        except Exception:
            provider = None

        if provider is not None:
            for identifier in identifiers:
                if not identifier:
                    continue
                try:
                    transaction = provider.get_transaction(str(identifier))
                except Exception:
                    continue
                customer_ref = transaction.get("customerRef")
                if customer_ref:
                    order, refund_task = _find_order_by_identifiers([str(customer_ref)])
                    if order is not None:
                        break

    if order is None:
        logger.info(
            "Dancity webhook identifiers %s did not match any SubHero order.",
            [str(value) for value in identifiers if value],
        )
        return

    model = type(order)

    if order.status == model.Status.SUCCESS:
        return

    if succeeded:
        order.status = model.Status.SUCCESS
        order.provider_ref = str(data.get("transactionId") or order.provider_ref)
        order.delivered_at = timezone.now()
        order.save(update_fields=["status", "provider_ref", "delivered_at"])
        WalletTransaction.objects.filter(reference=order.reference).update(
            status=WalletTransaction.Status.SUCCESS
        )
        logger.info("Webhook marked %s %s as SUCCESS.", model.__name__, order.reference)
    else:
        order.status = model.Status.FAILED
        order.provider_ref = "Provider transaction failed"
        order.save(update_fields=["status", "provider_ref"])
        refund_task(order.id)
        logger.info("Webhook marked %s %s as FAILED and refunded.", model.__name__, order.reference)


@shared_task
def poll_pending_vtu_orders():
    """
    Re-queries the provider for orders it accepted but has not settled yet.

    The provider can answer a purchase with PENDING/PROCESSING. Those orders stay
    in PROCESSING until either the webhook lands or this poller confirms them.
    """
    if getattr(settings, "VTU_MOCK", False):
        return

    provider = get_provider()
    cutoff = timezone.now() - timedelta(seconds=60)

    order_sets = (
        (VTUOrder, refund_vtu_order),
        (AirtimeOrder, refund_airtime_order),
        (CableOrder, refund_cable_order),
        (ElectricityOrder, refund_electricity_order),
        (ExamPinOrder, refund_exam_pin_order),
    )

    for model, refund_task in order_sets:
        pending = (
            model.objects
            .filter(status=model.Status.PROCESSING, created_at__lte=cutoff)
            .order_by("created_at")[:50]
        )

        for order in pending:
            reference = order.provider_ref or order.reference
            if not reference:
                continue

            try:
                transaction = provider.get_transaction(reference)
            except Exception as exc:
                logger.warning(
                    "Could not reconcile %s %s: %s", model.__name__, order.reference, exc
                )
                continue

            status = str(transaction.get("status") or "").strip().upper()
            if not status:
                continue

            if status == "SUCCESS":
                order.status = model.Status.SUCCESS
                order.provider_ref = str(transaction.get("tranxId") or order.provider_ref)
                order.delivered_at = timezone.now()
                update_fields = ["status", "provider_ref", "delivered_at"]

                if isinstance(order, ElectricityOrder):
                    token = transaction.get("token")
                    units = transaction.get("units")
                    if token:
                        order.token = str(token)
                        update_fields.append("token")
                    if units:
                        order.units = str(units)
                        update_fields.append("units")

                order.save(update_fields=update_fields)
                WalletTransaction.objects.filter(reference=order.reference).update(
                    status=WalletTransaction.Status.SUCCESS
                )
                logger.info("Reconciled %s %s as SUCCESS.", model.__name__, order.reference)

            elif status in ("FAILED", "CANCELLED"):
                order.status = model.Status.FAILED
                order.provider_ref = str(
                    transaction.get("apiResponse") or "Provider transaction failed"
                )[:100]
                order.save(update_fields=["status", "provider_ref"])
                refund_task(order.id)
                logger.info("Reconciled %s %s as %s.", model.__name__, order.reference, status)


