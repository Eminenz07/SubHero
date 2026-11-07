from django.conf import settings

from apps.vtu.providers.base import VTUProvider
from apps.vtu.providers.errors import ProviderError

_PROVIDERS = {
    "dancity": "apps.vtu.providers.dancity.DancityProvider",
    "gsubz": "apps.vtu.providers.gsubz.GsubzProvider",
}

_FUND_URLS = {
    "dancity": "https://app.dancity.app",
    "gsubz": "https://gsubz.com/dashboard",
}


def _provider_order() -> list[str]:
    """The provider chain, in the order it should be tried."""
    raw = getattr(settings, "VTU_PROVIDER_ORDER", "") or getattr(settings, "VTU_PROVIDER", "") or "dancity"
    names = [part.strip().lower() for part in str(raw).replace(";", ",").split(",")]
    return [name for name in names if name]


def _build(name: str) -> VTUProvider:
    if name not in _PROVIDERS:
        raise ProviderError(
            f"Unknown VTU provider '{name}'. Configured providers: {', '.join(sorted(_PROVIDERS))}."
        )

    from django.utils.module_loading import import_string

    return import_string(_PROVIDERS[name])()


def get_provider() -> VTUProvider:
    """Return the outbound VTU provider chain.

    A single provider is returned as-is. With more than one provider a
    FailoverProvider is returned, which tries them in order.
    """
    order = _provider_order()
    if not order:
        raise ProviderError("No VTU provider is configured.")

    providers = [_build(name) for name in order]

    if len(providers) == 1:
        return providers[0]

    from apps.vtu.providers.failover import FailoverProvider

    return FailoverProvider(providers)


def provider_label() -> str:
    """Human readable name of the configured provider chain."""
    order = _provider_order()
    if not order:
        return "VTU"
    if len(order) == 1:
        return order[0].title()
    return " + ".join(name.title() for name in order)


def provider_fund_url() -> str:
    """Where the admin tops up the primary provider's wallet."""
    order = _provider_order()
    primary = order[0] if order else ""
    return _FUND_URLS.get(primary, "")


__all__ = [
    "get_provider",
    "provider_label",
    "provider_fund_url",
    "ProviderError",
    "VTUProvider",
]
