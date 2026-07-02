"""
Admin Panel — Signals
====================
Centralized instrumentation listening to system events and registering syslog logs.
"""

from django.db.models.signals import post_save
from django.dispatch import receiver
from django.contrib.auth import get_user_model
from django.contrib.auth.signals import user_logged_in, user_login_failed

from apps.admin_panel.utils import syslog
from apps.wallet.models import WalletTransaction
from apps.vtu.models import VTUOrder, AirtimeOrder, CableOrder, ElectricityOrder, ExamPinOrder
from apps.smm.models import SMMOrder

User = get_user_model()


# ─────────────────────────────────────────────────────────────
# AUTHENTICATION LOGGING
# ─────────────────────────────────────────────────────────────

@receiver(post_save, sender=User)
def log_user_registration(sender, instance, created, **kwargs):
    if created:
        syslog(
            level="INFO",
            category="AUTH",
            message=f"New user registered: {instance.full_name} ({instance.phone_number})",
            user_id=str(instance.id)
        )


@receiver(user_logged_in)
def log_user_login(sender, request, user, **kwargs):
    syslog(
        level="INFO",
        category="AUTH",
        message=f"User logged in successfully: {user.phone_number} ({user.email})",
        user_id=str(user.id),
        ip=request.META.get("REMOTE_ADDR", "0.0.0.0")
    )


@receiver(user_login_failed)
def log_user_login_failed(sender, credentials, request, **kwargs):
    phone = credentials.get("phone_number", "Unknown")
    syslog(
        level="WARNING",
        category="AUTH",
        message=f"Failed login attempt for phone: {phone}",
        ip=request.META.get("REMOTE_ADDR", "0.0.0.0") if request else "0.0.0.0"
    )


# ─────────────────────────────────────────────────────────────
# WALLET & TRANSACTIONS LOGGING
# ─────────────────────────────────────────────────────────────

@receiver(post_save, sender=WalletTransaction)
def log_wallet_transaction(sender, instance, created, **kwargs):
    # Only log significant state transitions or creation
    user = instance.wallet.user if instance.wallet else None
    user_identifier = user.phone_number if user else "System"
    
    if created:
        syslog(
            level="INFO",
            category="PAYMENT",
            message=f"Transaction created: {instance.get_txn_type_display()} | Ref: {instance.reference} | User: {user_identifier} | Amount: ₦{instance.amount}",
            reference=instance.reference,
            status=instance.status
        )
    else:
        # State transition update
        level = "INFO"
        if instance.status == WalletTransaction.Status.FAILED:
            level = "ERROR"
        syslog(
            level=level,
            category="PAYMENT",
            message=f"Transaction updated: {instance.reference} | Status: {instance.status} | Final Amount: ₦{instance.amount}",
            reference=instance.reference,
            status=instance.status
        )


# ─────────────────────────────────────────────────────────────
# ORDERS LOGGING (VTU & SMM)
# ─────────────────────────────────────────────────────────────

def log_order_change(order, order_type_label, category):
    level = "INFO"
    if order.status == "FAILED" or order.status == "CANCELLED":
        level = "ERROR"
    elif order.status == "PROCESSING" or order.status == "PENDING":
        level = "INFO"
        
    syslog(
        level=level,
        category=category,
        message=f"Order {order.reference} ({order_type_label}) updated to status: {order.status} | User: {order.user.phone_number}",
        reference=order.reference,
        status=order.status
    )


@receiver(post_save, sender=VTUOrder)
def log_vtu_order(sender, instance, created, **kwargs):
    log_order_change(instance, "VTU Data", "VTU")


@receiver(post_save, sender=AirtimeOrder)
def log_airtime_order(sender, instance, created, **kwargs):
    log_order_change(instance, f"Airtime {instance.network.upper()}", "VTU")


@receiver(post_save, sender=CableOrder)
def log_cable_order(sender, instance, created, **kwargs):
    log_order_change(instance, f"Cable TV ({instance.provider.upper()})", "VTU")


@receiver(post_save, sender=ElectricityOrder)
def log_electricity_order(sender, instance, created, **kwargs):
    log_order_change(instance, f"Electricity ({instance.disco_name})", "VTU")


@receiver(post_save, sender=ExamPinOrder)
def log_exam_pin_order(sender, instance, created, **kwargs):
    log_order_change(instance, f"Exam PIN ({instance.exam_name})", "VTU")


@receiver(post_save, sender=SMMOrder)
def log_smm_order(sender, instance, created, **kwargs):
    log_order_change(instance, "SMM Social Booster", "SMM")
