import logging
from decimal import Decimal
from typing import Any, Optional

import requests
from django.conf import settings
from django.core.cache import cache

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

CATALOG_CACHE_TTL = 1800
DEFAULT_TIMEOUT = 30
DEFAULT_BASE_URL = "https://v2.cool-sub.com"

_SERVICE_KEYWORDS = {
    "airtime": "AIRTIME",
    "data": "DATA",
    "cable": "CABLE",
    "electricity": "ELECTRIC",
    "exam": "EXAM",
}

# Cool-sub lists some data bundles without a product label. They are all MTN
# SME bundles, so they are filed under that product.
_UNTAGGED_DATA_PRODUCT = "MTN SME"

# Cool-sub's product names for the networks SubHero sells. 9mobile airtime
# is branded "T2 Mobile Airtime" on their side.
_AIRTIME_ALIASES = {
    "9mobile": ("t2 mobile", "t2mobile", "9mobile", "etisalat"),
}


class DancityProvider(VTUProvider):
    """Cool-sub merchant API (https://v2.cool-sub.com/api/v1).

    Cool-sub runs the merchant platform Dancity's API key is issued against.
    The merchant endpoints live under ``/api/v1``; the legacy MSORG slots
    (``/api/data``, ``/api/topup``) serve the same catalogue.
    """

    name = "dancity"
    max_airtime_amount = Decimal("10000")

    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None, timeout: Optional[int] = None):
        self.api_key = api_key if api_key is not None else getattr(settings, "DANCITY_API_KEY", "")
        self.base_url = (
            base_url if base_url is not None else getattr(settings, "DANCITY_BASE_URL", DEFAULT_BASE_URL)
        ).rstrip("/")
        self.timeout = timeout if timeout is not None else getattr(settings, "DANCITY_TIMEOUT", DEFAULT_TIMEOUT)

    # ─────────────────────────── HTTP ───────────────────────────

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "X-API-Key": self.api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "channel": "API",
        }

    def _url(self, path: str) -> str:
        return f"{self.base_url}/api/v1{path}"

    def _request(self, method: str, path: str, params: Optional[dict] = None, json_body: Optional[dict] = None):
        if not self.api_key:
            raise ProviderAuthError("DANCITY_API_KEY is not configured on this environment.")

        try:
            response = requests.request(
                method,
                self._url(path),
                headers=self._headers(),
                params=params,
                json=json_body,
                timeout=self.timeout,
            )
        except requests.exceptions.Timeout as exc:
            raise ProviderTransientError(f"Dancity timed out on {path}.") from exc
        except requests.exceptions.RequestException as exc:
            raise ProviderTransientError(f"Dancity connection error on {path}: {exc}") from exc

        return self._handle(response, path)

    def _handle(self, response, path: str) -> dict:
        try:
            body = response.json()
        except ValueError as exc:
            raise ProviderTransientError(
                f"Dancity returned a non-JSON response [{response.status_code}] on {path}."
            ) from exc

        if not isinstance(body, dict):
            raise ProviderTransientError(f"Dancity returned an unexpected payload shape on {path}.")

        if response.status_code in (200, 201):
            return body

        message = body.get("message") or body.get("error") or f"HTTP {response.status_code}"
        if isinstance(message, (list, tuple)):
            message = "; ".join(str(part) for part in message)
        message = str(message)

        status = response.status_code
        if status in (401, 403):
            raise ProviderAuthError(f"Dancity rejected access to {path}: {message}")
        if status == 404:
            raise ProviderNotFoundError(f"Dancity could not find {path}: {message}")
        if status == 429:
            raise ProviderRateLimitedError(f"Dancity rate limit reached on {path}: {message}")
        if status == 400:
            lowered = message.lower()
            if "insufficient" in lowered or "balance" in lowered:
                raise ProviderDeclinedError(f"Dancity wallet balance too low: {message}")
            raise ProviderValidationError(f"Dancity rejected the {path} request: {message}")
        if status == 422:
            raise ProviderValidationError(f"Dancity rejected the {path} request: {message}")
        raise ProviderTransientError(f"Dancity server error [{status}] on {path}: {message}")

    # ────────────────────────── catalog ──────────────────────────

    # Cool-sub wraps catalogue payloads under a different key per endpoint:
    # the service list uses "allServices", the product list uses "allProduct"
    # and the plan lists use "data".
    _CATALOG_KEYS = ("data", "allProduct", "allServices", "plans", "products")

    def _catalog_get(self, path: str, params: Optional[dict] = None):
        cache_key = f"dancity:catalog:{path}:{sorted((params or None or {}).items())}"
        try:
            cached = cache.get(cache_key)
        except Exception:
            cached = None
        if cached is not None:
            return cached

        body = self._request("GET", path, params=params)
        data = None
        for key in self._CATALOG_KEYS:
            candidate = body.get(key)
            if isinstance(candidate, list):
                data = candidate
                break
        if data is None:
            data = body

        try:
            cache.set(cache_key, data, CATALOG_CACHE_TTL)
        except Exception:
            pass
        return data

    def _resolve_service(self, service_key: str) -> str:
        services = self._catalog_get("/services")
        names = []
        for entry in services if isinstance(services, list) else []:
            if isinstance(entry, str):
                names.append(entry)
            elif isinstance(entry, dict):
                label = entry.get("name") or entry.get("service") or entry.get("_id")
                if label:
                    names.append(str(label))

        keyword = _SERVICE_KEYWORDS.get(service_key, service_key.upper())
        for name in names:
            if keyword in name.upper():
                return name
        for name in names:
            if service_key.upper() in name.upper():
                return name
        return keyword

    def _products_for(self, service_key: str) -> list[ServiceProduct]:
        service = self._resolve_service(service_key)
        products = self._catalog_get("/products", {"service": service})

        out = []
        for entry in products if isinstance(products, list) else []:
            if isinstance(entry, str):
                out.append(ServiceProduct(product_id=entry, name=entry, price=Decimal("0")))
                continue
            if not isinstance(entry, dict):
                continue
            name = str(entry.get("name") or entry.get("product") or entry.get("_id") or "").strip()
            if not name:
                continue
            price = to_decimal(
                entry.get("price")
                if entry.get("price") is not None
                else entry.get("amount", entry.get("cost"))
            )
            out.append(
                ServiceProduct(
                    product_id=str(entry.get("_id") or name),
                    name=name,
                    price=price,
                    meta=entry,
                )
            )
        return out

    def list_data_plans(self) -> list[DataPlan]:
        plans = self._catalog_get("/plans/data")
        out = []
        for entry in plans if isinstance(plans, list) else []:
            if not isinstance(entry, dict):
                continue
            plan_id = str(entry.get("planId") or entry.get("_id") or "").strip()
            if not plan_id:
                continue
            product = str(entry.get("product") or "").strip()
            size = str(entry.get("plan") or "").strip()
            validity = str(entry.get("validity") or "").strip()
            if not product:
                # Cool-sub leaves the product blank on a batch of MTN SME
                # bundles. Fill it in so they are filed under the right
                # network and category instead of being dropped.
                product = _UNTAGGED_DATA_PRODUCT
            name = " ".join(part for part in (product, size) if part) or plan_id
            out.append(
                DataPlan(
                    plan_id=plan_id,
                    name=name,
                    provider_product=product,
                    price=to_decimal(entry.get("price")),
                    validity=validity,
                    size=size,
                )
            )
        return out

    def list_cable_plans(self) -> list[CablePlan]:
        plans = self._catalog_get("/plans/cable")
        out = []
        for entry in plans if isinstance(plans, list) else []:
            if not isinstance(entry, dict):
                continue
            plan_id = str(entry.get("planId") or entry.get("_id") or "").strip()
            if not plan_id:
                continue
            product = str(entry.get("product") or "").strip()
            package = str(entry.get("plan") or "").strip()
            out.append(
                CablePlan(
                    plan_id=plan_id,
                    provider=_slug(product),
                    provider_product=product,
                    name=package or plan_id,
                    price=to_decimal(entry.get("price")),
                )
            )
        return out

    def list_airtime_products(self) -> list[ServiceProduct]:
        return self._products_for("airtime")

    def list_electricity_products(self) -> list[ServiceProduct]:
        return self._products_for("electricity")

    def list_exam_products(self) -> list[ServiceProduct]:
        return self._products_for("exam")

    def resolve_airtime_product(self, network: str) -> str:
        target = (network or "").strip().lower()
        products = self.list_airtime_products()

        # Cool-sub sells 9mobile as "T2 Mobile Airtime".
        aliases = _AIRTIME_ALIASES.get(target, ())
        for product in products:
            label = product.name.lower()
            if target in label and "airtime" in label:
                return product.name
        for product in products:
            if target in product.name.lower():
                return product.name
        for alias in aliases:
            for product in products:
                if alias in product.name.lower():
                    return product.name
        raise ProviderNotFoundError(f"Dancity exposes no airtime product for network '{network}'.")

    def resolve_cable_product(self, provider: str) -> str:
        target = (provider or "").strip().lower()
        for plan in self.list_cable_plans():
            label = plan.provider_product.lower()
            if not label:
                continue
            if label == target or target in label or label in target:
                return plan.provider_product
        raise ProviderNotFoundError(f"Dancity exposes no cable product for provider '{provider}'.")

    def resolve_electricity_biller(self, biller_code: str) -> str:
        target = (biller_code or "").strip().upper()
        for product in self.list_electricity_products():
            name = product.name.strip()
            candidates = {
                name.upper(),
                name.split()[0].upper() if name else "",
                str(product.meta.get("billerCode") or "").upper(),
                str(product.meta.get("code") or "").upper(),
            }
            if target in candidates:
                return str(product.meta.get("billerCode") or name)
        return biller_code

    # ───────────────────────── purchases ─────────────────────────

    def _envelope_data(self, body: dict) -> dict:
        if not body.get("success", False):
            message = body.get("message") or body.get("error") or "Dancity declined the request."
            raise ProviderDeclinedError(str(message))
        data = body.get("data")
        return data if isinstance(data, dict) else {}

    def _purchase_result(self, body: dict, fallback_ref: str = "") -> PurchaseResult:
        data = self._envelope_data(body)

        status = str(data.get("status") or "").strip().upper()
        if not status:
            status = PurchaseStatus.SUCCESS

        provider_ref = str(
            data.get("tranxId") or data.get("transactionId") or data.get("_id") or fallback_ref or ""
        )
        message = str(data.get("apiResponse") or body.get("message") or "").strip()
        amount_paid = None
        if data.get("amountPaid") is not None:
            amount_paid = to_decimal(data.get("amountPaid"))

        extra: dict = {}
        if data.get("token"):
            extra["token"] = str(data.get("token"))
        if data.get("units") is not None:
            extra["units"] = str(data.get("units"))
        for key in ("pins", "pin", "serials", "vouchers", "results", "result"):
            if data.get(key):
                extra["pins"] = data.get(key)
                break
        if data.get("customerName"):
            extra["customer_name"] = str(data.get("customerName"))

        if status == PurchaseStatus.SUCCESS:
            return PurchaseResult(True, status, provider_ref, message, amount_paid, extra)
        if status in (PurchaseStatus.PENDING, PurchaseStatus.PROCESSING):
            return PurchaseResult(False, status, provider_ref, message, amount_paid, extra)

        raise ProviderDeclinedError(message or f"Dancity transaction ended with status {status}.")

    def buy_data(self, plan_id: str, phone: str, reference: str) -> PurchaseResult:
        body = self._request(
            "POST",
            "/data/buy",
            json_body={"plan": plan_id, "phone": phone, "customerRef": reference},
        )
        return self._purchase_result(body, reference)

    def buy_airtime(self, product: str, phone: str, amount: Decimal, reference: str) -> PurchaseResult:
        body = self._request(
            "POST",
            "/airtime/buy",
            json_body={
                "product": product,
                "phone": phone,
                "amount": _money(amount),
                "customerRef": reference,
            },
        )
        return self._purchase_result(body, reference)

    def validate_cable(self, smartcard: str, provider: str) -> str:
        body = self._request(
            "POST",
            "/cable/validate",
            json_body={"smartcardNumber": smartcard, "cablename": provider.upper()},
        )
        data = self._envelope_data(body)
        name = str(data.get("customerName") or "").strip()
        if not name:
            raise ProviderValidationError("Dancity returned no subscriber name for that smartcard.")
        return name

    def buy_cable(self, plan_id: str, smartcard: str, customer_name: str, reference: str) -> PurchaseResult:
        body = self._request(
            "POST",
            "/cable/buy",
            json_body={
                "smartcardNumber": smartcard,
                "cableplan": plan_id,
                "customerName": customer_name,
                "customerRef": reference,
            },
        )
        return self._purchase_result(body, reference)

    def validate_meter(self, meter_number: str, biller_code: str, amount: Decimal, meter_type: str) -> str:
        body = self._request(
            "POST",
            "/electricity/validate",
            json_body={
                "meterNumber": meter_number,
                "billerCode": biller_code,
                "amount": _money(amount),
                "meterType": meter_type,
            },
        )
        data = self._envelope_data(body)
        name = str(data.get("customerName") or "").strip()
        if not name:
            raise ProviderValidationError("Dancity returned no account holder name for that meter.")
        return name

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
        body = self._request(
            "POST",
            "/electricity/buy",
            json_body={
                "meterNumber": meter_number,
                "billerCode": biller_code,
                "meterType": meter_type,
                "amount": _money(amount),
                "customerName": customer_name,
                "address": address,
                "customerRef": reference,
            },
        )
        return self._purchase_result(body, reference)

    def buy_exam_pin(self, exam_name: str, quantity: int, reference: str, exam_number: str = "") -> PurchaseResult:
        payload = {"exam_name": exam_name, "quantity": quantity, "customerRef": reference}
        if exam_number:
            payload["examNumber"] = exam_number
        body = self._request("POST", "/education-pin/purchase", json_body=payload)
        return self._purchase_result(body, reference)

    # ────────────────────────── account ──────────────────────────

    def get_wallets(self) -> list[dict]:
        body = self._request("GET", "/wallet")
        data = body.get("data")
        if isinstance(data, dict):
            data = [data]
        return [entry for entry in (data or []) if isinstance(entry, dict)]

    def get_balance(self) -> Decimal:
        wallets = self.get_wallets()
        if not wallets:
            return Decimal("0.00")
        for wallet in wallets:
            label = str(wallet.get("wallettype") or wallet.get("name") or "").strip().lower()
            if label == "main" or label.startswith("main wallet"):
                return to_decimal(wallet.get("balance"))
        return sum((to_decimal(wallet.get("balance")) for wallet in wallets), Decimal("0.00"))

    def get_transaction(self, transaction_ref: str) -> dict:
        body = self._request("GET", f"/transactions/{transaction_ref}")
        data = body.get("data")
        return data if isinstance(data, dict) else {}


def _slug(value: str) -> str:
    return "".join(char if char.isalnum() else "-" for char in (value or "").lower()).strip("-")


def _money(amount: Any) -> Any:
    value = to_decimal(amount)
    if value == value.to_integral_value():
        return int(value)
    return float(value)
