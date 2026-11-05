from django.conf import settings
from apps.smm.platforms import PLATFORMS_META


def meta_pixel(request):
    """
    Expose Meta Pixel ID to templates.
    Only exposes the ID on public pages (not admin/subhero-hq).
    """
    if not hasattr(request, "path"):
        return {"meta_pixel_id": ""}

    admin_hq_url = getattr(settings, "ADMIN_HQ_URL", "subhero-hq/")
    admin_url = getattr(settings, "ADMIN_URL", "admin/")

    # Don't load pixel on admin routes
    is_admin = request.path.startswith(f"/{admin_hq_url.rstrip('/')}/") or request.path.startswith(f"/{admin_url.rstrip('/')}/")

    pixel_id = getattr(settings, "META_PIXEL_ID", "") if not is_admin else ""

    return {"meta_pixel_id": pixel_id}


def platforms(request):
    """
    Expose all platform metadata to templates for rendering icons.
    """
    return {"platforms_meta": PLATFORMS_META}


def service_flags(request):
    """
    Expose service launch flags to templates, so a service that is not live yet
    can be labelled "Coming soon" on every surface that lists it.
    """
    return {
        "exam_pin_coming_soon": getattr(settings, "EXAM_PIN_COMING_SOON", False),
    }