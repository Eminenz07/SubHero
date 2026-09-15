"""
SubHero — Sitemaps Configuration
================================
Django sitemaps covering public static marketing pages and
dynamic public giveaway claim pages.
"""

from django.contrib.sitemaps import Sitemap
from django.urls import reverse
from apps.giveaway.models import Giveaway


class StaticViewSitemap(Sitemap):
    """
    Sitemap for public static pages (Home, Privacy Policy, Terms).
    Excludes any authenticated-only or wallet-related URLs.
    """
    protocol = "https"
    priority = 1.0
    changefreq = "daily"

    def items(self):
        return [
            "landing",
            "privacy",
            "terms",
        ]

    def location(self, item):
        return reverse(item)


class GiveawaySitemap(Sitemap):
    """
    Sitemap for active and completed public giveaways.
    Provides indexed URLs for /g/<slug>/ links.
    """
    protocol = "https"
    changefreq = "hourly"
    priority = 0.8

    def items(self):
        # Index ACTIVE and COMPLETED giveaways so search engines can discover them,
        # excluding CANCELLED ones.
        return Giveaway.objects.filter(status__in=["ACTIVE", "COMPLETED"]).order_by("-created_at")

    def lastmod(self, obj):
        return obj.created_at

    def location(self, obj):
        return reverse("giveaway_short_link", kwargs={"slug": obj.slug})
