"""
Tier copy (single source of truth) and service-fact parsing for the SMM page.

Wording rules: only claims we can back up. Never "guaranteed", "100% real",
"non-drop", etc. — we can't verify what sits behind each supplier service.
"""
import re

NOT_SPECIFIED = "Not specified"

TIER_INFO = {
    "basic": {
        "key": "basic",
        "icon": "⚡",
        "label": "Quick Boost",
        "tagline": "Fast and low-cost",
        "what_it_is": "Low-cost delivery that often includes automated or low-activity accounts.",
        "drop_risk": "Higher, and some may disappear over days or weeks.",
        "drop_level": "Higher",
        "best_for": "Quick visibility, testing, tight budgets.",
        "not_ideal_for": "Accounts you plan to monetize or run ads from.",
        "receipt_line": "Fast and low-cost. Some engagement may drop over days or weeks.",
    },
    "standard": {
        "key": "standard",
        "icon": "📈",
        "label": "Growth Boost",
        "tagline": "Balanced",
        "what_it_is": "A mix of active and lower-activity accounts.",
        "drop_risk": "Moderate.",
        "drop_level": "Moderate",
        "best_for": "Steady everyday growth.",
        "not_ideal_for": "",
        "receipt_line": "Balanced. Moderate drop risk.",
    },
    "premium": {
        "key": "premium",
        "icon": "👑",
        "label": "Elite Boost",
        "tagline": "Built to last",
        "what_it_is": "Higher-quality accounts with real-looking profiles and activity, delivered at a natural pace.",
        "drop_risk": "Lower.",
        "drop_level": "Lower",
        "best_for": "Creators, businesses and giveaway hosts.",
        "not_ideal_for": "",
        "receipt_line": "Built to last. Lower drop risk.",
    },
}

TIER_FOOTER = (
    "Platforms can remove inauthentic activity, so some drop can happen on any tier. "
    "If an order fails to start, your wallet is refunded automatically."
)

ACK_DROP_TEXT = "I understand some engagement may drop over time."


# ─── Service fact parsing ────────────────────────────────────────────────
# Returns short normalized values only — never raw description text.

_NUM = r"\d+(?:[.,]\d+)?"
_UNIT_MAP = {
    "min": "min", "mins": "min", "minute": "min", "minutes": "min",
    "h": "hour", "hr": "hour", "hrs": "hour", "hour": "hour", "hours": "hour",
    "d": "day", "day": "day", "days": "day",
}

_REFILL_NONE = re.compile(r"\b(no\s*refill|refill\s*[:\-]?\s*(no|none|n/?a)\b|non[\s-]?refill)", re.I)
_REFILL_DAYS = re.compile(rf"(?:refill[^\n\d]{{0,20}}({_NUM})\s*(?:days?|d)\b|\b({_NUM})\s*(?:days?|d)\s*refill)", re.I)
_REFILL_LIFE = re.compile(r"(lifetime|life\s*time)\s*refill|refill[^\n]{0,15}lifetime", re.I)

_START_LINE = re.compile(r"start(?:ing)?\s*(?:time)?\s*[:\-]?\s*([^\n|]{1,40})", re.I)
_RANGE = re.compile(rf"({_NUM})\s*(?:-|–|to)\s*({_NUM})\s*([a-z]+)", re.I)
_SINGLE = re.compile(rf"({_NUM})\s*([a-z]+)", re.I)

_SPEED = re.compile(rf"(?:speed[^\n\d]{{0,15}})?({_NUM})\s*(k|m)?\s*(?:/|per\s*)\s*(day|hour|d|h)\b", re.I)


def _clean_num(s):
    return s.replace(",", "")


def _parse_refill(text):
    if _REFILL_NONE.search(text):
        return "No refill"
    m = _REFILL_DAYS.search(text)
    if m:
        n = _clean_num(m.group(1) or m.group(2))
        try:
            if 0 < float(n) <= 3650:
                return f"{int(float(n))} days"
        except ValueError:
            pass
    if _REFILL_LIFE.search(text):
        return "Lifetime (per supplier)"
    return NOT_SPECIFIED


def _unit(word, plural):
    u = _UNIT_MAP.get(word.lower())
    if not u:
        return None
    return u + ("s" if plural else "")


def _parse_start(text):
    m = _START_LINE.search(text)
    if not m:
        return NOT_SPECIFIED
    seg = m.group(1)
    if re.search(r"\b(instant|immediate)", seg, re.I):
        return "Instant"
    r = _RANGE.search(seg)
    if r:
        u = _unit(r.group(3), True)
        if u:
            return f"{_clean_num(r.group(1))}–{_clean_num(r.group(2))} {u}"
    s = _SINGLE.search(seg)
    if s:
        n = _clean_num(s.group(1))
        u = _unit(s.group(2), n not in ("1", "1.0"))
        if u:
            return f"{n} {u}"
    return NOT_SPECIFIED


def _parse_speed(text):
    m = _SPEED.search(text)
    if not m:
        return NOT_SPECIFIED
    n = _clean_num(m.group(1))
    mult = (m.group(2) or "").upper()
    per = "day" if m.group(3).lower().startswith("d") else "hour"
    return f"{n}{mult}/{per}"


def parse_service_facts(service):
    text = (getattr(service, "description", "") or "")[:4000]
    mn = getattr(service, "provider_min", 0) or 0
    mx = getattr(service, "provider_max", 0) or 0
    return {
        "refill": _parse_refill(text) if text else NOT_SPECIFIED,
        "start_time": _parse_start(text) if text else NOT_SPECIFIED,
        "speed": _parse_speed(text) if text else NOT_SPECIFIED,
        "min": f"{int(mn):,}" if mn else NOT_SPECIFIED,
        "max": f"{int(mx):,}" if mx else NOT_SPECIFIED,
    }
