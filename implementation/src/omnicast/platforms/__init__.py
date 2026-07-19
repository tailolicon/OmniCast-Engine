"""Multi-platform publishing adapters."""

from omnicast.platforms.base import IPlatform
from omnicast.platforms.models import (
    AuthState,
    Destination,
    FormatSpec,
    PlatformId,
    PlatformStatus,
    PolicyIssue,
    PostStats,
    PublishMetadata,
    PublishRequest,
    PublishResult,
    QuotaInfo,
)
from omnicast.platforms.registry import PlatformRegistry

__all__ = [
    "AuthState",
    "Destination",
    "FormatSpec",
    "IPlatform",
    "PlatformId",
    "PlatformRegistry",
    "PlatformStatus",
    "PolicyIssue",
    "PostStats",
    "PublishMetadata",
    "PublishRequest",
    "PublishResult",
    "QuotaInfo",
]
