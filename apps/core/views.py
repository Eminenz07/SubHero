from django.shortcuts import render
from django.http import HttpResponse

def healthcheck(request):
    """
    Ultra-lightweight healthcheck endpoint for monitoring tools (like UptimeRobot).
    Bypasses sessions, templates, and Redis so zero cache/Redis quota is consumed.
    """
    return HttpResponse("OK", content_type="text/plain")

def csrf_failure(request, reason=""):
    """
    Custom CSRF failure view matching the premium SubHero design theme.
    """
    return render(request, "403.html", {"is_csrf": True, "reason": reason}, status=403)


def robots_txt(request):
    """
    Generates dynamic robots.txt allowing public search engines to crawl public pages
    while disallowing authenticated areas, admin panels, and wallet endpoints.
    """
    from django.conf import settings

    admin_url = f"/{settings.ADMIN_URL.lstrip('/')}"
    admin_hq_url = f"/{settings.ADMIN_HQ_URL.lstrip('/')}"

    lines = [
        "User-agent: *",
        "Allow: /",
        "Allow: /privacy/",
        "Allow: /terms/",
        "Allow: /g/",
        f"Disallow: {admin_url}",
        f"Disallow: {admin_hq_url}",
        "Disallow: /admin/",
        "Disallow: /dashboard/",
        "Disallow: /wallet/",
        "Disallow: /auth/",
        "Disallow: /payments/",
        "Disallow: /notifications/",
        "Disallow: /vtu/",
        "Disallow: /smm/",
        "Disallow: /giveaway/create/",
        "Disallow: /giveaway/mine/",
        "Disallow: /giveaway/*/cancel/",
        "Disallow: /giveaway/*/receipt/",
        "",
        "Sitemap: https://subhero.com.ng/sitemap.xml",
    ]
    return HttpResponse("\n".join(lines), content_type="text/plain; charset=utf-8")

