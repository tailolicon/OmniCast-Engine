"""Pydantic models for Upload Pipeline. All frozen, inherit OmnicastSchema."""

from __future__ import annotations
from datetime import datetime, timezone
from enum import StrEnum
from pydantic import Field
from omnicast.models.schemas import OmnicastSchema


class UploadStatus(StrEnum):
    PENDING = "pending"
    COMPLIANCE_CHECK = "compliance_check"
    SCHEDULED = "scheduled"
    UPLOADING = "uploading"
    PROCESSING = "processing"  # YouTube processing after upload
    PUBLISHED = "published"
    FAILED = "failed"
    REJECTED = "rejected"  # compliance gate failed


class ComplianceResult(OmnicastSchema):
    """Result from compliance gate."""
    passed: bool = False
    checks: dict[str, bool] = Field(default_factory=dict)
    # keys: ai_disclosure, no_misleading, no_copyright_music,
    #        ftc_disclosure, advertiser_friendly, not_children, cross_channel_unique
    violations: list[str] = Field(default_factory=list)
    checked_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def violation_count(self) -> int:
        return len(self.violations)


class UploadMetadata(OmnicastSchema):
    """Metadata for YouTube video upload."""
    title: str
    description: str
    tags: list[str] = Field(default_factory=list)
    category_id: str = "22"  # People & Blogs default
    language: str = "en"
    ai_disclosure: bool = True
    privacy_status: str = "private"  # private → scheduled → public
    publish_at: datetime | None = None
    made_for_kids: bool = False


class UploadRequest(OmnicastSchema):
    """Full upload request."""
    video_id: str
    channel_id: str
    video_path: str
    thumbnail_paths: list[str] = Field(default_factory=list)
    metadata: UploadMetadata
    compliance: ComplianceResult | None = None


class UploadResult(OmnicastSchema):
    """Result from YouTube upload."""
    youtube_video_id: str = ""
    channel_id: str = ""
    status: UploadStatus = UploadStatus.PUBLISHED
    published_at: datetime | None = None
    url: str = ""
    thumbnail_set: bool = False
    error: str | None = None


class ScheduleSlot(OmnicastSchema):
    """A scheduled upload time slot."""
    channel_id: str
    scheduled_at: datetime
    market: str = "US"
    is_prime_time: bool = True


class TokenStatus(StrEnum):
    VALID = "valid"
    EXPIRING_SOON = "expiring_soon"  # < 1 hour
    EXPIRED = "expired"
    REVOKED = "revoked"


class TokenHealth(OmnicastSchema):
    """OAuth2 token health status."""
    channel_id: str
    status: TokenStatus = TokenStatus.VALID
    expires_at: datetime | None = None
    scopes: list[str] = Field(default_factory=list)
    last_check: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    error: str | None = None


class UploadPipelineState(OmnicastSchema):
    """Tracks upload pipeline progress for one video."""
    video_id: str
    channel_id: str
    compliance: UploadStatus = UploadStatus.PENDING
    scheduling: UploadStatus = UploadStatus.PENDING
    upload: UploadStatus = UploadStatus.PENDING
    thumbnail: UploadStatus = UploadStatus.PENDING

    @property
    def all_done(self) -> bool:
        return all(
            s in (UploadStatus.PUBLISHED, UploadStatus.SCHEDULED)
            for s in [self.compliance, self.scheduling, self.upload, self.thumbnail]
        )

    @property
    def has_failure(self) -> bool:
        return any(
            s in (UploadStatus.FAILED, UploadStatus.REJECTED)
            for s in [self.compliance, self.scheduling, self.upload, self.thumbnail]
        )
