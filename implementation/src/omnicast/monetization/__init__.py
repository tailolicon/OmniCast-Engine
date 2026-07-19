"""Monetization services."""

from omnicast.monetization.affiliate import AffiliateService

__all__ = ["AffiliateService"]
from omnicast.monetization.affiliate import AffiliateService
from omnicast.monetization.linker import MonetizationLinker, MonetizeResult
from omnicast.monetization.redirect import RedirectService

__all__ = [
    "AffiliateService",
    "MonetizationLinker",
    "MonetizeResult",
    "RedirectService",
]
