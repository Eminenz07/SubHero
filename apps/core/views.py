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

