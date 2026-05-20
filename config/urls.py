"""
SubHero — URL Configuration
============================
Root URL routing for all apps.
"""

from django.conf import settings
from django.contrib import admin
from django.urls import include, path
from django.views.generic import TemplateView

urlpatterns = [
    # Admin — URL configurable via .env (PRD Section 7.6)
    path(settings.ADMIN_URL, admin.site.urls),

    # Public pages
    path("", TemplateView.as_view(template_name="landing.html"), name="landing"),

    # Auth / Accounts
    path("auth/", include("apps.accounts.urls", namespace="accounts")),

    # Dashboard (stub for Phase 1)
    path("dashboard/", TemplateView.as_view(template_name="dashboard.html"), name="dashboard"),

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
]

# Debug toolbar — dev only
if settings.DEBUG:
    try:
        import debug_toolbar

        urlpatterns = [
            path("__debug__/", include(debug_toolbar.urls)),
        ] + urlpatterns
    except ImportError:
        pass
