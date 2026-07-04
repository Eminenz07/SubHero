from decimal import Decimal
import logging
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.cache import cache
from django.db import transaction
from django.shortcuts import render, redirect
from django.views import View

from apps.core.mixins import PinRequiredMixin
from apps.core.utils import get_client_ip, generate_reference, normalize_phone
from apps.wallet.models import Wallet, WalletTransaction
from apps.wallet.services import InsufficientBalanceError, WalletFrozenError
from apps.vtu.models import (
    VTUPlan, VTUOrder,
    AirtimeOrder, AIRTIME_NETWORKS,
    CablePlan, CableOrder,
    ElectricityOrder, DISCO_CHOICES, DISCO_NAMES,
    ExamProduct, ExamPinOrder,
)
from apps.vtu.tasks import (
    process_vtu_order,
    process_airtime_order,
    process_cable_order,
    process_electricity_order,
    process_exam_pin_order,
    sync_cable_plans, sync_exam_products,
    refund_vtu_order, refund_airtime_order,
    refund_cable_order, refund_electricity_order,
    refund_exam_pin_order,
)

logger = logging.getLogger(__name__)


# ────────────────────────────────────────────────────────────
# HELPERS
# ────────────────────────────────────────────────────────────

def _check_pin(request, context, template):
    """Validates PIN with lockout. Returns (ok: bool, response_or_None)."""
    pin_attempts_key = f"pin_attempts:{request.user.id}"
    pin_lockout_key  = f"pin_lockout:{request.user.id}"

    if cache.get(pin_lockout_key):
        lockout_mins = settings.PIN_LOCKOUT_SECONDS // 60
        messages.error(request, f"PIN locked due to too many attempts. Try again in {lockout_mins} minutes.")
        return False, render(request, template, context)

    pin = request.POST.get("pin", "")
    if not request.user.check_pin(pin):
        attempts = cache.get(pin_attempts_key, 0) + 1
        cache.set(pin_attempts_key, attempts, 300)
        if attempts >= 3:
            cache.set(pin_lockout_key, True, settings.PIN_LOCKOUT_SECONDS)
            lockout_mins = settings.PIN_LOCKOUT_SECONDS // 60
            messages.error(request, f"Incorrect PIN. You have been locked out for {lockout_mins} minutes.")
        else:
            messages.error(request, f"Incorrect transaction PIN. {3 - attempts} attempts remaining.")
        return False, render(request, template, context)

    cache.delete(pin_attempts_key)
    return True, None


def _atomic_debit(wallet, amount, reference, txn_type, description, ip, status=WalletTransaction.Status.PENDING):
    """Atomically locks and debits the wallet. Returns (locked_wallet, txn)."""
    locked_wallet = Wallet.objects.select_for_update().get(id=wallet.id)
    if locked_wallet.is_frozen:
        raise WalletFrozenError("Your wallet is frozen. Contact support.")
    if locked_wallet.balance < amount:
        raise InsufficientBalanceError("Insufficient balance")
    balance_before = locked_wallet.balance
    locked_wallet.balance -= amount
    locked_wallet.save(update_fields=["balance"])
    txn = WalletTransaction.objects.create(
        wallet=locked_wallet,
        txn_type=txn_type,
        amount=amount,
        balance_before=balance_before,
        balance_after=locked_wallet.balance,
        reference=reference,
        status=status,
        description=description,
        ip_address=ip,
    )
    return locked_wallet, txn


# ────────────────────────────────────────────────────────────
# DATA
# ────────────────────────────────────────────────────────────

class BuyDataView(LoginRequiredMixin, PinRequiredMixin, View):
    """Buy Mobile Data Package View with active CheapDataHub background integration."""
    template_name = "vtu/data.html"

    def get(self, request, *args, **kwargs):
        wallet, _ = Wallet.objects.get_or_create(user=request.user)
        plans = VTUPlan.objects.filter(is_active=True)
        if not plans.exists():
            from apps.vtu.tasks import sync_vtu_plans
            sync_vtu_plans()
            plans = VTUPlan.objects.filter(is_active=True)

        plans_dict = {p.plan_id: {"name": p.name, "price": p.subhero_price, "validity": p.validity, "network": p.network} for p in plans}
        return render(request, self.template_name, {"wallet": wallet, "plans": plans_dict})

    def post(self, request, *args, **kwargs):
        wallet, _ = Wallet.objects.get_or_create(user=request.user)
        network = request.POST.get("network", "").lower()
        phone_number = request.POST.get("phone_number", "").strip()
        plan_id = request.POST.get("plan_id", "")

        plans = VTUPlan.objects.filter(is_active=True)
        plans_dict = {p.plan_id: {"name": p.name, "price": p.subhero_price, "validity": p.validity, "network": p.network} for p in plans}
        context = {"wallet": wallet, "plans": plans_dict, "form_data": {"network": network, "phone_number": phone_number, "plan_id": plan_id}}

        if not network or not phone_number or not plan_id:
            messages.error(request, "All fields are required.")
            return render(request, self.template_name, context)
        if network not in ["mtn", "airtel", "glo", "9mobile"]:
            messages.error(request, "Invalid network selected.")
            return render(request, self.template_name, context)

        normalized_phone = normalize_phone(phone_number)
        if not normalized_phone.startswith("+234") or len(normalized_phone) != 14:
            messages.error(request, "Please enter a valid 11-digit Nigerian phone number.")
            return render(request, self.template_name, context)

        pin_ok, pin_response = _check_pin(request, context, self.template_name)
        if not pin_ok:
            return pin_response

        try:
            plan = VTUPlan.objects.get(plan_id=plan_id, is_active=True)
        except VTUPlan.DoesNotExist:
            messages.error(request, "Invalid or inactive data plan selected.")
            return render(request, self.template_name, context)

        idempotency_key = f"vtu_idempotency:{request.user.id}:{plan_id}:{normalized_phone}"
        if cache.get(idempotency_key):
            messages.error(request, "Duplicate order detected. Please wait 5 minutes before retrying.")
            return render(request, self.template_name, context)

        reference = generate_reference("VTU")
        try:
            with transaction.atomic():
                locked_wallet, txn = _atomic_debit(
                    wallet, plan.subhero_price, reference,
                    WalletTransaction.TxnType.VTU,
                    f"Mobile Data · {network.upper()} {plan.name} → {phone_number}",
                    get_client_ip(request),
                )
                order = VTUOrder.objects.create(
                    user=request.user, network=network, recipient=phone_number,
                    plan_id=plan_id, plan_name=plan.name, amount=plan.subhero_price,
                    api_cost=plan.provider_price,
                    reference=reference, status=VTUOrder.Status.PROCESSING,
                )

            cache.set(idempotency_key, order.id, 300)
            # Run task synchronously for immediate real-time feedback
            from apps.vtu.tasks import process_vtu_order
            process_vtu_order(order.id)
            order.refresh_from_db()
            txn = WalletTransaction.objects.filter(reference=order.reference).first()
            locked_wallet = Wallet.objects.get(user=request.user)

            return render(request, "vtu/receipt.html", {
                "wallet": locked_wallet, "txn": txn, "order": order,
                "service_type": "data", "network": network,
                "phone_number": phone_number, "plan_name": plan.name,
                "amount": plan.subhero_price, "back_url": "/vtu/data/",
            })
        except InsufficientBalanceError:
            messages.error(request, f"Insufficient balance. You need ₦{plan.subhero_price:,.2f} but your balance is ₦{wallet.balance:,.2f}.")
        except WalletFrozenError:
            messages.error(request, "Your wallet is currently frozen. Please contact support.")
        except Exception:
            logger.exception("VTU data purchase failed")
            # Emergency fallback: if order was created and debited, mark FAILED and refund
            try:
                _order = locals().get('order')
                if _order and _order.pk and _order.status not in (VTUOrder.Status.SUCCESS, VTUOrder.Status.FAILED):
                    _order.status = VTUOrder.Status.FAILED
                    _order.save(update_fields=["status"])
                    WalletTransaction.objects.filter(reference=_order.reference).update(status=WalletTransaction.Status.FAILED)
                    refund_vtu_order(_order.id)
            except Exception as refund_err:
                logger.exception("Emergency VTU refund also failed: %s", refund_err)
            messages.error(request, "Transaction failed. Your wallet has been refunded if any amount was deducted.")
        return render(request, self.template_name, context)


# ────────────────────────────────────────────────────────────
# AIRTIME
# ────────────────────────────────────────────────────────────

class BuyAirtimeView(LoginRequiredMixin, PinRequiredMixin, View):
    """Buy Airtime View — MTN, Airtel, Glo, 9mobile via CheapDataHub."""
    template_name = "vtu/airtime.html"

    def _context(self, request):
        wallet, _ = Wallet.objects.get_or_create(user=request.user)
        return {
            "wallet": wallet,
            "networks": list(AIRTIME_NETWORKS.keys()),
            "amounts": [100, 200, 500, 1000, 2000, 5000]
        }

    def get(self, request, *args, **kwargs):
        return render(request, self.template_name, self._context(request))

    def post(self, request, *args, **kwargs):
        wallet, _ = Wallet.objects.get_or_create(user=request.user)
        network = request.POST.get("network", "").lower()
        phone_number = request.POST.get("phone_number", "").strip()
        amount_str = request.POST.get("amount", "").strip()
        context = {**self._context(request), "form_data": {"network": network, "phone_number": phone_number, "amount": amount_str}}

        if not network or not phone_number or not amount_str:
            messages.error(request, "All fields are required.")
            return render(request, self.template_name, context)

        if network not in AIRTIME_NETWORKS:
            messages.error(request, "Invalid network selected.")
            return render(request, self.template_name, context)

        try:
            amount = Decimal(amount_str)
            if amount < Decimal("100") or amount > Decimal("50000"):
                raise ValueError
        except (ValueError, Exception):
            messages.error(request, "Airtime amount must be between ₦100 and ₦50,000.")
            return render(request, self.template_name, context)

        normalized_phone = normalize_phone(phone_number)
        if not normalized_phone.startswith("+234") or len(normalized_phone) != 14:
            messages.error(request, "Please enter a valid 11-digit Nigerian phone number.")
            return render(request, self.template_name, context)

        pin_ok, pin_response = _check_pin(request, context, self.template_name)
        if not pin_ok:
            return pin_response

        idempotency_key = f"airtime_idem:{request.user.id}:{normalized_phone}:{amount}"
        if cache.get(idempotency_key):
            messages.error(request, "Duplicate order detected. Please wait 5 minutes before retrying.")
            return render(request, self.template_name, context)

        reference = generate_reference("AIR")
        try:
            with transaction.atomic():
                locked_wallet, txn = _atomic_debit(
                    wallet, amount, reference,
                    WalletTransaction.TxnType.VTU,
                    f"Airtime · {network.upper()} ₦{amount:,.0f} → {phone_number}",
                    get_client_ip(request),
                )
                order = AirtimeOrder.objects.create(
                    user=request.user, network=network, recipient=normalized_phone,
                    amount=amount, api_cost=amount, reference=reference, status=AirtimeOrder.Status.PROCESSING,
                )

            cache.set(idempotency_key, order.id, 300)
            # Run task synchronously for immediate real-time feedback
            from apps.vtu.tasks import process_airtime_order
            process_airtime_order(str(order.id))
            order.refresh_from_db()
            txn = WalletTransaction.objects.filter(reference=order.reference).first()
            locked_wallet = Wallet.objects.get(user=request.user)

            return render(request, "vtu/receipt.html", {
                "wallet": locked_wallet, "txn": txn, "order": order,
                "service_type": "airtime", "network": network,
                "phone_number": phone_number, "amount": amount,
                "back_url": "/vtu/airtime/",
            })
        except InsufficientBalanceError:
            messages.error(request, f"Insufficient balance. You need ₦{amount:,.2f} but your balance is ₦{wallet.balance:,.2f}.")
        except WalletFrozenError:
            messages.error(request, "Your wallet is currently frozen. Please contact support.")
        except Exception:
            logger.exception("Airtime purchase failed")
            try:
                _order = locals().get('order')
                if _order and _order.pk and _order.status not in (AirtimeOrder.Status.SUCCESS, AirtimeOrder.Status.FAILED):
                    _order.status = AirtimeOrder.Status.FAILED
                    _order.save(update_fields=["status"])
                    WalletTransaction.objects.filter(reference=_order.reference).update(status=WalletTransaction.Status.FAILED)
                    refund_airtime_order(_order.id)
            except Exception as refund_err:
                logger.exception("Emergency Airtime refund also failed: %s", refund_err)
            messages.error(request, "Transaction failed. Your wallet has been refunded if any amount was deducted.")
        return render(request, self.template_name, context)


# ────────────────────────────────────────────────────────────
# CABLE TV
# ────────────────────────────────────────────────────────────

class BuyCableView(LoginRequiredMixin, PinRequiredMixin, View):
    """Cable TV subscription — DStv, GOtv, Startimes via CheapDataHub."""
    template_name = "vtu/cable.html"

    def _get_plans(self):
        plans = CablePlan.objects.filter(is_active=True).order_by("provider", "subhero_price")
        if not plans.exists():
            sync_cable_plans()
            plans = CablePlan.objects.filter(is_active=True).order_by("provider", "subhero_price")
        by_provider = {}
        for p in plans:
            by_provider.setdefault(p.provider, []).append(p)
        return plans, by_provider

    def get(self, request, *args, **kwargs):
        wallet, _ = Wallet.objects.get_or_create(user=request.user)
        _, by_provider = self._get_plans()
        return render(request, self.template_name, {"wallet": wallet, "plans_by_provider": by_provider})

    def post(self, request, *args, **kwargs):
        wallet, _ = Wallet.objects.get_or_create(user=request.user)
        provider = request.POST.get("provider", "").lower()
        plan_id = request.POST.get("plan_id", "")
        card_number = request.POST.get("card_number", "").strip()
        phone_number = request.POST.get("phone_number", "").strip()
        _, by_provider = self._get_plans()
        context = {"wallet": wallet, "plans_by_provider": by_provider, "form_data": {"provider": provider, "plan_id": plan_id, "card_number": card_number, "phone_number": phone_number}}

        if not provider or not plan_id or not card_number or not phone_number:
            messages.error(request, "All fields are required.")
            return render(request, self.template_name, context)

        try:
            plan = CablePlan.objects.get(plan_id=plan_id, provider=provider, is_active=True)
        except CablePlan.DoesNotExist:
            messages.error(request, "Invalid package selected. Please refresh and try again.")
            return render(request, self.template_name, context)

        normalized_phone = normalize_phone(phone_number)
        if not normalized_phone.startswith("+234") or len(normalized_phone) != 14:
            messages.error(request, "Please enter a valid 11-digit Nigerian phone number.")
            return render(request, self.template_name, context)

        pin_ok, pin_response = _check_pin(request, context, self.template_name)
        if not pin_ok:
            return pin_response

        idempotency_key = f"cable_idem:{request.user.id}:{plan_id}:{card_number}"
        if cache.get(idempotency_key):
            messages.error(request, "Duplicate order detected. Please wait 5 minutes before retrying.")
            return render(request, self.template_name, context)

        reference = generate_reference("CBL")
        try:
            with transaction.atomic():
                locked_wallet, txn = _atomic_debit(
                    wallet, plan.subhero_price, reference,
                    WalletTransaction.TxnType.VTU,
                    f"Cable TV · {provider.upper()} {plan.name} → Card {card_number}",
                    get_client_ip(request),
                )
                order = CableOrder.objects.create(
                    user=request.user, provider=provider, plan_id=plan_id,
                    plan_name=plan.name, card_number=card_number, phone=normalized_phone,
                    amount=plan.subhero_price, api_cost=plan.amount, reference=reference, status=CableOrder.Status.PROCESSING,
                )

            cache.set(idempotency_key, order.id, 300)
            # Run task synchronously for immediate real-time feedback
            from apps.vtu.tasks import process_cable_order
            process_cable_order(str(order.id))
            order.refresh_from_db()
            txn = WalletTransaction.objects.filter(reference=order.reference).first()
            locked_wallet = Wallet.objects.get(user=request.user)

            return render(request, "vtu/receipt.html", {
                "wallet": locked_wallet, "txn": txn, "order": order,
                "service_type": "cable", "provider": provider.upper(),
                "plan_name": plan.name, "card_number": card_number,
                "amount": plan.subhero_price, "back_url": "/vtu/cable/",
            })
        except InsufficientBalanceError:
            messages.error(request, f"Insufficient balance. You need ₦{plan.subhero_price:,.2f} but your balance is ₦{wallet.balance:,.2f}.")
        except WalletFrozenError:
            messages.error(request, "Your wallet is currently frozen. Please contact support.")
        except Exception:
            logger.exception("Cable TV purchase failed")
            try:
                _order = locals().get('order')
                if _order and _order.pk and _order.status not in (CableOrder.Status.SUCCESS, CableOrder.Status.FAILED):
                    _order.status = CableOrder.Status.FAILED
                    _order.save(update_fields=["status"])
                    WalletTransaction.objects.filter(reference=_order.reference).update(status=WalletTransaction.Status.FAILED)
                    refund_cable_order(_order.id)
            except Exception as refund_err:
                logger.exception("Emergency Cable refund also failed: %s", refund_err)
            messages.error(request, "Transaction failed. Your wallet has been refunded if any amount was deducted.")
        return render(request, self.template_name, context)


# ────────────────────────────────────────────────────────────
# ELECTRICITY
# ────────────────────────────────────────────────────────────

class BuyElectricityView(LoginRequiredMixin, PinRequiredMixin, View):
    """Electricity token vending — all major DISCOs via CheapDataHub."""
    template_name = "vtu/electricity.html"

    def get(self, request, *args, **kwargs):
        wallet, _ = Wallet.objects.get_or_create(user=request.user)
        return render(request, self.template_name, {
            "wallet": wallet,
            "discos": DISCO_CHOICES,
            "amounts": [500, 1000, 2000, 5000, 10000]
        })

    def post(self, request, *args, **kwargs):
        wallet, _ = Wallet.objects.get_or_create(user=request.user)
        disco_id = request.POST.get("disco_id", "").strip()
        meter_number = request.POST.get("meter_number", "").strip()
        meter_type = request.POST.get("meter_type", "").lower()
        phone_number = request.POST.get("phone_number", "").strip()
        amount_str = request.POST.get("amount", "").strip()
        context = {
            "wallet": wallet,
            "discos": DISCO_CHOICES,
            "amounts": [500, 1000, 2000, 5000, 10000],
            "form_data": {
                "disco_id": disco_id,
                "meter_number": meter_number,
                "meter_type": meter_type,
                "phone_number": phone_number,
                "amount": amount_str
            }
        }

        if not disco_id or not meter_number or not meter_type or not phone_number or not amount_str:
            messages.error(request, "All fields are required.")
            return render(request, self.template_name, context)

        disco_name = DISCO_NAMES.get(disco_id)
        if not disco_name:
            messages.error(request, "Invalid distribution company selected.")
            return render(request, self.template_name, context)

        if meter_type not in ["prepaid", "postpaid"]:
            messages.error(request, "Invalid meter type. Must be prepaid or postpaid.")
            return render(request, self.template_name, context)

        try:
            amount = Decimal(amount_str)
            if amount < Decimal("500") or amount > Decimal("100000"):
                raise ValueError
        except (ValueError, Exception):
            messages.error(request, "Amount must be between ₦500 and ₦100,000.")
            return render(request, self.template_name, context)

        if not meter_number.isdigit() or not (11 <= len(meter_number) <= 13):
            messages.error(request, "Please enter a valid meter number (11–13 digits).")
            return render(request, self.template_name, context)

        normalized_phone = normalize_phone(phone_number)
        if not normalized_phone.startswith("+234") or len(normalized_phone) != 14:
            messages.error(request, "Please enter a valid 11-digit Nigerian phone number.")
            return render(request, self.template_name, context)

        pin_ok, pin_response = _check_pin(request, context, self.template_name)
        if not pin_ok:
            return pin_response

        idempotency_key = f"elec_idem:{request.user.id}:{meter_number}:{amount}"
        if cache.get(idempotency_key):
            messages.error(request, "Duplicate order detected. Please wait 5 minutes before retrying.")
            return render(request, self.template_name, context)

        reference = generate_reference("ELEC")
        try:
            with transaction.atomic():
                locked_wallet, txn = _atomic_debit(
                    wallet, amount, reference,
                    WalletTransaction.TxnType.VTU,
                    f"Electricity · {disco_name} {meter_type.capitalize()} Token → Meter {meter_number}",
                    get_client_ip(request),
                )
                order = ElectricityOrder.objects.create(
                    user=request.user, disco_id=disco_id, disco_name=disco_name,
                    meter_number=meter_number, meter_type=meter_type,
                    phone=normalized_phone, amount=amount, api_cost=amount, reference=reference,
                    status=ElectricityOrder.Status.PROCESSING,
                )

            cache.set(idempotency_key, order.id, 300)
            # Run task synchronously for immediate real-time feedback
            from apps.vtu.tasks import process_electricity_order
            process_electricity_order(str(order.id))
            order.refresh_from_db()
            txn = WalletTransaction.objects.filter(reference=order.reference).first()
            locked_wallet = Wallet.objects.get(user=request.user)

            return render(request, "vtu/receipt.html", {
                "wallet": locked_wallet, "txn": txn, "order": order,
                "service_type": "electricity", "disco_name": disco_name,
                "meter_number": meter_number, "meter_type": meter_type,
                "amount": amount, "back_url": "/vtu/electricity/",
            })
        except InsufficientBalanceError:
            messages.error(request, f"Insufficient balance. You need ₦{amount:,.2f} but your balance is ₦{wallet.balance:,.2f}.")
        except WalletFrozenError:
            messages.error(request, "Your wallet is currently frozen. Please contact support.")
        except Exception:
            logger.exception("Electricity purchase failed")
            try:
                _order = locals().get('order')
                if _order and _order.pk and _order.status not in (ElectricityOrder.Status.SUCCESS, ElectricityOrder.Status.FAILED):
                    _order.status = ElectricityOrder.Status.FAILED
                    _order.save(update_fields=["status"])
                    WalletTransaction.objects.filter(reference=_order.reference).update(status=WalletTransaction.Status.FAILED)
                    refund_electricity_order(_order.id)
            except Exception as refund_err:
                logger.exception("Emergency Electricity refund also failed: %s", refund_err)
            messages.error(request, "Transaction failed. Your wallet has been refunded if any amount was deducted.")
        return render(request, self.template_name, context)


# ────────────────────────────────────────────────────────────
# EXAM PINS
# ────────────────────────────────────────────────────────────

class BuyExamPinView(LoginRequiredMixin, PinRequiredMixin, View):
    """Exam PIN purchase — WAEC, NECO, NABTEB via CheapDataHub."""
    template_name = "vtu/exam_pin.html"

    def _get_products(self):
        products = ExamProduct.objects.filter(is_active=True)
        if not products.exists():
            sync_exam_products()
            products = ExamProduct.objects.filter(is_active=True)
        return products

    def get(self, request, *args, **kwargs):
        wallet, _ = Wallet.objects.get_or_create(user=request.user)
        return render(request, self.template_name, {
            "wallet": wallet,
            "products": self._get_products(),
            "quantity_choices": ExamPinOrder.QUANTITY_CHOICES,
        })

    def post(self, request, *args, **kwargs):
        wallet, _ = Wallet.objects.get_or_create(user=request.user)
        product_id = request.POST.get("product_id", "")
        quantity_str = request.POST.get("quantity", "1")
        context = {"wallet": wallet, "products": self._get_products(), "quantity_choices": ExamPinOrder.QUANTITY_CHOICES, "form_data": {"product_id": product_id, "quantity": quantity_str}}

        try:
            product = ExamProduct.objects.get(product_id=product_id, is_active=True)
        except ExamProduct.DoesNotExist:
            messages.error(request, "Invalid exam product selected.")
            return render(request, self.template_name, context)

        try:
            quantity = int(quantity_str)
            valid_qtys = [q[0] for q in ExamPinOrder.QUANTITY_CHOICES]
            if quantity not in valid_qtys:
                raise ValueError
        except (ValueError, Exception):
            messages.error(request, f"Invalid quantity. Choose from: {', '.join(str(q) for q in [q[0] for q in ExamPinOrder.QUANTITY_CHOICES])}.")
            return render(request, self.template_name, context)

        total = product.subhero_price_per_pin * quantity

        pin_ok, pin_response = _check_pin(request, context, self.template_name)
        if not pin_ok:
            return pin_response

        idempotency_key = f"exam_idem:{request.user.id}:{product_id}:{quantity}"
        if cache.get(idempotency_key):
            messages.error(request, "Duplicate order detected. Please wait 5 minutes before retrying.")
            return render(request, self.template_name, context)

        reference = generate_reference("EXAM")
        try:
            with transaction.atomic():
                locked_wallet, txn = _atomic_debit(
                    wallet, total, reference,
                    WalletTransaction.TxnType.VTU,
                    f"Exam PIN · {product.exam_name} ×{quantity}",
                    get_client_ip(request),
                )
                order = ExamPinOrder.objects.create(
                    user=request.user, product_id=product_id, exam_name=product.exam_name,
                    quantity=quantity, amount=total, api_cost=product.price_per_pin * quantity, reference=reference,
                    status=ExamPinOrder.Status.PROCESSING,
                )

            cache.set(idempotency_key, order.id, 300)
            # Run task synchronously for immediate real-time feedback
            from apps.vtu.tasks import process_exam_pin_order
            process_exam_pin_order(str(order.id))
            order.refresh_from_db()
            txn = WalletTransaction.objects.filter(reference=order.reference).first()
            locked_wallet = Wallet.objects.get(user=request.user)

            return render(request, "vtu/receipt.html", {
                "wallet": locked_wallet, "txn": txn, "order": order,
                "service_type": "exam_pin", "exam_name": product.exam_name,
                "quantity": quantity, "amount": total,
                "pins": order.get_pins_list(),
                "back_url": "/vtu/exam-pin/",
            })
        except InsufficientBalanceError:
            messages.error(request, f"Insufficient balance. You need ₦{total:,.2f} but your balance is ₦{wallet.balance:,.2f}.")
        except WalletFrozenError:
            messages.error(request, "Your wallet is currently frozen. Please contact support.")
        except Exception:
            logger.exception("Exam PIN purchase failed")
            try:
                _order = locals().get('order')
                if _order and _order.pk and _order.status not in (ExamPinOrder.Status.SUCCESS, ExamPinOrder.Status.FAILED):
                    _order.status = ExamPinOrder.Status.FAILED
                    _order.save(update_fields=["status"])
                    WalletTransaction.objects.filter(reference=_order.reference).update(status=WalletTransaction.Status.FAILED)
                    refund_exam_pin_order(_order.id)
            except Exception as refund_err:
                logger.exception("Emergency Exam PIN refund also failed: %s", refund_err)
            messages.error(request, "Transaction failed. Your wallet has been refunded if any amount was deducted.")
        return render(request, self.template_name, context)


# ────────────────────────────────────────────────────────────
# AJAX — PLANS ENDPOINTS
# ────────────────────────────────────────────────────────────

class VtuPlansAjaxView(LoginRequiredMixin, View):
    """Returns network-filtered plan cards grouped by category as HTML partial."""
    template_name = "vtu/partials/_plan_cards.html"

    # Define canonical category order per network
    CATEGORY_ORDER = {
        "mtn":     ["SME", "SME2", "SMART", "DATA"],
        "airtel":  ["CG", "SMART", "DATA"],
        "glo":     ["CG", "AWOOF", "DATA"],
        "9mobile": ["CG", "DATA"],
    }

    def get(self, request, *args, **kwargs):
        network = request.GET.get("network", "").lower()
        plans = VTUPlan.objects.filter(network=network, is_active=True).order_by("plan_type", "subhero_price")

        # Group plans by plan_type preserving canonical order
        order = self.CATEGORY_ORDER.get(network, [])
        grouped = {}
        for plan in plans:
            pt = plan.plan_type or "DATA"
            if pt not in grouped:
                grouped[pt] = []
            grouped[pt].append(plan)

        # Sort categories: known order first, then any extras alphabetically
        def cat_sort_key(cat):
            try:
                return (0, order.index(cat))
            except ValueError:
                return (1, cat)

        sorted_groups = sorted(grouped.items(), key=lambda x: cat_sort_key(x[0]))

        return render(request, self.template_name, {
            "grouped_plans": sorted_groups,
            "network": network,
        })


class CablePlansAjaxView(LoginRequiredMixin, View):
    """Returns provider-filtered cable plan options as HTML partial."""
    def get(self, request, *args, **kwargs):
        import json
        provider = request.GET.get("provider", "").lower()
        plans = list(CablePlan.objects.filter(provider=provider, is_active=True).order_by("subhero_price").values("plan_id", "name", "subhero_price"))
        from django.http import JsonResponse
        return JsonResponse({"plans": plans})


class ReceiptStatusAjaxView(LoginRequiredMixin, View):
    """
    HTMX status polling endpoint for VTU receipts.
    Checks the background database state of the specified order type.
    """
    template_name = "vtu/partials/_receipt_content.html"

    def get(self, request, order_type, order_id, *args, **kwargs):
        from django.shortcuts import get_object_or_404
        from apps.vtu.models import VTUOrder, AirtimeOrder, CableOrder, ElectricityOrder, ExamPinOrder

        order = None
        if order_type == 'data':
            order = get_object_or_404(VTUOrder, id=order_id, user=request.user)
        elif order_type == 'airtime':
            order = get_object_or_404(AirtimeOrder, id=order_id, user=request.user)
        elif order_type == 'cable':
            order = get_object_or_404(CableOrder, id=order_id, user=request.user)
        elif order_type == 'electricity':
            order = get_object_or_404(ElectricityOrder, id=order_id, user=request.user)
        elif order_type == 'exam_pin':
            order = get_object_or_404(ExamPinOrder, id=order_id, user=request.user)
        else:
            from django.http import Http404
            raise Http404("Invalid order type")

        wallet, _ = Wallet.objects.get_or_create(user=request.user)
        txn = WalletTransaction.objects.filter(reference=order.reference).first()

        context = {
            "wallet": wallet,
            "txn": txn,
            "order": order,
            "service_type": order_type,
            "amount": order.amount,
            "back_url": f"/vtu/{order_type}/",
        }

        if order_type == 'data':
            context.update({
                "network": order.network,
                "phone_number": order.recipient,
                "plan_name": order.plan_name,
            })
        elif order_type == 'airtime':
            context.update({
                "network": order.network,
                "phone_number": order.recipient,
            })
        elif order_type == 'cable':
            context.update({
                "provider": order.provider.upper(),
                "plan_name": order.plan_name,
                "card_number": order.smartcard_number if hasattr(order, 'smartcard_number') else getattr(order, 'card_number', ''),
            })
        elif order_type == 'electricity':
            context.update({
                "disco_name": order.disco_name,
                "meter_number": order.meter_number,
                "meter_type": order.meter_type,
            })
        elif order_type == 'exam_pin':
            context.update({
                "exam_name": order.exam_name,
                "quantity": order.quantity,
                "pins": order.get_pins_list(),
            })

        return render(request, self.template_name, context)


class VerifyUtilityAjaxView(LoginRequiredMixin, View):
    """
    AJAX view to verify electricity meter numbers and cable TV smartcard numbers.
    Provides standard fallback verification if API returns 404 or offline.
    """
    def get(self, request, *args, **kwargs):
        from django.http import JsonResponse
        import requests
        
        action = request.GET.get("action", "").strip().lower()
        
        if action == "electricity":
            disco_id = request.GET.get("disco_id", "").strip()
            number = request.GET.get("number", "").strip()
            meter_type = request.GET.get("meter_type", "prepaid").strip().lower()
            
            if not disco_id or not number:
                return JsonResponse({"status": "error", "message": "Distribution Company and Meter Number are required."})
            
            disco_name = DISCO_NAMES.get(disco_id, "Unknown DisCo")
            
            # Format validation (11 to 13 digits)
            if not number.isdigit() or not (11 <= len(number) <= 13):
                return JsonResponse({"status": "error", "message": "Invalid meter number format (11-13 digits required)."})
                
            return JsonResponse({
                "status": "success",
                "customer_name": f"Format Valid — Confirmed on delivery ({disco_name} {meter_type.upper()})"
            })
                
        elif action == "cable":
            provider = request.GET.get("provider", "").strip().lower()
            number = request.GET.get("number", "").strip()
            
            if not provider or not number:
                return JsonResponse({"status": "error", "message": "Provider and Smart Card number are required."})
            
            # Format validation (10 or 11 digits)
            if not number.isdigit() or not (10 <= len(number) <= 11):
                return JsonResponse({"status": "error", "message": "Invalid Smartcard number format (10-11 digits)."})
                
            return JsonResponse({
                "status": "success",
                "customer_name": f"Format Valid — Confirmed on delivery ({provider.upper()} Decoder)"
            })
                
        else:
            return JsonResponse({"status": "error", "message": "Invalid action specified."})



