"""
SubHero SMM Platform Metadata Registry & Dynamic Detection
==========================================================
Provides dynamic detection of social media platforms from OgaViral / upstream catalogues,
complete with brand colors, icons, and styling for individual icon buttons.
"""

PLATFORMS_META = {
    "instagram": {
        "slug": "instagram",
        "name": "Instagram",
        "emoji": "📸",
        "feather_icon": "instagram",
        "brand_color": "#E1306C",
        "brand_bg": "linear-gradient(135deg, #f09433 0%, #e6683c 25%, #dc2743 50%, #cc2366 75%, #bc1888 100%)",
        "border_color": "#E1306C",
        "order": 1,
    },
    "tiktok": {
        "slug": "tiktok",
        "name": "TikTok",
        "emoji": "🎵",
        "feather_icon": "video",
        "brand_color": "#00F2FE",
        "brand_bg": "linear-gradient(135deg, #010101 0%, #000000 60%, #FE2C55 100%)",
        "border_color": "#FE2C55",
        "order": 2,
    },
    "youtube": {
        "slug": "youtube",
        "name": "YouTube",
        "emoji": "▶️",
        "feather_icon": "youtube",
        "brand_color": "#FF0000",
        "brand_bg": "linear-gradient(135deg, #FF0000 0%, #CC0000 100%)",
        "border_color": "#FF0000",
        "order": 3,
    },
    "twitter": {
        "slug": "twitter",
        "name": "Twitter / X",
        "emoji": "𝕏",
        "feather_icon": "twitter",
        "brand_color": "#1DA1F2",
        "brand_bg": "linear-gradient(135deg, #000000 0%, #111827 100%)",
        "border_color": "#38BDF8",
        "order": 4,
    },
    "facebook": {
        "slug": "facebook",
        "name": "Facebook",
        "emoji": "📘",
        "feather_icon": "facebook",
        "brand_color": "#1877F2",
        "brand_bg": "linear-gradient(135deg, #1877F2 0%, #0D5CB6 100%)",
        "border_color": "#1877F2",
        "order": 5,
    },
    "telegram": {
        "slug": "telegram",
        "name": "Telegram",
        "emoji": "✈️",
        "feather_icon": "send",
        "brand_color": "#229ED9",
        "brand_bg": "linear-gradient(135deg, #2AABEE 0%, #229ED9 100%)",
        "border_color": "#229ED9",
        "order": 6,
    },
    "whatsapp": {
        "slug": "whatsapp",
        "name": "WhatsApp",
        "emoji": "💬",
        "feather_icon": "message-circle",
        "brand_color": "#25D366",
        "brand_bg": "linear-gradient(135deg, #25D366 0%, #128C7E 100%)",
        "border_color": "#25D366",
        "order": 7,
    },
    "spotify": {
        "slug": "spotify",
        "name": "Spotify",
        "emoji": "🎧",
        "feather_icon": "music",
        "brand_color": "#1DB954",
        "brand_bg": "linear-gradient(135deg, #1DB954 0%, #191414 100%)",
        "border_color": "#1DB954",
        "order": 8,
    },
    "threads": {
        "slug": "threads",
        "name": "Threads",
        "emoji": "🧵",
        "feather_icon": "at-sign",
        "brand_color": "#FFFFFF",
        "brand_bg": "linear-gradient(135deg, #101010 0%, #262626 100%)",
        "border_color": "#A3A3A3",
        "order": 9,
    },
    "snapchat": {
        "slug": "snapchat",
        "name": "Snapchat",
        "emoji": "👻",
        "feather_icon": "camera",
        "brand_color": "#FFFC00",
        "brand_bg": "linear-gradient(135deg, #FFFC00 0%, #F5E800 100%)",
        "border_color": "#FFFC00",
        "order": 10,
    },
    "linkedin": {
        "slug": "linkedin",
        "name": "LinkedIn",
        "emoji": "💼",
        "feather_icon": "linkedin",
        "brand_color": "#0A66C2",
        "brand_bg": "linear-gradient(135deg, #0A66C2 0%, #004182 100%)",
        "border_color": "#0A66C2",
        "order": 11,
    },
    "discord": {
        "slug": "discord",
        "name": "Discord",
        "emoji": "👾",
        "feather_icon": "message-square",
        "brand_color": "#5865F2",
        "brand_bg": "linear-gradient(135deg, #5865F2 0%, #4752C4 100%)",
        "border_color": "#5865F2",
        "order": 12,
    },
    "twitch": {
        "slug": "twitch",
        "name": "Twitch",
        "emoji": "🎮",
        "feather_icon": "tv",
        "brand_color": "#9146FF",
        "brand_bg": "linear-gradient(135deg, #9146FF 0%, #772CE8 100%)",
        "border_color": "#9146FF",
        "order": 13,
    },
    "kick": {
        "slug": "kick",
        "name": "Kick",
        "emoji": "🟢",
        "feather_icon": "play",
        "brand_color": "#53FC18",
        "brand_bg": "linear-gradient(135deg, #0A0A0A 0%, #1A1A1A 100%)",
        "border_color": "#53FC18",
        "order": 14,
    },
    "audiomack": {
        "slug": "audiomack",
        "name": "Audiomack",
        "emoji": "🎶",
        "feather_icon": "volume-2",
        "brand_color": "#FFA200",
        "brand_bg": "linear-gradient(135deg, #FFA200 0%, #CC8200 100%)",
        "border_color": "#FFA200",
        "order": 15,
    },
    "apple_music": {
        "slug": "apple_music",
        "name": "Apple Music",
        "emoji": "🍎",
        "feather_icon": "disc",
        "brand_color": "#FA2D48",
        "brand_bg": "linear-gradient(135deg, #FA2D48 0%, #D4143D 100%)",
        "border_color": "#FA2D48",
        "order": 16,
    },
    "gaming": {
        "slug": "gaming",
        "name": "Gaming / Steam",
        "emoji": "🕹️",
        "feather_icon": "cpu",
        "brand_color": "#66C0F4",
        "brand_bg": "linear-gradient(135deg, #171A21 0%, #1B2838 100%)",
        "border_color": "#66C0F4",
        "order": 17,
    },
    "traffic": {
        "slug": "traffic",
        "name": "Web Traffic",
        "emoji": "🌐",
        "feather_icon": "globe",
        "brand_color": "#3B82F6",
        "brand_bg": "linear-gradient(135deg, #1E40AF 0%, #1D4ED8 100%)",
        "border_color": "#3B82F6",
        "order": 18,
    },
    "other": {
        "slug": "other",
        "name": "Other Services",
        "emoji": "⚡",
        "feather_icon": "zap",
        "brand_color": "#8B5CF6",
        "brand_bg": "linear-gradient(135deg, #2E1065 0%, #4C1D95 100%)",
        "border_color": "#8B5CF6",
        "order": 99,
    },
}


def detect_platform(category_str, name_str=""):
    """
    Detects the canonical platform slug from raw category and service name strings.
    Ensures that individual platforms (Facebook, WhatsApp, Threads, Snapchat, LinkedIn,
    Discord, Twitch, Kick, Spotify, etc.) receive their own dedicated button and are
    never lumped under generic 'other'.
    """
    text = f"{category_str or ''} {name_str or ''}".lower()

    if "instagram" in text:
        return "instagram"
    if "tiktok" in text or "tik tok" in text:
        return "tiktok"
    if "youtube" in text:
        return "youtube"
    if "threads" in text:
        return "threads"
    if "twitter" in text or "x.com" in text or text == "x" or " x " in text or text.startswith("x ") or text.endswith(" x") or "x -" in text or "x:" in text:
        return "twitter"
    if "facebook" in text or "fb " in text or "fb:" in text:
        return "facebook"
    if "telegram" in text:
        return "telegram"
    if "whatsapp" in text or "whats app" in text:
        return "whatsapp"
    if "spotify" in text:
        return "spotify"
    if "snapchat" in text:
        return "snapchat"
    if "linkedin" in text:
        return "linkedin"
    if "discord" in text:
        return "discord"
    if "twitch" in text:
        return "twitch"
    if "kick.com" in text or "kick " in text or "kick:" in text:
        return "kick"
    if "audiomack" in text:
        return "audiomack"
    if "apple music" in text or "itunes" in text:
        return "apple_music"
    if "steam" in text or "roblox" in text or "game" in text or "ea play" in text:
        return "gaming"
    if "traffic" in text or "website" in text:
        return "traffic"

    return "other"


def get_platform_meta(slug):
    """
    Returns platform metadata dictionary for a given slug.
    If a new platform was added upstream, dynamically creates clean metadata
    so it has its own standalone button and styling.
    """
    slug_clean = (slug or "other").lower().strip()
    if slug_clean in PLATFORMS_META:
        return PLATFORMS_META[slug_clean]

    # Dynamic fallback for newly added platform
    pretty_name = slug_clean.replace("_", " ").replace("-", " ").title()
    return {
        "slug": slug_clean,
        "name": pretty_name,
        "emoji": "✨",
        "feather_icon": "share-2",
        "brand_color": "#10B981",
        "brand_bg": "linear-gradient(135deg, #064E3B 0%, #065F46 100%)",
        "border_color": "#10B981",
        "order": 50,
    }


def get_active_platforms():
    """
    Returns an ordered list of platform metadata dictionaries that currently
    have at least one active, classified service in the database.
    """
    from apps.smm.models import SMMService

    # Public visibility: only platforms that have at least one active service with a confirmed tier
    active_slugs = (
        SMMService.objects.filter(is_active=True, tier__isnull=False)
        .exclude(tier="")
        .values_list("category", flat=True)
        .distinct()
    )

    platforms = [get_platform_meta(slug) for slug in active_slugs if slug]
    # Sort according to defined order, with unknown platforms at the end
    platforms.sort(key=lambda p: (p.get("order", 50), p.get("name", "")))
    return platforms
