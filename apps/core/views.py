from django.shortcuts import render

def csrf_failure(request, reason=""):
    """
    Custom CSRF failure view matching the premium SubHero design theme.
    """
    return render(request, "403.html", {"is_csrf": True, "reason": reason}, status=403)
