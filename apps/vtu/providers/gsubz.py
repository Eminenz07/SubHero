"""GSUBZ provider adapter (https://api.gsubz.com).

Covers data and airtime, which are the services SubHero has switched on.
Cable, electricity and exam pins are deliberately not implemented: those
services are still behind the "Soon" badge.
"""

import logging
from decimal import Decimal
from typing import Optional

import requests
from django.conf import settings

from apps.vtu.providers.base import (
    CablePlan,
    DataPlan,
    PurchaseResult,
    PurchaseStatus,
    ServiceProduct,
    VTUProvider,
    to_decimal,
)
from apps.vtu.providers.errors import (
    ProviderAuthError,
    ProviderDeclinedError,
    ProviderError,
    ProviderNotFoundError,
    ProviderRateLimitedError,
    ProviderTransientError,
    ProviderValidationError,
)

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://api.gsubz.com"
DEFAULT_TIMEOUT = 60

# Data service IDs exposed by GSUBZ. The catalogue is fetched per service.
DATA_SERVICE_IDS = (
    "mtn_gifting",
    "mtn_sme",
    "airtel_gifting",
    "airtel_sme",
    "glo_data",
    "glo_sme",
    "mtn_datashare",
)

# Airtime service IDs. GSUBZ spells 9mobile "etisalat".
AIRTIME_SERVICE_IDS = {
    "mtn": "mtn",
    "airtel": "airtel",
    "glo": "glo",
    "9mobile": "etisalat",
    "etisalat": "etisalat",
}

# Description -> provider error mapping for failed responses.
_DECLINE_DESCRIPTIONS = {
    "INSUFFICIENT_BALANCE",
    "ORDER_FAILED",
    "SERVICE_DISABLED",
    "ACCOUNT_BLOCKED",
}
_AUTH_DESCRIPTIONS = {"INVALID_API_OR_NOT_FOUND"}
_VALIDATION_DESCRIPTIONS = {
    "INVALID_CONTENT",
    "INVALID_PLAN",
    "REQUIRED_CONTENT_NOT_SENT",
    "CONTENT_NOT_FOUND",
    "REQUIRED_CONTENT_REQUESTID_IS_EMPTY",
    "REQUEST_METHOD_NOT_IN_POST",
    "BELOW_MINIMUM_ORDER",
    "REGION_MISMATCH",
}
_RATE_LIMIT_DESCRIPTIONS = {"TOO_MANY_REQUESTS"}
_TRANSIENT_DESCRIPTIONS = {
    "GATEWAY_ERROR",
    "SERVER_ERROR",
    "REQUEST_IN_PROGRESS",
}
# The account has not been upgraded for API purchases. Nothing the request does
# can change this, so another provider has to serve the order.
_NOT_UPGRADED_MARKER = "GET UPGRADED"


class GsubzProvider(VTUProvider):
    """GSUBZ merchant API adapter."""

    name = "gsubz"
    max_airtime_amount = None

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: Optional[int] = None,
    ):
        self.api_key = api_key if api_key is not None else getattr(settings, "GSUBZ_API_KEY", "")
        self.base_url = (
            base_url if base_url is not None else getattr(settings, "GSUBZ_BASE_URL", DEFAULT_BASE_URL)
        ).rstrip("/")
        self.timeout = timeout if timeout is not None else getattr(settings, "GSUBZ_TIMEOUT", DEFAULT_TIMEOUT)

    # ─────────────────────────── HTTP ───────────────────────────

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
        }

    def _url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    def _request(
        self,
        method: str,
        path: str,
        data: Optional[dict] = None,
        params: Optional[dict] = None,
        allow_not_found: bool = False,
    ):
        if not self.api_key:
            raise ProviderAuthError("GSUBZ_API_KEY is not configured on this environment.")

        try:
            response = requests.request(
                method,
                self._url(path),
                headers=self._headers(),
                data=data,
                params=params,
                timeout=self.timeout,
            )
        except requests.exceptions.Timeout as exc:
            raise ProviderTransientError(f"GSUBZ timed out on {path}.") from exc
        except requests.exceptions.RequestException as exc:
            raise ProviderTransientError(f"GSUBZ connection error on {path}: {exc}") from exc

        return self._handle(response, path, allow_not_found=allow_not_found)

    def _handle(self, response, path: str, allow_not_found: bool = False) -> dict:
        try:
            body = response.json()
        except ValueError as exc:
            raise ProviderTransientError(
                f"GSUBZ returned a non-JSON response [{response.status_code}] on {path}."
            ) from exc

        if not isinstance(body, dict):
            raise ProviderTransientError(f"GSUBZ returned an unexpected payload shape on {path}.")

        http_status = response.status_code
        description = str(body.get("description") or "").strip().upper()
        message = str(
            body.get("api_response") or body.get("message") or description or f"HTTP {http_status}"
        ).strip()

        # GSUBZ reports the outcome in `description` and `status`, not only in
        # the HTTP code, and a 200 can still be a failed transaction.
        body_status = str(body.get("status") or "").strip().lower()

        # A repeated requestID is refused but carries the original result.
        if description == "INVALID_ARGUMENTS_DUPLICATE_REQUEST_ID":
            return body

        if _NOT_UPGRADED_MARKER in description:
            raise ProviderAuthError(
                "GSUBZ has not enabled API purchases on this account yet."
            )
        if description in _AUTH_DESCRIPTIONS:
            raise ProviderAuthError(f"GSUBZ rejected access to {path}: {message}")
        if description in _RATE_LIMIT_DESCRIPTIONS:
            raise ProviderRateLimitedError(f"GSUBZ rate limit reached on {path}: {message}")
        if description in _VALIDATION_DESCRIPTIONS or description.startswith("CONTENT_NOT_FOUND"):
            if allow_not_found and description.startswith("CONTENT_NOT_FOUND"):
                return body
            raise ProviderValidationError(f"GSUBZ rejected the {path} request: {message}")
        if description in _DECLINE_DESCRIPTIONS:
            raise ProviderDeclinedError(f"GSUBZ declined the {path} request: {message}")
        if description in _TRANSIENT_DESCRIPTIONS:
            raise ProviderTransientError(f"GSUBZ server error on {path}: {message}")

        if http_status in (401, 403):
            raise ProviderAuthError(f"GSUBZ rejected access to {path}: {message}")
        if http_status == 429:
            raise ProviderRateLimitedError(f"GSUBZ rate limit reached on {path}: {message}")
        if http_status in (400, 404, 405, 422):
            if allow_not_found and http_status == 404:
                return body
            raise ProviderValidationError(f"GSUBZ rejected the {path} request: {message}")
        if http_status in (402, 406):
            raise ProviderDeclinedError(f"GSUBZ declined the {path} request: {message}")
        if http_status >= 500:
            raise ProviderTransientError(f"GSUBZ server error [{http_status}] on {path}: {message}")

        if body_status in ("failed", "failure"):
            raise ProviderDeclinedError(f"GSUBZ declined the {path} request: {message}")

        return body

    # ────────────────────────── catalog ──────────────────────────

    def _plans_for(self, service_id: str) -> list[dict]:
        body = self._request("GET", "/api/plans/", params={"service": service_id})
        plans = body.get("plans")
        return [entry for entry in plans if isinstance(entry, dict)] if isinstance(plans, list) else []

    def list_data_plans(self) -> list[DataPlan]:
        out: list[DataPlan] = []
        for service_id in DATA_SERVICE_IDS:
            try:
                entries = self._plans_for(service_id)
            except ProviderError as exc:
                logger.warning("GSUBZ plan list failed for %s: %s", service_id, exc)
                continue

            for entry in entries:
                value = str(entry.get("value") or "").strip()
                if not value:
                    continue
                display_name = str(entry.get("displayName") or value).strip()
                size, validity = _split_display_name(display_name)
                out.append(
                    DataPlan(
                        plan_id=f"{service_id}:{value}",
                        name=display_name,
                        provider_product=service_id,
                        price=to_decimal(entry.get("api_price") or entry.get("price")),
                        validity=validity,
                        size=size,
                    )
                )
        return out

    def list_airtime_products(self) -> list[ServiceProduct]:
        return [
            ServiceProduct(product_id=service_id, name=service_id, price=Decimal("0"))
            for service_id in sorted(set(AIRTIME_SERVICE_IDS.values()))
        ]

    def list_cable_plans(self) -> list[CablePlan]:
        raise ProviderNotFoundError("GSUBZ cable subscriptions are not enabled on SubHero yet.")

    def list_electricity_products(self) -> list[ServiceProduct]:
        raise ProviderNotFoundError("GSUBZ electricity is not enabled on SubHero yet.")

    def list_exam_products(self) -> list[ServiceProduct]:
        raise ProviderNotFoundError("GSUBZ exam pins are not enabled on SubHero yet.")

    def resolve_airtime_product(self, network: str) -> str:
        target = (network or "").strip().lower()
        service_id = AIRTIME_SERVICE_IDS.get(target)
        if not service_id:
            raise ProviderNotFoundError(f"GSUBZ exposes no airtime product for network '{network}'.")
        return service_id

    def resolve_cable_product(self, provider: str) -> str:
        raise ProviderNotFoundError("GSUBZ cable subscriptions are not enabled on SubHero yet.")

    def resolve_electricity_biller(self, biller_code: str) -> str:
        raise ProviderNotFoundError("GSUBZ electricity is not enabled on SubHero yet.")

    # ───────────────────────── purchases ─────────────────────────

    def _purchase_result(self, body: dict, fallback_ref: str = "") -> PurchaseResult:
        status = str(body.get("status") or "").strip().lower()
        description = str(body.get("description") or "").strip().upper()
        message = str(body.get("api_response") or body.get("message") or "").strip()

        provider_ref = str(
            body.get("transactionID")
            or body.get("transaction_id")
            or body.get("requestID")
            or fallback_ref
            or ""
        )

        amount_paid = None
        if body.get("amountPaid") is not None:
            amount_paid = to_decimal(body.get("amountPaid"))

        if status in ("successful", "success"):
            extra: dict = {}
            if body.get("token"):
                extra["token"] = str(body.get("token"))
            if body.get("api_response"):
                extra["api_response"] = message
            return PurchaseResult(True, PurchaseStatus.SUCCESS, provider_ref, message, amount_paid, extra)

        if status in ("pending", "processing"):
            return PurchaseResult(False, PurchaseStatus.PROCESSING, provider_ref, message, amount_paid)

        if description in _AUTH_DESCRIPTIONS:
            raise ProviderAuthError(message or "GSUBZ rejected the API key.")
        if description in _RATE_LIMIT_DESCRIPTIONS:
            raise ProviderRateLimitedError(message or "GSUBZ rate limit reached.")
        if description in _VALIDATION_DESCRIPTIONS:
            raise ProviderValidationError(message or f"GSUBZ rejected the request ({description}).")
        if description in _DECLINE_DESCRIPTIONS:
            raise ProviderDeclinedError(message or f"GSUBZ declined the request ({description}).")

        raise ProviderDeclinedError(message or f"GSUBZ transaction ended with status {status or 'unknown'}.")

    def buy_data(self, plan_id: str, phone: str, reference: str) -> PurchaseResult:
        service_id, _, value = str(plan_id).partition(":")
        if not service_id or not value:
            raise ProviderValidationError(f"GSUBZ data plan '{plan_id}' is malformed.")

        body = self._request(
            "POST",
            "/api/pay/",
            data={
                "serviceID": service_id,
                "plan": value,
                "api": self.api_key,
                "amount": "",
                "phone": phone,
                "requestID": reference,
            },
        )
        return self._purchase_result(body, reference)

    def buy_airtime(self, product: str, phone: str, amount: Decimal, reference: str) -> PurchaseResult:
        body = self._request(
            "POST",
            "/api/pay/",
            data={
                "serviceID": product,
                "api": self.api_key,
                "amount": str(int(amount)) if amount == amount.to_integral_value() else str(amount),
                "phone": phone,
                "requestID": reference,
            },
        )
        return self._purchase_result(body, reference)

    def validate_cable(self, smartcard: str, provider: str) -> str:
        raise ProviderNotFoundError("GSUBZ cable subscriptions are not enabled on SubHero yet.")

    def buy_cable(self, plan_id: str, smartcard: str, customer_name: str, reference: str) -> PurchaseResult:
        raise ProviderNotFoundError("GSUBZ cable subscriptions are not enabled on SubHero yet.")

    def validate_meter(self, meter_number: str, biller_code: str, amount: Decimal, meter_type: str) -> str:
        raise ProviderNotFoundError("GSUBZ electricity is not enabled on SubHero yet.")

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
        raise ProviderNotFoundError("GSUBZ electricity is not enabled on SubHero yet.")

    def buy_exam_pin(self, exam_name: str, quantity: int, reference: str, exam_number: str = "") -> PurchaseResult:
        raise ProviderNotFoundError("GSUBZ exam pins are not enabled on SubHero yet.")

    # ────────────────────────── account ──────────────────────────

    def get_wallets(self) -> list[dict]:
        body = self._request("POST", "/api/balance/", data={"api": self.api_key})
        balance = to_decimal(body.get("balance"))
        return [{"wallettype": "main", "balance": balance, "currency": "NGN"}]

    def get_balance(self) -> Decimal:
        return to_decimal(self.get_wallets()[0]["balance"])

    def get_transaction(self, transaction_ref: str) -> dict:
        body = self._request(
            "POST",
            "/api/verify/",
            data={"api": self.api_key, "requestID": str(transaction_ref)},
            allow_not_found=True,
        )
        description = str(body.get("description") or "").strip().upper()
        raw_status = str(body.get("status") or "").strip().lower()

        if description == "TRANSACTION_SUCCESSFUL":
            status = "SUCCESS"
        elif description == "TRANSACTION_FAILED" or description.startswith("CONTENT_NOT_FOUND"):
            status = "FAILED"
        elif raw_status in ("success", "successful"):
            status = "SUCCESS"
        elif raw_status in ("failed", "failure"):
            status = "FAILED"
        else:
            status = raw_status.upper()

        return {
            "status": status,
            "transaction_id": body.get("transaction_id") or body.get("transactionID"),
            "amount": body.get("amount"),
            "api_response": body.get("api_response"),
            "token": body.get("token"),
        }


def _split_display_name(display_name: str) -> tuple[str, str]:
    """
    Splits a GSUBZ plan label into its size and validity.

    "10GB - 30days" -> ("10GB", "30")
    "1.5GB (All Social Media) - 30days" -> ("1.5GB", "30")
    "1.5GB" -> ("1.5GB", "")
    """
    label = (display_name or "").strip()
    if not label:
        return "", ""

    size = label
    validity = ""

    if "-" in label:
        head, _, tail = label.partition("-")
        size = head.strip()
        validity = tail.strip()

    # Drop any parenthetical qualifier, e.g. "1.2GB (All Social Media)".
    if "(" in size:
        size = size.split("(", 1)[0].strip()

    validity = validity.lower().replace("days", "").replace("day", "").strip()
    return size, validity
