"""
Promo Campaigns — Views
======================
Public join link (noindex, IP-ratelimited) that resolves the campaign
server-side and hands the code off to registration.
"""

import logging
import re

from django.conf import settings
from django.contrib import messages
from django.db.models import F
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.views import View
from django_ratelimit.decorators import ratelimit

from apps.core.utils import get_client_ip

from .models import PromoCampaign
from .services import promo_enabled

logger = logging.getLogger(__name__)

CODE_RE = re.compile(r"^[A-Za-z0-9-]{4,32}$")


def _neutral(request):
    """Neutral message that reveals nothing about code validity."""
    messages.info(
        request,
        "This offer isn't available right now, but you can still sign up.",
    )
    return redirect(reverse("accounts:register"))


class JoinPromoView(View):
    """
    GET /join/<code>/ — noindex, ratelimited by IP.
    Resolves the campaign server-side, stores the code in the session,
    and hands off to ?promo=<code> on the register page.
    Never reveals whether a code is valid.
    """

    template_name = "promos/join.html"

    @method_decorator(ratelimit(key="ip", rate="10/m", method="GET", block=True))
    def dispatch(self, *args, **kwargs):
        return super().dispatch(*args, **kwargs)

    def get(self, request, code):
        code_clean = (code or "").strip().upper()
        campaign = None

        if CODE_RE.match(code_clean or ""):
            campaign = (
                PromoCampaign.objects.filter(code__iexact=code_clean)
                .only(
                    "id", "code", "name", "bonus_amount", "max_claims",
                    "claimed_count", "status", "starts_at", "ends_at",
                )
                .first()
            )
            if campaign:
                # Increment visits atomically (only real campaigns).
                PromoCampaign.objects.filter(id=campaign.id).update(
                    visits=F("visits") + 1
                )

        # Always store the code in the session so it survives the redirect.
        request.session["promo_code"] = code_clean
        request.session.modified = True

        effective = campaign.effective_status if campaign else None

        if not campaign or effective != PromoCampaign.Status.ACTIVE:
            # Neutral message — reveals nothing about validity.
            return _neutral(request)

        # Active campaign: render the join banner + hand off to register.
        spots_left = max(campaign.max_claims - campaign.claimed_count, 0)
        context = {
            "campaign": campaign,
            "spots_left": spots_left,
            "promo_code": code_clean,
            "register_url": f"{reverse('accounts:register')}?promo={code_clean}",
            "PROMOS_ENABLED": promo_enabled(),
        }
        return render(request, self.template_name, context)
