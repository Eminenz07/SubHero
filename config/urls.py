"""
SubHero — URL Configuration
============================
Root URL routing for all apps.
"""

from django.conf import settings
from django.contrib import admin
from django.contrib.sitemaps.views import sitemap
from django.urls import include, path
from django.views.generic import TemplateView
from apps.giveaway import views as giveaway_views
from apps.core import views as core_views
from config.sitemaps import StaticViewSitemap, GiveawaySitemap

sitemaps = {
    "static": StaticViewSitemap,
    "giveaways": GiveawaySitemap,
}

urlpatterns = [
    # Search Engine Optimization (SEO)
    path("robots.txt", core_views.robots_txt, name="robots_txt"),
    path("sitemap.xml", sitemap, {"sitemaps": sitemaps}, name="django.contrib.sitemaps.views.sitemap"),

    # Zero-overhead healthcheck for UptimeRobot / uptime monitors (0 Redis commands)
    path("healthz/", core_views.healthcheck, name="healthcheck"),
    path("ping/", core_views.healthcheck, name="ping"),
    path("trigger-test-500/", core_views.trigger_test_500, name="trigger_test_500"),

    # PWA files served at root
    path("manifest.json", TemplateView.as_view(template_name="manifest.json", content_type="application/json"), name="manifest_json"),
    path("sw.js", TemplateView.as_view(template_name="sw.js", content_type="application/javascript"), name="service_worker"),

    # Admin — URL configurable via .env (PRD Section 7.6)
    path(settings.ADMIN_URL, admin.site.urls),

    # Public pages
    path("", TemplateView.as_view(template_name="landing.html"), name="landing"),
    path("privacy/", TemplateView.as_view(template_name="privacy.html"), name="privacy"),
    path("terms/", TemplateView.as_view(template_name="terms.html"), name="terms"),
    path("guidelines/", TemplateView.as_view(template_name="guidelines.html"), name="guidelines"),

    # Auth / Accounts
    path("auth/", include("apps.accounts.urls", namespace="accounts")),

    # Dashboard (stub for Phase 1)
    path("dashboard/", core_views.DashboardView.as_view(), name="dashboard"),

    # Wallet (Phase 2)
    path("wallet/", include("apps.wallet.urls", namespace="wallet")),

    # VTU (Phase 4)
    path("vtu/", include("apps.vtu.urls", namespace="vtu")),

    # SMM (Phase 5)
    path("smm/", include("apps.smm.urls", namespace="smm")),

    # Transactions (Phase 3)
    # path("transactions/", include("apps.transactions.urls", namespace="transactions")),

    # Payments webhooks (Phase 2)
    path("payments/", include("apps.payments.urls", namespace="payments")),

    # Notifications (Phase 3)
    path("notifications/", include("apps.notifications.urls", namespace="notifications")),

    # Admin Panel (HQ) — configurable via .env (PRD Section 3.1)
    path(settings.ADMIN_HQ_URL, include("apps.admin_panel.urls", namespace="admin_panel")),
    
    # Giveaway (Phase 3)
    path("giveaway/", include("apps.giveaway.urls", namespace="giveaway")),
    path("g/<str:slug>/", giveaway_views.claim_page, name="giveaway_short_link"),
]

# Debug toolbar — dev only
if settings.DEBUG:
    from django.shortcuts import redirect
    from django.contrib.auth import login, get_user_model

    def demo_login_view(request):
        User = get_user_model()
        u, _ = User.objects.get_or_create(phone_number='+2348012345678', defaults={'email': 'demo@subhero.ng', 'full_name': 'Tunde Balogun', 'is_verified': True})
        login(request, u, backend='django.contrib.auth.backends.ModelBackend')
        target = request.GET.get('next', '/giveaway/create/')
        return redirect(target)

    urlpatterns += [
        path("demo-login/", demo_login_view, name="demo_login"),
    ]

    try:
        import debug_toolbar

        urlpatterns = [
            path("__debug__/", include(debug_toolbar.urls)),
        ] + urlpatterns
    except ImportError:
        pass

