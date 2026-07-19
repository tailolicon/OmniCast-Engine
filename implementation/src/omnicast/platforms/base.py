"""Platform publishing protocol."""

from __future__ import annotations

from typing import Protocol

from omnicast.platforms.models import (
    AuthState,
    FormatSpec,
    PolicyIssue,
    PostStats,
    PublishRequest,
    PublishResult,
    QuotaInfo,
)


class IPlatform(Protocol):
    """Contract implemented by every official publishing surface."""

    id: str
    format_spec: FormatSpec

    async def authenticate(self, account_id: str) -> AuthState: ...

    async def quota(self, account_id: str) -> QuotaInfo: ...

    async def validate(self, request: PublishRequest) -> list[PolicyIssue]: ...

    async def publish(self, request: PublishRequest) -> PublishResult: ...

    async def fetch_analytics(self, post_id: str, account_id: str) -> PostStats: ...

    async def fetch_comments(self, post_id: str, account_id: str) -> list[dict]: ...
