"""Failover provider.

SubHero can run more than one outbound VTU provider at once. The first
reachable and funded provider serves the order; if it cannot, the next one in
the chain is tried.

Two rules keep this safe:

1. Only definitive failures move an order to the next provider. A timeout or a
   5xx might mean the purchase went through upstream, so the failing provider
   is asked for the transaction status before anything else is tried.
2. Every provider is asked for the same logical plan. ``VTUPlan`` stores the
   plan id of each provider under ``provider_plan_ids``, keyed by provider name.
"""

import logging
from decimal import Decimal
from typing import Optional

from apps.vtu.providers.base import (
    CablePlan,
    DataPlan,
    PurchaseResult,
    PurchaseStatus,
    ServiceProduct,
    VTUProvider,
    split_amount,
    to_decimal,
)
from apps.vtu.providers.errors import (
    ProviderAuthError,
    ProviderDeclinedError,
    ProviderError,
    ProviderNotFoundError,
    ProviderPartialDeliveryError,
    ProviderRateLimitedError,
    ProviderTransientError,
    ProviderValidationError,
)

logger = logging.getLogger(__name__)


class _PartialDelivery(Exception):
    """Raised inside a provider call when only part of the value was delivered."""

    def __init__(self, delivered: Decimal, cause: Exception):
        super().__init__(str(cause))
        self.delivered = delivered
        self.cause = cause


class FailoverProvider(VTUProvider):
    """Tries each provider in order until one delivers."""

    name = "failover"

    def __init__(self, providers: list[VTUProvider]):
        self.providers = [provider for provider in providers if provider is not None]
        if not self.providers:
            raise ValueError("FailoverProvider needs at least one provider.")

    @property
    def max_airtime_amount(self) -> Optional[Decimal]:
        """The cap of the provider that is asked first.

        The first provider in the chain serves the order, so its cap is the one
        that matters. Each provider splits the amount by its own cap when it
        actually serves it.
        """
        return self.providers[0].max_airtime_amount

    # ────────────────────────── helpers ──────────────────────────

    def _plan_ids(self, plan_id: str) -> dict:
        """Map provider name -> the plan id that provider understands."""
        from apps.vtu.models import VTUPlan

        mapping: dict = {}
        try:
            plan = VTUPlan.objects.filter(plan_id=plan_id).first()
        except Exception:
            plan = None

        if plan is not None:
            stored = plan.provider_plan_ids or {}
            if isinstance(stored, dict):
                mapping = {str(k): str(v) for k, v in stored.items() if v}

        if not mapping:
            # A plan cached before the provider chain was introduced carries a
            # single id. Every provider gets a chance with it: the ones that do
            # not own the plan reject it and the chain moves on.
            mapping = {provider.name: plan_id for provider in self.providers}
        return mapping

    def _resolved_after_transient(self, provider: VTUProvider, reference: str):
        """
        Ask a provider whether a timed-out purchase actually went through.

        Returns a PurchaseResult when the outcome is known, otherwise None.
        """
        try:
            transaction = provider.get_transaction(reference)
        except Exception:
            return None

        status = str(transaction.get("status") or "").strip().upper()
        provider_ref = str(
            transaction.get("transaction_id")
            or transaction.get("tranxId")
            or transaction.get("transactionID")
            or reference
        )
        message = str(transaction.get("api_response") or "")

        amount_paid = transaction.get("amountPaid")
        if amount_paid is None:
            amount_paid = transaction.get("amount_paid")

        if status == "SUCCESS":
            return PurchaseResult(
                True,
                PurchaseStatus.SUCCESS,
                provider_ref,
                message,
                to_decimal(amount_paid) if amount_paid is not None else None,
            )
        if status == "FAILED":
            return PurchaseResult(
                False,
                PurchaseStatus.FAILED,
                provider_ref,
                message,
                to_decimal(amount_paid) if amount_paid is not None else None,
            )
        return None

    def _run(self, action: str, reference: str, call):
        """
        Run one purchase across the provider chain.

        ``call`` receives a provider and returns a PurchaseResult.
        """
        errors: list[tuple[str, str]] = []

        for provider in self.providers:
            try:
                result = call(provider)
            except ProviderTransientError as exc:
                logger.warning(
                    "%s: %s failed transiently on %s (%s).",
                    action, provider.name, reference, exc,
                )
                settled = self._resolved_after_transient(provider, reference)
                if settled is not None:
                    if settled.status == PurchaseStatus.SUCCESS:
                        return self._tag(settled, provider)
                    errors.append((provider.name, str(exc)))
                    continue
                # Outcome unknown upstream. Do not risk a double delivery.
                raise
            except (ProviderAuthError, ProviderDeclinedError, ProviderValidationError, ProviderNotFoundError) as exc:
                logger.warning(
                    "%s: %s declined on %s (%s). Trying the next provider.",
                    action, provider.name, reference, exc,
                )
                errors.append((provider.name, str(exc)))
                continue
            except ProviderRateLimitedError as exc:
                logger.warning(
                    "%s: %s rate limited on %s (%s). Trying the next provider.",
                    action, provider.name, reference, exc,
                )
                errors.append((provider.name, str(exc)))
                continue

            return self._tag(result, provider)

        detail = "; ".join(f"{name}: {message}" for name, message in errors) or "no provider available"
        raise ProviderDeclinedError(f"No VTU provider could complete the {action}. {detail}")

    @staticmethod
    def _tag(result: PurchaseResult, provider: VTUProvider) -> PurchaseResult:
        """Record which provider served the order."""
        extra = dict(result.extra or {})
        extra["provider"] = provider.name
        return PurchaseResult(
            result.success,
            result.status,
            result.provider_ref,
            result.message,
            result.amount_paid,
            extra,
        )

    # ────────────────────────── catalog ──────────────────────────

    def list_data_plans(self) -> list[DataPlan]:
        return self.providers[0].list_data_plans()

    def list_cable_plans(self) -> list[CablePlan]:
        return self.providers[0].list_cable_plans()

    def list_airtime_products(self) -> list[ServiceProduct]:
        return self.providers[0].list_airtime_products()

    def list_electricity_products(self) -> list[ServiceProduct]:
        return self.providers[0].list_electricity_products()

    def list_exam_products(self) -> list[ServiceProduct]:
        return self.providers[0].list_exam_products()

    def resolve_airtime_product(self, network: str) -> str:
        """Returns the canonical network token; each provider maps it itself."""
        for provider in self.providers:
            try:
                provider.resolve_airtime_product(network)
                return network
            except ProviderError:
                continue
        raise ProviderNotFoundError(f"No VTU provider exposes airtime for network '{network}'.")

    def resolve_cable_product(self, provider: str) -> str:
        return self.providers[0].resolve_cable_product(provider)

    def resolve_electricity_biller(self, biller_code: str) -> str:
        return self.providers[0].resolve_electricity_biller(biller_code)

    # ───────────────────────── purchases ─────────────────────────

    def buy_data(self, plan_id: str, phone: str, reference: str) -> PurchaseResult:
        plan_ids = self._plan_ids(plan_id)

        def call(provider: VTUProvider) -> PurchaseResult:
            provider_plan_id = plan_ids.get(provider.name)
            if not provider_plan_id:
                raise ProviderNotFoundError(
                    f"{provider.name} has no plan id mapped for '{plan_id}'."
                )
            return provider.buy_data(provider_plan_id, phone, reference)

        return self._run("data purchase", reference, call)

    def buy_airtime(self, product: str, phone: str, amount: Decimal, reference: str) -> PurchaseResult:
        """
        Buy airtime, splitting the amount by each provider's own cap.

        A provider that can only take ₦1000 per transaction is given several
        transactions, so the cap never decides whether the whole order fits.
        """
        total_paid = Decimal("0")
        delivered = Decimal("0")
        last_provider_ref = reference

        def call(provider: VTUProvider) -> PurchaseResult:
            nonlocal total_paid, delivered, last_provider_ref

            # Each provider maps the network token to its own product name. A
            # provider that does not carry that network is skipped.
            provider_product = provider.resolve_airtime_product(product)

            chunks = split_amount(amount, provider.max_airtime_amount)
            provider_paid = Decimal("0")
            provider_delivered = Decimal("0")

            for index, chunk in enumerate(chunks):
                chunk_ref = reference if len(chunks) == 1 else f"{reference}-{index + 1}"
                try:
                    result = provider.buy_airtime(provider_product, phone, chunk, chunk_ref)
                except Exception as exc:
                    if provider_delivered > 0:
                        raise _PartialDelivery(provider_delivered, exc) from exc
                    raise

                if result.status in (PurchaseStatus.PENDING, PurchaseStatus.PROCESSING):
                    return result

                provider_delivered += chunk
                if result.amount_paid is not None:
                    provider_paid += result.amount_paid
                if result.provider_ref:
                    last_provider_ref = result.provider_ref

            total_paid = provider_paid
            delivered = provider_delivered
            return PurchaseResult(
                True,
                PurchaseStatus.SUCCESS,
                last_provider_ref,
                "Airtime delivered.",
                provider_paid or None,
            )

        try:
            return self._run("airtime purchase", reference, call)
        except _PartialDelivery as partial:
            raise ProviderPartialDeliveryError(
                f"Only part of the airtime was delivered: {partial.cause}",
                partial.delivered,
            ) from partial.cause

    def validate_cable(self, smartcard: str, provider: str) -> str:
        return self.providers[0].validate_cable(smartcard, provider)

    def buy_cable(self, plan_id: str, smartcard: str, customer_name: str, reference: str) -> PurchaseResult:
        plan_ids = self._plan_ids(plan_id)

        def call(provider: VTUProvider) -> PurchaseResult:
            provider_plan_id = plan_ids.get(provider.name) or plan_id
            return provider.buy_cable(provider_plan_id, smartcard, customer_name, reference)

        return self._run("cable purchase", reference, call)

    def validate_meter(self, meter_number: str, biller_code: str, amount: Decimal, meter_type: str) -> str:
        return self.providers[0].validate_meter(meter_number, biller_code, amount, meter_type)

    def buy_electricity(
        self,
        meter_number: str,
        biller_code: str,
        meter_type: str,
        amount: Decimal,
        customer_name: str,
        address: str,
        reference: str,
    ) -> PurchaseResult:
        def call(provider: VTUProvider) -> PurchaseResult:
            return provider.buy_electricity(
                meter_number, biller_code, meter_type, amount, customer_name, address, reference
            )

        return self._run("electricity purchase", reference, call)

    def buy_exam_pin(self, exam_name: str, quantity: int, reference: str, exam_number: str = "") -> PurchaseResult:
        def call(provider: VTUProvider) -> PurchaseResult:
            return provider.buy_exam_pin(exam_name, quantity, reference, exam_number)

        return self._run("exam pin purchase", reference, call)

    # ────────────────────────── account ──────────────────────────

    def get_wallets(self) -> list[dict]:
        wallets: list[dict] = []
        for provider in self.providers:
            try:
                for wallet in provider.get_wallets():
                    entry = dict(wallet)
                    entry["provider"] = provider.name
                    wallets.append(entry)
            except ProviderError as exc:
                logger.warning("Could not read %s wallet: %s", provider.name, exc)
        return wallets

    def get_balance(self) -> Decimal:
        total = Decimal("0")
        for provider in self.providers:
            try:
                total += provider.get_balance()
            except ProviderError as exc:
                logger.warning("Could not read %s balance: %s", provider.name, exc)
        return total

    def get_transaction(self, transaction_ref: str) -> dict:
        for provider in self.providers:
            try:
                transaction = provider.get_transaction(transaction_ref)
            except ProviderError:
                continue
            if transaction:
                return transaction
        return {}
