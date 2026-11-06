from django.conf import settings

from apps.vtu.providers.base import VTUProvider
from apps.vtu.providers.errors import ProviderError

_PROVIDERS = {
    "dancity": "apps.vtu.providers.dancity.DancityProvider",
}


def get_provider() -> VTUProvider:
    """Return the configured outbound VTU provider."""
    name = str(getattr(settings, "VTU_PROVIDER", "dancity") or "dancity").strip().lower()

    if name not in _PROVIDERS:
        raise ProviderError(
            f"Unknown VTU provider '{name}'. Configured providers: {', '.join(sorted(_PROVIDERS))}."
        )

    from django.utils.module_loading import import_string

    return import_string(_PROVIDERS[name])()


__all__ = ["get_provider", "ProviderError", "VTUProvider"]
