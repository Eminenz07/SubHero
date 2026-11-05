class ProviderError(Exception):
    """Base class for all outbound provider failures."""


class ProviderAuthError(ProviderError):
    """Credentials rejected, account not permitted, or caller IP not allowlisted.

    Never retryable: retrying cannot change the outcome and would burn rate limit.
    """


class ProviderValidationError(ProviderError):
    """Provider rejected the request payload. Definitive, never retryable."""


class ProviderNotFoundError(ProviderError):
    """Requested plan, product or resource does not exist upstream."""


class ProviderDeclinedError(ProviderError):
    """Provider accepted the request but refused to fulfil it.

    Examples: insufficient wallet balance, ineligible subscriber, invalid line.
    """


class ProviderRateLimitedError(ProviderError):
    """Provider throttled the request. Retryable after a delay."""


class ProviderTransientError(ProviderError):
    """Network fault, timeout or provider 5xx. Retryable."""


class ProviderPendingError(ProviderError):
    """Provider accepted the request but has not settled it yet."""
