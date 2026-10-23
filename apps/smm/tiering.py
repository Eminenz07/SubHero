"""
SubHero SMM Tier Classification & Suggestion Engine
===================================================
Classifies services into the 3-tier structure:
  - basic: Quick Boost (Fast delivery, lower retention)
  - standard: Growth Boost (Balanced speed and retention, Most Popular)
  - premium: Elite Boost (Real, active engagement, highest retention, Recommended)

Pricing is the MAJOR determinant: a service is banded by its price within its
subcategory (bottom third = basic, middle = standard, top third = premium).
Keywords only adjust the price band by at most one tier — so a cheap plan can
never land in Elite Boost, and an expensive plan needs quality signals to earn it.
"""

from decimal import Decimal
import logging

logger = logging.getLogger(__name__)

PREMIUM_KEYWORDS = [
    "real", "hq", "high quality", "non-drop", "non drop", "nondrop",
    "refill guarantee", "refill", "lifetime", "organic", "elite", "targeted",
    "usa", "nigerian", "active", "permanent", "monetization", "exclusive",
    "vip", "verified", "slow", "natural", "guaranteed"
]

BASIC_KEYWORDS = [
    "instant", "fast", "cheap", "no refill", "no guarantee",
    "bot", "mixed", "speed", "quick", "cheapest", "low retention", "flash"
]

STANDARD_KEYWORDS = [
    "steady", "30 days", "30-day", "growth", "balanced", "stable",
    "standard", "regular", "normal"
]


def score_keywords(text):
    """
    Computes keyword scores for a service description + name.
    Returns (premium_score, basic_score, standard_score).
    """
    if not text:
        return 0, 0, 0

    text_lower = text.lower()
    premium_score = sum(1 for kw in PREMIUM_KEYWORDS if kw in text_lower)
    basic_score = sum(1 for kw in BASIC_KEYWORDS if kw in text_lower)
    standard_score = sum(1 for kw in STANDARD_KEYWORDS if kw in text_lower)

    # Specific strong keywords give extra weight
    if "non-drop" in text_lower or "non drop" in text_lower or "nondrop" in text_lower:
        premium_score += 2
    if "refill guarantee" in text_lower or "lifetime" in text_lower:
        premium_score += 2
    if "real & active" in text_lower or "organic" in text_lower:
        premium_score += 2
    if "no refill" in text_lower or "no guarantee" in text_lower:
        basic_score += 2
    if "instant" in text_lower and "refill" not in text_lower:
        basic_score += 1

    return premium_score, basic_score, standard_score


def determine_price_band(service, group_prices):
    """
    MAJOR DETERMINANT: bands the service by price within its group
    (subcategory prices, falling back to platform-level prices).
    Bottom third = basic, middle third = standard, top third = premium.
    """
    prices = [p for p in (group_prices or []) if p is not None]
    if len(prices) <= 2:
        return "standard"

    sorted_prices = sorted(prices)
    n = len(sorted_prices)
    t1 = sorted_prices[n // 3]
    t2 = sorted_prices[(2 * n) // 3]

    price = service.subhero_price_per_1k or service.provider_rate or Decimal("0")
    if price <= t1:
        return "basic"
    elif price >= t2:
        return "premium"
    return "standard"


def calculate_suggested_tier(service, group_prices=None):
    """
    Calculates the recommended tier ('basic', 'standard', 'premium').

    Price band is the primary classifier; keywords adjust it by at most ONE tier:
      - premium band → premium (demoted to standard if zero quality signals)
      - standard band → standard (promoted to premium only with strong premium
        signals and no cheap language; demoted to basic with explicit cheap signals)
      - basic band → basic (lifted to standard only with real premium signals)
    """
    # 1. Price band — the major determinant
    price_band = determine_price_band(service, group_prices)

    # 2. Keyword analysis — the fine adjustment
    combined_text = f"{service.name or ''} {service.subcategory or ''} {service.description or ''}"
    prem_score, basic_score, std_score = score_keywords(combined_text)

    # 3. Decision synthesis: keywords shift the price band by at most one tier
    if price_band == "premium":
        # Top-priced service: it must still show some quality (or at least no
        # explicit cheap/bot language) to be recommended as Elite.
        if prem_score >= 1 or (basic_score == 0 and std_score >= 1):
            return "premium"
        return "standard"

    if price_band == "standard":
        if prem_score >= 3 and basic_score == 0:
            return "premium"
        if (basic_score >= 2 and prem_score == 0) or basic_score >= 3:
            return "basic"
        return "standard"

    # price_band == "basic": a cheap plan can NEVER be premium.
    if prem_score >= 2 and basic_score == 0:
        return "standard"
    return "basic"


def _price_groups_for_queryset(services):
    """
    Builds price lists grouped by subcategory (falling back to platform category)
    so banding compares like-for-like services (e.g. IG Comments vs IG Comments).
    """
    groups = {}
    for s in services:
        key = (s.subcategory or "").strip() or s.category or "other"
        groups.setdefault(key, []).append(s.subhero_price_per_1k or s.provider_rate)
    return groups


def reclassify_services(qs=None):
    """
    Recomputes suggested_tier for services using subcategory price grouping,
    and applies the suggestion as the confirmed tier for every service whose
    tier_source is not 'manual' (admin overrides are never touched).

    Returns (suggested_updated, tiers_applied).
    """
    from apps.smm.models import SMMService

    if qs is None:
        qs = SMMService.objects.filter(is_active=True)

    services = list(qs)
    if not services:
        return 0, 0

    price_groups = _price_groups_for_queryset(services)

    suggested_updated = 0
    tiers_applied = 0
    for s in services:
        key = (s.subcategory or "").strip() or s.category or "other"
        suggestion = calculate_suggested_tier(s, price_groups.get(key, []))

        update_fields = []
        if s.suggested_tier != suggestion:
            s.suggested_tier = suggestion
            update_fields.append("suggested_tier")

        if s.tier_source != "manual" and s.tier != suggestion:
            s.tier = suggestion
            s.tier_source = "auto"
            update_fields.extend(["tier", "tier_source"])

        if update_fields:
            s.save(update_fields=list(set(update_fields)))
            if "suggested_tier" in update_fields:
                suggested_updated += 1
            if "tier" in update_fields:
                tiers_applied += 1

    logger.info("Reclassified SMM services: %d suggestions updated, %d auto tiers applied.", suggested_updated, tiers_applied)
    return suggested_updated, tiers_applied


def auto_suggest_tiers_for_catalogue(qs=None):
    """
    Backwards-compatible wrapper: recomputes suggestions and applies them to
    all non-manual services. Returns the number of services processed.
    """
    suggested_updated, tiers_applied = reclassify_services(qs=qs)
    return suggested_updated + tiers_applied
