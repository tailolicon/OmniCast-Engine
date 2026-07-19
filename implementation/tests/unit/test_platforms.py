from unittest.mock import AsyncMock, MagicMock

import pytest

from omnicast.platforms import (
    Destination,
    PlatformId,
    PlatformRegistry,
    PlatformStatus,
    PublishMetadata,
    PublishRequest,
)
from omnicast.platforms.tiktok import TikTokPlatform
from omnicast.platforms.youtube import YouTubePlatform
from omnicast.upload.models import UploadResult, UploadStatus


def _request(**kwargs) -> PublishRequest:
    metadata = PublishMetadata(
        title="Test Video",
        description="Made with AI assistance.",
        tags=["ai", "finance"],
        extra={"duration_seconds": 60, "aspect_ratio": "9:16"},
    )
    defaults = {
        "video_id": "v1",
        "channel_id": "ch1",
        "account_id": "acct1",
        "video_path": "/tmp/final.mp4",
        "metadata": metadata,
        "dry_run": True,
    }
    defaults.update(kwargs)
    return PublishRequest(**defaults)


class TestPlatformModels:
    def test_destination_defaults(self):
        dest = Destination(
            destination_id="ch1_tiktok",
            platform_id=PlatformId.TIKTOK,
            account_id="acct1",
        )

        assert dest.enabled is True
        assert dest.approval_required is False
        assert dest.format_variant == "standard"


class TestPlatformRegistry:
    def test_register_and_get(self):
        registry = PlatformRegistry()
        platform = TikTokPlatform()

        registry.register(platform)

        assert registry.get("tiktok") is platform
        assert registry.ids() == ["tiktok"]

    def test_missing_platform_raises_clear_error(self):
        registry = PlatformRegistry()

        with pytest.raises(KeyError, match="Platform not registered"):
            registry.get("missing")


class TestYouTubePlatform:
    @pytest.mark.asyncio
    async def test_publish_delegates_to_existing_uploader(self):
        uploader = MagicMock()
        uploader.estimate_quota_cost.return_value = 1650
        uploader.upload = AsyncMock(
            return_value=UploadResult(
                youtube_video_id="yt_123",
                channel_id="acct1",
                status=UploadStatus.PUBLISHED,
                url="https://youtu.be/yt_123",
                thumbnail_set=True,
            )
        )
        platform = YouTubePlatform(uploader=uploader)

        result = await platform.publish(_request(thumbnail_paths=["/tmp/t.jpg"]))

        assert result.platform_id == PlatformId.YOUTUBE
        assert result.post_id == "yt_123"
        assert result.status == PlatformStatus.PUBLISHED
        uploader.upload.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_validation_blocks_missing_ai_disclosure(self):
        uploader = MagicMock()
        metadata = PublishMetadata(
            title="Test",
            description="Plain description",
            ai_disclosure=False,
        )
        platform = YouTubePlatform(uploader=uploader)

        issues = await platform.validate(_request(metadata=metadata))

        assert any(issue.severity == "blocking" for issue in issues)
        assert any("AI disclosure" in issue.message for issue in issues)


class TestTikTokPlatform:
    @pytest.mark.asyncio
    async def test_dry_run_returns_draft_result(self):
        platform = TikTokPlatform()

        result = await platform.publish(_request())

        assert result.platform_id == PlatformId.TIKTOK
        assert result.status == PlatformStatus.DRAFT
        assert result.post_id.startswith("dry_run_tiktok_")
        assert result.raw["payload"]["source_info"]["source"] == "PULL_FROM_URL"

    @pytest.mark.asyncio
    async def test_validate_requires_vertical_variant(self):
        platform = TikTokPlatform()
        metadata = PublishMetadata(
            title="Test",
            description="Made with AI assistance.",
            extra={"duration_seconds": 60, "aspect_ratio": "16:9"},
        )

        issues = await platform.validate(_request(metadata=metadata))

        assert any(issue.code == "not_vertical" for issue in issues)

    @pytest.mark.asyncio
    async def test_real_publish_without_token_fails_safely(self):
        platform = TikTokPlatform()
        request = _request(dry_run=False)

        result = await platform.publish(request)

        assert result.status == PlatformStatus.FAILED
        assert "OAuth token" in (result.error or "")


class TestPlatformApiHelpers:
    def test_platform_specs_include_youtube_and_tiktok(self):
        from omnicast.api import server

        specs = server._platform_specs()

        assert {spec["platform_id"] for spec in specs} == {"youtube", "tiktok"}
        assert specs[0]["format_spec"]["aspect_ratio"] == "16:9"
        assert specs[1]["format_spec"]["aspect_ratio"] == "9:16"

    def test_legacy_channel_gets_implicit_youtube_destination(self):
        from omnicast.api import server

        destinations = server._destinations_for_channel({
            "channel_id": "ch1",
            "name": "Channel One",
            "youtube_channel_id": "UC123",
            "market": "US",
        })

        assert destinations == [{
            "destination_id": "ch1_youtube",
            "channel_id": "ch1",
            "channel_name": "Channel One",
            "platform_id": "youtube",
            "account_id": "UC123",
            "format_variant": "youtube_16x9",
            "enabled": True,
            "approval_required": False,
            "schedule_policy": "prime_time",
            "market": "US",
            "metadata_overrides": {},
            "implicit_legacy": True,
        }]

    def test_monetization_readiness_is_not_ship_without_live_credentials_and_offer(self):
        from omnicast.api import server

        readiness = server._monetization_readiness()

        assert readiness["recommendation"] in {"wait", "reject"}
        blocker_names = {item["name"] for item in readiness["blockers"]}
        assert "multi_platform_analytics" not in blocker_names
        assert "affiliate_tracking" not in blocker_names
        assert "credential_vault" not in blocker_names
        assert {"encrypted_credentials_configured", "active_offer_configured"} & blocker_names
