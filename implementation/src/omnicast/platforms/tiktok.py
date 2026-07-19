"""TikTok Content Posting API adapter.

This adapter starts M1 with policy/format validation and a safe dry-run path.
Real posting is limited to official Content Posting API flows and requires an
approved app, user OAuth token, and a public pull URL for the video asset.
"""

from __future__ import annotations

import httpx

from omnicast.platforms.analytics_store import PlatformAnalyticsStore
from omnicast.platforms.models import (
    AuthState,
    FormatSpec,
    PlatformId,
    PlatformStatus,
    PolicyIssue,
    PolicySeverity,
    PostStats,
    PublishRequest,
    PublishResult,
    QuotaInfo,
)

TIKTOK_POST_INIT_URL = "https://open.tiktokapis.com/v2/post/publish/video/init/"
TIKTOK_CAPTION_LIMIT = 2200


class TikTokPlatform:
    """TikTok video/reels-style destination via the official posting API."""

    id = PlatformId.TIKTOK.value
    format_spec = FormatSpec(
        variant="tiktok_9x16",
        aspect_ratio="9:16",
        width=1080,
        height=1920,
        min_duration_seconds=3,
        max_duration_seconds=600,
        caption_max_length=TIKTOK_CAPTION_LIMIT,
        supports_scheduling=False,
        supports_thumbnail=False,
    )

    def __init__(
        self,
        access_tokens: dict[str, str] | None = None,
        analytics_store: PlatformAnalyticsStore | None = None,
    ) -> None:
        self._access_tokens = access_tokens or {}
        self.analytics_store = analytics_store

    async def authenticate(self, account_id: str) -> AuthState:
        token = self._access_tokens.get(account_id)
        return AuthState(
            platform_id=PlatformId.TIKTOK,
            account_id=account_id,
            authenticated=bool(token),
            scopes=["video.publish"] if token else [],
            error=None if token else "TikTok OAuth token not configured",
        )

    async def quota(self, account_id: str) -> QuotaInfo:
        return QuotaInfo(
            platform_id=PlatformId.TIKTOK,
            account_id=account_id,
            remaining=None,
            details={"note": "TikTok quota is app/account specific; poll API status externally."},
        )

    async def validate(self, request: PublishRequest) -> list[PolicyIssue]:
        issues: list[PolicyIssue] = []
        caption = self._caption(request)
        if len(caption) > self.format_spec.caption_max_length:
            issues.append(PolicyIssue(
                code="caption_too_long",
                message=(
                    f"TikTok caption exceeds {self.format_spec.caption_max_length} characters"
                ),
                severity=PolicySeverity.BLOCKING,
            ))

        duration = request.metadata.extra.get("duration_seconds")
        if duration is not None:
            if duration < self.format_spec.min_duration_seconds:
                issues.append(PolicyIssue(
                    code="duration_too_short",
                    message="TikTok video must be at least 3 seconds",
                    severity=PolicySeverity.BLOCKING,
                ))
            if duration > self.format_spec.max_duration_seconds:
                issues.append(PolicyIssue(
                    code="duration_too_long",
                    message="TikTok adapter currently targets videos up to 10 minutes",
                    severity=PolicySeverity.BLOCKING,
                ))

        aspect_ratio = request.metadata.extra.get("aspect_ratio")
        if aspect_ratio and aspect_ratio != self.format_spec.aspect_ratio:
            issues.append(PolicyIssue(
                code="not_vertical",
                message="TikTok destination expects a 9:16 vertical render variant",
                severity=PolicySeverity.BLOCKING,
            ))

        if not request.metadata.ai_disclosure:
            issues.append(PolicyIssue(
                code="ai_disclosure_recommended",
                message="AI-generated content should carry clear disclosure",
                severity=PolicySeverity.WARNING,
            ))
        return issues

    async def publish(self, request: PublishRequest) -> PublishResult:
        issues = await self.validate(request)
        blocking = [issue for issue in issues if issue.severity == PolicySeverity.BLOCKING]
        if blocking:
            return PublishResult(
                platform_id=PlatformId.TIKTOK,
                account_id=request.account_id,
                status=PlatformStatus.FAILED,
                error="; ".join(issue.message for issue in blocking),
            )

        if request.dry_run:
            post_id = f"dry_run_tiktok_{request.video_id}"
            return PublishResult(
                platform_id=PlatformId.TIKTOK,
                account_id=request.account_id,
                post_id=post_id,
                status=PlatformStatus.DRAFT,
                url=f"https://www.tiktok.com/@{request.account_id}/video/{post_id}",
                raw={"mode": "dry_run", "payload": self._build_init_payload(request)},
            )

        token = self._access_tokens.get(request.account_id)
        if not token:
            return PublishResult(
                platform_id=PlatformId.TIKTOK,
                account_id=request.account_id,
                status=PlatformStatus.FAILED,
                error="TikTok OAuth token not configured",
            )

        video_url = request.metadata.extra.get("video_url")
        if not video_url:
            return PublishResult(
                platform_id=PlatformId.TIKTOK,
                account_id=request.account_id,
                status=PlatformStatus.FAILED,
                error=(
                    "TikTok real publish requires a public video_url for PULL_FROM_URL "
                    "or a file-upload implementation"
                ),
            )

        payload = self._build_init_payload(request)
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                TIKTOK_POST_INIT_URL,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json; charset=UTF-8",
                },
                json=payload,
            )
        if response.status_code >= 400:
            return PublishResult(
                platform_id=PlatformId.TIKTOK,
                account_id=request.account_id,
                status=PlatformStatus.FAILED,
                error=response.text,
                raw={"status_code": response.status_code},
            )
        data = response.json()
        publish_id = data.get("data", {}).get("publish_id", "")
        return PublishResult(
            platform_id=PlatformId.TIKTOK,
            account_id=request.account_id,
            post_id=publish_id,
            status=PlatformStatus.DRAFT,
            raw=data,
        )

    async def fetch_analytics(self, post_id: str, account_id: str) -> PostStats:
        if self.analytics_store:
            stats = self.analytics_store.latest(self.id, post_id)
            if stats:
                return stats
        return PostStats(
            platform_id=PlatformId.TIKTOK,
            account_id=account_id,
            post_id=post_id,
            raw={"source": "tiktok_platform_adapter", "ingested": False},
        )

    async def fetch_comments(self, post_id: str, account_id: str) -> list[dict]:
        return []

    def _caption(self, request: PublishRequest) -> str:
        tags = " ".join(f"#{tag.lstrip('#')}" for tag in request.metadata.tags)
        return " ".join(part for part in [request.metadata.title, request.metadata.description, tags] if part)

    def _build_init_payload(self, request: PublishRequest) -> dict:
        privacy_level = request.metadata.extra.get("privacy_level", "SELF_ONLY")
        video_url = request.metadata.extra.get("video_url", request.video_path)
        return {
            "post_info": {
                "title": self._caption(request)[: self.format_spec.caption_max_length],
                "privacy_level": privacy_level,
                "disable_duet": bool(request.metadata.extra.get("disable_duet", False)),
                "disable_comment": bool(request.metadata.extra.get("disable_comment", False)),
                "disable_stitch": bool(request.metadata.extra.get("disable_stitch", False)),
                "video_cover_timestamp_ms": int(
                    request.metadata.extra.get("video_cover_timestamp_ms", 1000)
                ),
            },
            "source_info": {
                "source": "PULL_FROM_URL",
                "video_url": video_url,
            },
        }
