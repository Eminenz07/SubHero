from django.shortcuts import render
from django.http import HttpResponse
from django.views.generic import TemplateView
from apps.wallet.models import Wallet, WalletTransaction


class DashboardView(TemplateView):
    """
    Dashboard view with Meta Pixel event context.
    """
    template_name = "dashboard.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        if self.request.user.is_authenticated:
            # Fire Purchase event if there's a recent successful wallet funding
            recent_fund = WalletTransaction.objects.filter(
                wallet=self.request.user.wallet,
                txn_type=WalletTransaction.TxnType.FUND,
                status=WalletTransaction.Status.SUCCESS
            ).order_by('-created_at').first()
            
            if recent_fund and not self.request.session.get(f'pixel_purchase_fired_{recent_fund.id}'):
                self.request.session[f'pixel_purchase_fired_{recent_fund.id}'] = True
                context['fire_purchase_event'] = {
                    'value': float(recent_fund.amount),
                    'currency': 'NGN',
                    'transaction_ref': recent_fund.reference,
                }
        
        return context


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


def trigger_test_500(request):
    """
    Diagnostic endpoint to deliberately trigger a 500 error and verify
    that ErrorAlertMiddleware sends an immediate alert to subherong@gmail.com.
    """
    raise RuntimeError(
        "Deliberate 500 Test: Verifying that SubHero ErrorAlertMiddleware catches "
        "and dispatches an immediate email alert to subherong@gmail.com!"
    )

