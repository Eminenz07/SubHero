"""
SubHero SMM Tier Classification & Suggestion Engine
===================================================
Classifies services into the 3-tier structure:
  - basic: Quick Boost (Fast delivery, lower retention)
  - standard: Growth Boost (Balanced speed and retention, Most Popular)
  - premium: Elite Boost (Real, active engagement, highest retention, Recommended)

Provides auto-suggestion heuristics based on keyword matching and category
price banding, while strictly keeping newly synced services unclassified
until explicitly confirmed by an admin.
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
    "instant", "fast", "cheap", "no refill", "no guarantee", "drop",
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


def determine_price_band(service, category_prices):
    """
    Determines whether the service's price per 1k is in the bottom third (basic),
    middle third (standard), or top third (premium) of its category/platform.
    """
    if not category_prices or len(category_prices) <= 2:
        return "standard"

    sorted_prices = sorted(category_prices)
    n = len(sorted_prices)
    t1 = sorted_prices[n // 3]
    t2 = sorted_prices[(2 * n) // 3]

    price = service.subhero_price_per_1k or service.provider_rate or Decimal("0")
    if price <= t1:
        return "basic"
    elif price >= t2:
        return "premium"
    return "standard"


def calculate_suggested_tier(service, category_prices=None):
    """
    Calculates the recommended tier ('basic', 'standard', 'premium') for a service
    based on keyword matching and category price banding.
    """
    # 1. Keyword analysis
    combined_text = f"{service.name or ''} {service.subcategory or ''} {service.description or ''}"
    prem_score, basic_score, std_score = score_keywords(combined_text)

    # 2. Price banding
    price_band = determine_price_band(service, category_prices) if category_prices else "standard"

    # 3. Decision synthesis
    # If strong premium keywords are present, elevate to premium
    if prem_score >= 3 or (prem_score > basic_score and price_band == "premium"):
        return "premium"

    # If explicit basic keywords with no quality/refill language, lower to basic
    if (basic_score >= 2 and prem_score == 0) or (price_band == "basic" and prem_score == 0):
        return "basic"

    # If price band is top third and has at least some quality signal
    if price_band == "premium" and prem_score >= 1:
        return "premium"

    # If price band is bottom third and lacks strong premium signals
    if price_band == "basic" and prem_score <= 1:
        return "basic"

    # Default balanced option
    return "standard"


def auto_suggest_tiers_for_catalogue(qs=None):
    """
    Scans services in the catalogue and updates their `suggested_tier` field
    without altering `tier` (which remains unclassified until admin approval).
    """
    from apps.smm.models import SMMService

    if qs is None:
        qs = SMMService.objects.filter(is_active=True)

    services = list(qs)
    if not services:
        return 0

    # Group price points by category for price banding calculation
    cat_prices = {}
    for s in services:
        cat_prices.setdefault(s.category, []).append(s.subhero_price_per_1k or s.provider_rate)

    updated_count = 0
    for s in services:
        suggestion = calculate_suggested_tier(s, cat_prices.get(s.category, []))
        if s.suggested_tier != suggestion:
            s.suggested_tier = suggestion
            s.save(update_fields=["suggested_tier"])
            updated_count += 1

    logger.info("Auto-suggested tiers updated for %d SMM services.", updated_count)
    return updated_count
