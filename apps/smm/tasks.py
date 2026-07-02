import logging
import requests
from decimal import Decimal
from django.db import transaction
from django.conf import settings
from django.utils import timezone
from celery import shared_task
from celery.exceptions import MaxRetriesExceededError

from apps.smm.models import SMMService, SMMOrder
from apps.wallet.models import Wallet, WalletTransaction
from apps.wallet.services import debit_wallet, credit_wallet, InsufficientBalanceError, WalletFrozenError
from apps.notifications.tasks import send_transaction_sms

logger = logging.getLogger(__name__)

@shared_task(bind=True, max_retries=2)
def process_smm_order(self, order_id):
    """
    PRD Section 6.4: Processes a customer SMM order atomically.
    1. Debits the customer's wallet.
    2. Sends the order request to the social booster gateway API.
    3. Handles failure retries and auto-refunds.
    """
    try:
        order = SMMOrder.objects.get(id=order_id)
    except SMMOrder.DoesNotExist:
        logger.error("SMM order not found: %s", order_id)
        return

    if order.status != SMMOrder.Status.PROCESSING:
        logger.warning("SMM order %s is not in PROCESSING state (current status: %s).", order_id, order.status)
        return

    # STEP 2: Call social booster gateway API
    api_key = settings.JAP_API_KEY
    if not api_key:
        logger.warning("Social booster gateway API Key is not configured. Cannot process SMM order %s.", order_id)
        order.status = SMMOrder.Status.FAILED
        order.provider_order_id = "Failed: Gateway not configured"
        order.save(update_fields=["status", "provider_order_id"])
        # Update WalletTransaction to FAILED before triggering refund
        WalletTransaction.objects.filter(reference=order.reference).update(status=WalletTransaction.Status.FAILED)
        refund_smm_order.delay(order_id)
        return

    url = settings.JAP_API_URL
    payload = {
        "key": api_key,
        "action": "add",
        "service": order.service.provider_service_id,
        "link": order.target_url,
        "quantity": order.quantity
    }

    try:
        response = requests.post(url, data=payload, timeout=30)
        
        # Check for bad HTTP status code first
        if response.status_code not in [200, 201]:
            msg = response.text[:150] if response.text else "No response body"
            raise Exception(f"Social booster gateway error [{response.status_code}]: {msg}")
            
        try:
            response_data = response.json()
        except ValueError:
            raise Exception(f"Social booster gateway returned invalid response [{response.status_code}]")

        if "order" in response_data:
            order.provider_order_id = str(response_data["order"])
            order.status = SMMOrder.Status.PROCESSING
            order.save(update_fields=["status", "provider_order_id"])

            # Update SMM transaction to PENDING (awaiting delivery confirmation)
            WalletTransaction.objects.filter(reference=order.reference).update(status=WalletTransaction.Status.PENDING)

            logger.info("SMM order placed successfully via booster gateway: provider_id=%s", order.provider_order_id)
        else:
            # Explicit application error (e.g. bad API key, low balance, invalid service) - fail fast immediately!
            error_msg = response_data.get("error", response_data.get("message", "Gateway declined request"))
            logger.error("SMM order %s encountered definitive gateway application error. Failing immediately. Reason: %s", order_id, error_msg)
            
            order.status = SMMOrder.Status.FAILED
            order.provider_order_id = f"Failed: {error_msg}"[:100]
            order.save(update_fields=["status", "provider_order_id"])
            # Update WalletTransaction to FAILED before triggering refund
            WalletTransaction.objects.filter(reference=order.reference).update(status=WalletTransaction.Status.FAILED)
            refund_smm_order.delay(order_id)
            return

    except (requests.exceptions.Timeout, requests.exceptions.ConnectionError, Exception) as exc:
        exc_str = str(exc)
        is_definitive = any(kw in exc_str for kw in [
            "400", "401", "402", "403", "404", "422", 
            "Unauthorized", "Forbidden", "Insufficient", "wallet", "API Key"
        ])
        
        if is_definitive:
            logger.error("SMM order %s encountered definitive failure. Failing immediately. Reason: %s", order_id, exc_str)
            order.status = SMMOrder.Status.FAILED
            order.provider_order_id = f"Failed: {exc_str}"[:100]
            order.save(update_fields=["status", "provider_order_id"])
            # Update WalletTransaction to FAILED before triggering refund
            WalletTransaction.objects.filter(reference=order.reference).update(status=WalletTransaction.Status.FAILED)
            refund_smm_order.delay(order_id)
            return

        logger.warning("SMM order %s gateway call failed. Retrying... Error: %s", order_id, exc_str)
        try:
            self.retry(exc=exc, countdown=30)
        except MaxRetriesExceededError:
            logger.error("SMM order %s exceeded all retries. Initiating refund.", order_id)
            order.status = SMMOrder.Status.FAILED
            order.provider_order_id = f"Failed: {exc_str}"[:100]
            order.save(update_fields=["status", "provider_order_id"])
            # Update WalletTransaction to FAILED before triggering refund
            WalletTransaction.objects.filter(reference=order.reference).update(status=WalletTransaction.Status.FAILED)
            refund_smm_order.delay(order_id)


@shared_task
def refund_smm_order(order_id):
    """
    Restores the client's debited wallet balance when an SMM order fails permanently.
    """
    try:
        with transaction.atomic():
            order = SMMOrder.objects.select_for_update().get(id=order_id)
            
            # Skip if already refunded
            if order.status == SMMOrder.Status.FAILED and WalletTransaction.objects.filter(reference=f"REFUND-{order.reference}").exists():
                logger.warning("SMM Order %s is already refunded.", order_id)
                return

            wallet = Wallet.objects.select_for_update().get(user=order.user)
            balance_before = wallet.balance
            wallet.balance += order.amount
            wallet.save(update_fields=["balance"])

            order.status = SMMOrder.Status.FAILED
            order.save(update_fields=["status"])

            # Update original SMM debit WalletTransaction to FAILED
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
                description=f"Refund · {order.service.name} (SMM)"
            )

            # Warning Notification
            try:
                from apps.notifications.models import Notification
                reason = "Gateway processing error"
                if order.provider_order_id and order.provider_order_id.startswith("Failed:"):
                    raw_reason = order.provider_order_id.replace("Failed: ", "")
                    # Sanitize any internal provider names from customer-facing messages
                    raw_reason = (
                        raw_reason
                        .replace("JustAnotherPanel", "our booster gateway")
                        .replace("JAP", "our booster gateway")
                        .replace("just-another-panel", "our booster gateway")
                    )
                    reason = raw_reason
                
                Notification.add(
                    user=order.user,
                    title="SMM Order Failed - Refunded",
                    description=f"Your SMM booster request for {order.service.name} failed (Reason: {reason}). ₦{order.amount:,.2f} has been fully refunded.",
                    level="warning"
                )
            except Exception as e:
                logger.error("Notification creation failed: %s", str(e))

            logger.info("SMM Refund success: ₦%s restored to User %s", order.amount, order.user.id)

    except Exception as err:
        logger.exception("SMM Refund execution failure: %s", str(err))
        return

    try:
        send_transaction_sms.delay(
            order.user.phone_number,
            f"SubHero: ₦{order.amount:,.0f} refunded. SMM Order {order.reference} could not be completed."
        )
    except Exception as sms_err:
        logger.error("SMM Refund SMS delivery failed: %s", str(sms_err))


@shared_task
def poll_smm_orders():
    """
    Periodic task running every 30 minutes to check status of running SMM orders.
    Triggers refunds for failed/canceled orders, or updates completed statuses.
    """
    logger.info("SMM orders polling triggered.")
    api_key = settings.JAP_API_KEY
    if not api_key:
        logger.info("Social booster gateway API Key is not set. Skipping SMM polling.")
        return

    processing_orders = SMMOrder.objects.filter(status=SMMOrder.Status.PROCESSING)
    url = settings.JAP_API_URL

    for order in processing_orders:
        if not order.provider_order_id or order.provider_order_id.startswith("MOCK"):
            # Orders with mock IDs were created without a real API key — mark as failed and refund
            logger.warning("SMM order %s has mock provider ID — marking failed and refunding.", order.reference)
            order.status = SMMOrder.Status.FAILED
            order.save(update_fields=["status"])
            refund_smm_order.delay(order.id)
            continue

        try:
            response = requests.post(url, data={
                "key": api_key,
                "action": "status",
                "order": order.provider_order_id
            }, timeout=15)
            data = response.json()

            status = data.get("status")
            if status == "Completed":
                order.status = SMMOrder.Status.SUCCESS
                order.save(update_fields=["status"])
                
                # In-app Success Alert
                try:
                    from apps.notifications.models import Notification
                    Notification.add(
                        user=order.user,
                        title="SMM Order Completed",
                        description=f"Your SMM request for {order.service.name} has been successfully delivered.",
                        level="financial"
                    )
                except Exception as e:
                    logger.error("Notification creation failed: %s", str(e))

                # Send SMS
                send_transaction_sms.delay(
                    order.user.phone_number,
                    f"SubHero: Your SMM order {order.reference} has been completed! Thank you."
                )

            elif status == "Partial":
                remains = data.get("remains", 0)
                try:
                    remains_int = int(remains)
                except ValueError:
                    remains_int = 0

                if remains_int > 0 and remains_int < order.quantity:
                    refund_qty = remains_int
                    refund_amount = (Decimal(refund_qty) / Decimal(order.quantity)) * order.amount

                    # Perform atomic partial refund
                    with transaction.atomic():
                        wallet = Wallet.objects.select_for_update().get(user=order.user)
                        balance_before = wallet.balance
                        wallet.balance += refund_amount
                        wallet.save(update_fields=["balance"])

                        order.status = SMMOrder.Status.PARTIAL
                        order.save(update_fields=["status"])

                        WalletTransaction.objects.create(
                            wallet=wallet,
                            txn_type=WalletTransaction.TxnType.REFUND,
                            amount=refund_amount,
                            balance_before=balance_before,
                            balance_after=wallet.balance,
                            reference=f"PARTIAL-{order.reference}",
                            status=WalletTransaction.Status.SUCCESS,
                            description=f"Partial Refund: {refund_qty} remains for SMM Order {order.reference}"
                        )

                        # In-app Warning Alert
                        try:
                            from apps.notifications.models import Notification
                            Notification.add(
                                user=order.user,
                                title="SMM Order Partially Delivered",
                                description=f"SMM order {order.reference} partially completed. ₦{refund_amount:,.2f} refunded for {refund_qty} undelivered items.",
                                level="warning"
                            )
                        except Exception as e:
                            logger.error("Notification creation failed: %s", str(e))

                    # Send SMS
                    send_transaction_sms.delay(
                        order.user.phone_number,
                        f"SubHero: SMM order partially completed. ₦{refund_amount:,.0f} has been refunded to your wallet."
                    )

            elif status in ["Failed", "Canceled", "Cancelled"]:
                logger.warning("SMM Order %s returned gateway status: %s. Reversing payment.", order.reference, status)
                # Mark transaction as FAILED before refund
                WalletTransaction.objects.filter(reference=order.reference).update(status=WalletTransaction.Status.FAILED)
                refund_smm_order.delay(order.id)

        except Exception as e:
            logger.error("Failed to poll status for SMM Order %s: %s", order.provider_order_id, str(e))


@shared_task
def sync_smm_catalogue():
    """
    Synchronizes active social booster services. Applied daily at 3:00 AM (Celery Beat).
    """
    logger.info("Synchronizing SMM Catalogue from booster gateway...")
    api_key = settings.JAP_API_KEY
    if not api_key:
        # Pre-populate catalogue for local manual developer verification
        pre_populated = [
            # Instagram
            {"service": "1001", "name": "Instagram Followers (Real & Active)", "category": "instagram", "min": "100", "max": "10000", "rate": Decimal("0.80")},
            {"service": "1002", "name": "Instagram Likes (High Quality)", "category": "instagram", "min": "50", "max": "5000", "rate": Decimal("0.20")},
            {"service": "1003", "name": "Instagram Views (Fast delivery)", "category": "instagram", "min": "100", "max": "50000", "rate": Decimal("0.10")},
            # TikTok
            {"service": "2001", "name": "TikTok Followers (Premium)", "category": "tiktok", "min": "100", "max": "20000", "rate": Decimal("1.20")},
            {"service": "2002", "name": "TikTok Likes (Real)", "category": "tiktok", "min": "100", "max": "10000", "rate": Decimal("0.30")},
            {"service": "2003", "name": "TikTok Views (Instant)", "category": "tiktok", "min": "500", "max": "100000", "rate": Decimal("0.05")},
            # YouTube
            {"service": "3001", "name": "YouTube Subscribers (Non-Drop)", "category": "youtube", "min": "50", "max": "5000", "rate": Decimal("8.50")},
            {"service": "3002", "name": "YouTube Likes (Active)", "category": "youtube", "min": "50", "max": "10000", "rate": Decimal("1.50")},
            {"service": "3003", "name": "YouTube Views (High Retention)", "category": "youtube", "min": "100", "max": "100000", "rate": Decimal("1.20")},
            # Twitter
            {"service": "4001", "name": "Twitter Followers (Real Look)", "category": "twitter", "min": "100", "max": "5000", "rate": Decimal("2.50")},
            {"service": "4002", "name": "Twitter Retweets (Instant)", "category": "twitter", "min": "50", "max": "2000", "rate": Decimal("0.90")},
            {"service": "4003", "name": "Twitter Likes (Organic)", "category": "twitter", "min": "50", "max": "5000", "rate": Decimal("0.70")},
            # Telegram
            {"service": "5001", "name": "Telegram Channel Members (Global)", "category": "telegram", "min": "100", "max": "10000", "rate": Decimal("0.60")},
            {"service": "5002", "name": "Telegram Post Views (Instant)", "category": "telegram", "min": "100", "max": "50000", "rate": Decimal("0.05")},
            # Spotify
            {"service": "6001", "name": "Spotify Playlist Followers", "category": "spotify", "min": "100", "max": "20000", "rate": Decimal("0.40")},
            {"service": "6002", "name": "Spotify Song Plays (Premium)", "category": "spotify", "min": "100", "max": "50000", "rate": Decimal("0.30")},
        ]
        from apps.admin_panel.models import SystemSetting
        try:
            smm_margin_pct = Decimal(SystemSetting.get("smm_profit_margin", "50.00"))
        except Exception:
            smm_margin_pct = Decimal("50.00")
        smm_margin = smm_margin_pct / Decimal("100")

        for s in pre_populated:
            # For mock data, rate is already normalized in Naira.
            markup_price = s["rate"] * (Decimal("1") + smm_margin)
            SMMService.objects.update_or_create(
                provider_service_id=s["service"],
                defaults={
                    "name": s["name"],
                    "category": s["category"],
                    "subcategory": s["category"].capitalize() + " Default",
                    "provider_min": int(s["min"]),
                    "provider_max": int(s["max"]),
                    "provider_rate": s["rate"],
                    "subhero_price_per_1k": markup_price,
                    "is_active": True
                }
            )
        logger.info("Mock SMM service catalogue loaded successfully.")
        return

    url = settings.JAP_API_URL
    try:
        response = requests.post(url, data={"key": api_key, "action": "services"}, timeout=30)
        services = response.json()

        count = 0
        for s in services:
            category_lower = s["category"].lower()
            
            # Map JAP categories to our 6 core frontend platform tabs
            platform = "other"
            if "instagram" in category_lower:
                platform = "instagram"
            elif "tiktok" in category_lower:
                platform = "tiktok"
            elif "youtube" in category_lower:
                platform = "youtube"
            elif "twitter" in category_lower or "x.com" in category_lower or "threads" in category_lower:
                platform = "twitter"
            elif "telegram" in category_lower:
                platform = "telegram"
            elif "spotify" in category_lower:
                platform = "spotify"

            # Skip unsupported categories to keep the catalogue curated and high quality
            if platform == "other":
                continue

            rate_usd = Decimal(str(s["rate"]))
            
            # Dynamic USD to Naira exchange rate
            from apps.admin_panel.models import AlertConfig, SystemSetting
            alert_config = AlertConfig.objects.first()
            usd_rate = alert_config.usd_ngn_rate if alert_config else Decimal("1600.00")
            provider_rate_naira = rate_usd * usd_rate
            
            # Dynamic SMM profit markup
            try:
                smm_margin_pct = Decimal(SystemSetting.get("smm_profit_margin", "50.00"))
            except Exception:
                smm_margin_pct = Decimal("50.00")
            smm_margin = smm_margin_pct / Decimal("100")
            
            subhero_price = provider_rate_naira * (Decimal("1") + smm_margin)

            SMMService.objects.update_or_create(
                provider_service_id=str(s["service"]),
                defaults={
                    "name": s["name"],
                    "category": platform,
                    "subcategory": s.get("category", "").strip(),
                    "provider_min": int(s["min"]),
                    "provider_max": int(s["max"]),
                    "provider_rate": rate_usd,
                    "subhero_price_per_1k": subhero_price,
                    "is_active": True
                }
            )
            count += 1
        logger.info("SMM catalogue synced successfully via booster gateway. Mapped and updated %d services.", count)
    except Exception as e:
        logger.error("Failed to sync SMM catalogue from booster gateway: %s", str(e))
