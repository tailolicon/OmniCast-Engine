"""YouTube platform adapter around the existing upload pipeline."""

from __future__ import annotations

from omnicast.platforms.analytics_store import PlatformAnalyticsStore
from omnicast.platforms.models import (
    AuthState,
    FormatSpec,
    PlatformId,
    PlatformStatus,
    PolicyIssue,
    PolicySeverity,
    PostStats,
    PublishMetadata,
    PublishRequest,
    PublishResult,
    QuotaInfo,
)
from omnicast.upload.compliance import ComplianceChecker
from omnicast.upload.models import UploadMetadata, UploadRequest, UploadStatus
from omnicast.upload.oauth import OAuth2Manager
from omnicast.upload.youtube_api import YouTubeUploader


def _to_upload_metadata(metadata: PublishMetadata) -> UploadMetadata:
    return UploadMetadata(
        title=metadata.title,
        description=metadata.description,
        tags=metadata.tags,
        language=metadata.language,
        ai_disclosure=metadata.ai_disclosure,
        privacy_status=metadata.privacy_status,
        publish_at=metadata.publish_at,
        made_for_kids=metadata.made_for_kids,
    )


def _to_upload_request(request: PublishRequest) -> UploadRequest:
    return UploadRequest(
        video_id=request.video_id,
        channel_id=request.account_id,
        video_path=request.video_path,
        thumbnail_paths=request.thumbnail_paths,
        metadata=_to_upload_metadata(request.metadata),
    )


class YouTubePlatform:
    """Official YouTube Data API v3 adapter."""

    id = PlatformId.YOUTUBE.value
    format_spec = FormatSpec(
        variant="youtube_16x9",
        aspect_ratio="16:9",
        width=1920,
        height=1080,
        caption_max_length=5000,
        supports_scheduling=True,
        supports_thumbnail=True,
    )

    def __init__(
        self,
        uploader: YouTubeUploader,
        oauth: OAuth2Manager | None = None,
        compliance: ComplianceChecker | None = None,
        analytics_store: PlatformAnalyticsStore | None = None,
    ) -> None:
        self.uploader = uploader
        self.oauth = oauth
        self.compliance = compliance or ComplianceChecker()
        self.analytics_store = analytics_store

    async def authenticate(self, account_id: str) -> AuthState:
        if not self.oauth:
            return AuthState(
                platform_id=PlatformId.YOUTUBE,
                account_id=account_id,
                authenticated=False,
                error="OAuth2Manager not configured",
            )
        health = await self.oauth.check_health(account_id)
        return AuthState(
            platform_id=PlatformId.YOUTUBE,
            account_id=account_id,
            authenticated=health.error is None,
            scopes=health.scopes,
            expires_at=health.expires_at,
            error=health.error,
        )

    async def quota(self, account_id: str) -> QuotaInfo:
        return QuotaInfo(
            platform_id=PlatformId.YOUTUBE,
            account_id=account_id,
            remaining=None,
            unit="quota_units",
            details={"upload_cost_with_thumbnail": self.uploader.estimate_quota_cost(True)},
        )

    async def validate(self, request: PublishRequest) -> list[PolicyIssue]:
        result = self.compliance.check(_to_upload_request(request))
        return [
            PolicyIssue(
                code="youtube_compliance",
                message=violation,
                severity=PolicySeverity.BLOCKING,
            )
            for violation in result.violations
        ]

    async def publish(self, request: PublishRequest) -> PublishResult:
        issues = await self.validate(request)
        blocking = [issue for issue in issues if issue.severity == PolicySeverity.BLOCKING]
        if blocking:
            return PublishResult(
                platform_id=PlatformId.YOUTUBE,
                account_id=request.account_id,
                status=PlatformStatus.FAILED,
                error="; ".join(issue.message for issue in blocking),
            )

        result = await self.uploader.upload(_to_upload_request(request))
        status = (
            PlatformStatus.FAILED
            if result.status == UploadStatus.FAILED
            else PlatformStatus.PUBLISHED
        )
        return PublishResult(
            platform_id=PlatformId.YOUTUBE,
            account_id=request.account_id,
            post_id=result.youtube_video_id,
            status=status,
            url=result.url,
            published_at=result.published_at,
            thumbnail_set=result.thumbnail_set,
            error=result.error,
        )

    async def fetch_analytics(self, post_id: str, account_id: str) -> PostStats:
        if self.analytics_store:
            stats = self.analytics_store.latest(self.id, post_id)
            if stats:
                return stats
        return PostStats(
            platform_id=PlatformId.YOUTUBE,
            account_id=account_id,
            post_id=post_id,
            raw={"source": "youtube_platform_adapter", "ingested": False},
        )

    async def fetch_comments(self, post_id: str, account_id: str) -> list[dict]:
        return []
