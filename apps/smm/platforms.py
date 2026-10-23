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
        "svg": (
            '<defs><linearGradient id="ig-brand-grad" x1="0%" y1="100%" x2="100%" y2="0%">'
            '<stop offset="0%" stop-color="#F09433"/>'
            '<stop offset="25%" stop-color="#E6683C"/>'
            '<stop offset="50%" stop-color="#DC2743"/>'
            '<stop offset="75%" stop-color="#CC2366"/>'
            '<stop offset="100%" stop-color="#BC1888"/>'
            '</linearGradient></defs>'
            '<path fill="url(#ig-brand-grad)" d="M7.0301.084c-1.2768.0602-2.1487.264-2.911.5634-.7888.3075-1.4575.72-2.1228 1.3877-.6652.6677-1.075 1.3368-1.3802 2.127-.2954.7638-.4956 1.6365-.552 2.914-.0564 1.2775-.0689 1.6882-.0626 4.947.0062 3.2586.0206 3.6671.0825 4.9473.061 1.2765.264 2.1482.5635 2.9107.308.7889.72 1.4573 1.388 2.1228.6679.6655 1.3365 1.0743 2.1285 1.38.7632.295 1.6361.4961 2.9134.552 1.2773.056 1.6884.069 4.9462.0627 3.2578-.0062 3.668-.0207 4.9478-.0814 1.28-.0607 2.147-.2652 2.9098-.5633.7889-.3086 1.4578-.72 2.1228-1.3881.665-.6682 1.0745-1.3378 1.3795-2.1284.2957-.7632.4966-1.636.552-2.9124.056-1.2809.0692-1.6898.063-4.948-.0063-3.2583-.021-3.6668-.0817-4.9465-.0607-1.2797-.264-2.1487-.5633-2.9117-.3084-.7889-.72-1.4568-1.3876-2.1228C21.2982 1.33 20.628.9208 19.8378.6165 19.074.321 18.2017.1197 16.9244.0645 15.6471.0093 15.236-.005 11.977.0014 8.718.0076 8.31.0215 7.0301.0839m.1402 21.6932c-1.17-.0509-1.8053-.2453-2.2287-.408-.5606-.216-.96-.4771-1.3819-.895-.422-.4178-.6811-.8186-.9-1.378-.1644-.4234-.3624-1.058-.4171-2.228-.0595-1.2645-.072-1.6442-.079-4.848-.007-3.2037.0053-3.583.0607-4.848.05-1.169.2456-1.805.408-2.2282.216-.5613.4762-.96.895-1.3816.4188-.4217.8184-.6814 1.3783-.9003.423-.1651 1.0575-.3614 2.227-.4171 1.2655-.06 1.6447-.072 4.848-.079 3.2033-.007 3.5835.005 4.8495.0608 1.169.0508 1.8053.2445 2.228.408.5608.216.96.4754 1.3816.895.4217.4194.6816.8176.9005 1.3787.1653.4217.3617 1.056.4169 2.2263.0602 1.2655.0739 1.645.0796 4.848.0058 3.203-.0055 3.5834-.061 4.848-.051 1.17-.245 1.8055-.408 2.2294-.216.5604-.4763.96-.8954 1.3814-.419.4215-.8181.6811-1.3783.9-.4224.1649-1.0577.3617-2.2262.4174-1.2656.0595-1.6448.072-4.8493.079-3.2045.007-3.5825-.006-4.848-.0608M16.953 5.5864A1.44 1.44 0 1 0 18.39 4.144a1.44 1.44 0 0 0-1.437 1.4424M5.8385 12.012c.0067 3.4032 2.7706 6.1557 6.173 6.1493 3.4026-.0065 6.157-2.7701 6.1506-6.1733-.0065-3.4032-2.771-6.1565-6.174-6.1498-3.403.0067-6.156 2.771-6.1496 6.1738M8 12.0077a4 4 0 1 1 4.008 3.9921A3.9996 3.9996 0 0 1 8 12.0077"/>'
        ),
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
        "svg": (
            '<path fill="#FFFFFF" d="M14.234 10.162 22.977 0h-2.072l-7.591 8.824L7.251 0H.258l9.168 13.343L.258 24H2.33l8.016-9.318L16.749 24h6.993zm-2.837 3.299-.929-1.329L3.076 1.56h3.182l5.965 8.532.929 1.329 7.754 11.09h-3.182z"/>'
        ),
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
