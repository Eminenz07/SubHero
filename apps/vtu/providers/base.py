from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Optional


class PurchaseStatus:
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"


@dataclass(frozen=True)
class DataPlan:
    plan_id: str
    name: str
    provider_product: str
    price: Decimal
    validity: str = ""


@dataclass(frozen=True)
class CablePlan:
    plan_id: str
    provider: str
    provider_product: str
    name: str
    price: Decimal


@dataclass(frozen=True)
class ServiceProduct:
    product_id: str
    name: str
    price: Decimal
    meta: dict = field(default_factory=dict)


@dataclass(frozen=True)
class PurchaseResult:
    success: bool
    status: str
    provider_ref: str
    message: str
    amount_paid: Optional[Decimal] = None
    extra: dict = field(default_factory=dict)


class VTUProvider(ABC):
    """Contract every outbound VAS provider must satisfy.

    Implementations translate one upstream API into the shapes SubHero stores,
    so call sites never deal with provider specific payloads.
    """

    name = "base"

    max_airtime_amount: Decimal | None = None
    """Largest airtime value the provider accepts in a single transaction.

    ``None`` means the provider has no per-transaction cap.
    """

    @abstractmethod
    def get_balance(self) -> Decimal:
        """Current merchant wallet balance in NGN."""

    @abstractmethod
    def get_wallets(self) -> list[dict]:
        """Raw wallet records, e.g. [{wallettype, balance, currency}]."""

    @abstractmethod
    def list_data_plans(self) -> list[DataPlan]:
        """Every purchasable data plan in the catalogue."""

    @abstractmethod
    def list_cable_plans(self) -> list[CablePlan]:
        """Every purchasable cable subscription package."""

    @abstractmethod
    def list_airtime_products(self) -> list[ServiceProduct]:
        """Airtime products, one per supported network."""

    @abstractmethod
    def list_electricity_products(self) -> list[ServiceProduct]:
        """Electricity billers / distribution companies."""

    @abstractmethod
    def list_exam_products(self) -> list[ServiceProduct]:
        """Education PIN products."""

    @abstractmethod
    def resolve_airtime_product(self, network: str) -> str:
        """Provider product name for a SubHero network slug, e.g. mtn -> 'MTN Airtime'."""

    @abstractmethod
    def resolve_cable_product(self, provider: str) -> str:
        """Provider product label for a SubHero cable slug, e.g. gotv -> 'GOTV'."""

    @abstractmethod
    def resolve_electricity_biller(self, biller_code: str) -> str:
        """Provider biller code for a SubHero DISCO code, e.g. EKEDC -> 'EKEDC'."""

    @abstractmethod
    def buy_data(self, plan_id: str, phone: str, reference: str) -> PurchaseResult:
        """Purchase a data bundle."""

    @abstractmethod
    def buy_airtime(self, product: str, phone: str, amount: Decimal, reference: str) -> PurchaseResult:
        """Purchase airtime top-up."""

    @abstractmethod
    def validate_cable(self, smartcard: str, provider: str) -> str:
        """Return the subscriber name on a smartcard. Raises on invalid smartcard."""

    @abstractmethod
    def buy_cable(self, plan_id: str, smartcard: str, customer_name: str, reference: str) -> PurchaseResult:
        """Renew a cable subscription."""

    @abstractmethod
    def validate_meter(self, meter_number: str, biller_code: str, amount: Decimal, meter_type: str) -> str:
        """Return the account holder name on a meter. Raises on invalid meter."""

    @abstractmethod
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
        """Vend a prepaid token or settle a postpaid bill."""

    @abstractmethod
    def buy_exam_pin(self, exam_name: str, quantity: int, reference: str, exam_number: str = "") -> PurchaseResult:
        """Purchase education PINs."""

    @abstractmethod
    def get_transaction(self, transaction_ref: str) -> dict:
        """Re-query a transaction by id, tranxId or customerRef."""


_NETWORK_TOKENS = (
    ("9mobile", ("9MOBILE", "9 MOBILE", "NINE MOBILE", "ETISALAT")),
    ("airtel", ("AIRTEL",)),
    ("glo", ("GLO",)),
    ("mtn", ("MTN",)),
)

_PLAN_TYPE_TOKENS = (
    ("SME2", ("SME2", "SME 2")),
    ("SME", ("SME",)),
    ("SMART", ("SMART",)),
    ("AWOOF", ("AWOOF",)),
    ("CG", ("CG",)),
    ("CORPORATE", ("CORPORATE",)),
    ("GIFTING", ("GIFTING", "GIFT")),
    ("X", (" X",)),
    ("MIX", ("MIX",)),
)


def derive_network(provider_product: str) -> str:
    """Map a provider product label to a SubHero network slug."""
    label = (provider_product or "").upper()
    for slug, tokens in _NETWORK_TOKENS:
        for token in tokens:
            if token in label:
                return slug
    return "other"


def derive_plan_type(provider_product: str) -> str:
    """Map a provider product label to a SubHero plan category."""
    label = (provider_product or "").upper()
    for plan_type, tokens in _PLAN_TYPE_TOKENS:
        for token in tokens:
            if token in label:
                return plan_type
    return "DATA"


def to_decimal(value: Any, default: str = "0") -> Decimal:
    """Best effort conversion of an upstream price field to Decimal."""
    if value is None:
        return Decimal(default)
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value).replace(",", "").strip())
    except Exception:
        return Decimal(default)
