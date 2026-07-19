"""Shared models for multi-platform publishing.

The platform layer is intentionally small: existing upload code can adapt into
it, while new platforms expose the same publish/analytics contract.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum

from pydantic import Field

from omnicast.models.schemas import OmnicastSchema


class PlatformId(StrEnum):
    YOUTUBE = "youtube"
    TIKTOK = "tiktok"
    FACEBOOK = "facebook"
    INSTAGRAM = "instagram"
    MANUAL = "manual"


class PlatformStatus(StrEnum):
    DRAFT = "draft"
    SCHEDULED = "scheduled"
    PUBLISHED = "published"
    WAITING_APPROVAL = "waiting_approval"
    FAILED = "failed"
    SKIPPED = "skipped"


class PolicySeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    BLOCKING = "blocking"


class FormatSpec(OmnicastSchema):
    """Output constraints for one platform/variant."""

    variant: str = "standard"
    aspect_ratio: str = "16:9"
    width: int = 1920
    height: int = 1080
    min_duration_seconds: int = 1
    max_duration_seconds: int = 43200
    codec: str = "h264"
    caption_max_length: int = 5000
    supports_scheduling: bool = True
    supports_thumbnail: bool = True


class AuthState(OmnicastSchema):
    platform_id: PlatformId
    account_id: str
    authenticated: bool = False
    scopes: list[str] = Field(default_factory=list)
    expires_at: datetime | None = None
    error: str | None = None


class QuotaInfo(OmnicastSchema):
    platform_id: PlatformId
    account_id: str
    remaining: int | None = None
    reset_at: datetime | None = None
    unit: str = "requests"
    details: dict = Field(default_factory=dict)


class PolicyIssue(OmnicastSchema):
    code: str
    message: str
    severity: PolicySeverity = PolicySeverity.WARNING


class PublishMetadata(OmnicastSchema):
    title: str
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    language: str = "en"
    privacy_status: str = "private"
    publish_at: datetime | None = None
    ai_disclosure: bool = True
    made_for_kids: bool = False
    extra: dict = Field(default_factory=dict)


class PublishRequest(OmnicastSchema):
    video_id: str
    channel_id: str
    account_id: str
    video_path: str
    metadata: PublishMetadata
    thumbnail_paths: list[str] = Field(default_factory=list)
    format_variant: str = "standard"
    dry_run: bool = False


class PublishResult(OmnicastSchema):
    platform_id: PlatformId
    account_id: str
    post_id: str = ""
    status: PlatformStatus = PlatformStatus.PUBLISHED
    url: str = ""
    published_at: datetime | None = None
    thumbnail_set: bool = False
    error: str | None = None
    raw: dict = Field(default_factory=dict)


class PostStats(OmnicastSchema):
    platform_id: PlatformId
    account_id: str
    post_id: str
    channel_id: str = ""
    fetched_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    views: int = 0
    likes: int = 0
    comments: int = 0
    shares: int = 0
    watch_time_seconds: float = 0.0
    revenue: float = 0.0
    raw: dict = Field(default_factory=dict)


class Destination(OmnicastSchema):
    """One channel publishing target."""

    destination_id: str
    platform_id: PlatformId
    account_id: str
    format_variant: str = "standard"
    enabled: bool = True
    approval_required: bool = False
    schedule_policy: str = "prime_time"
    market: str = "US"
    metadata_overrides: dict = Field(default_factory=dict)
