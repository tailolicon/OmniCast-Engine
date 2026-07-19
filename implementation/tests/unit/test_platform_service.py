import pytest
import json

from omnicast.platforms.models import PlatformId, PlatformStatus, PublishResult
from omnicast.platforms.registry import PlatformRegistry
from omnicast.platforms.service import publish_approval_row


class FakeTikTokPlatform:
    id = "tiktok"

    def __init__(self):
        self.requests = []

    async def publish(self, request):
        self.requests.append(request)
        return PublishResult(
            platform_id=PlatformId.TIKTOK,
            account_id=request.account_id,
            post_id="draft_123",
            status=PlatformStatus.DRAFT,
            url="https://www.tiktok.com/@acct/video/draft_123",
            raw={"mode": "dry_run"},
        )


def _write_video(path):
    path.write_bytes(b"0" * 700_000)


@pytest.mark.asyncio
async def test_publish_approval_row_routes_to_platform_registry(tmp_path):
    video = tmp_path / "video.mp4"
    _write_video(video)
    registry = PlatformRegistry()
    platform = FakeTikTokPlatform()
    registry.register(platform)
    row = {
        "channel_id": "ch1",
        "video_id": "vid1",
        "platform_id": "tiktok",
        "video_path": str(video),
        "title": "Draft Title",
        "summary": "Made with AI assistance.",
        "raw": {
            "account_id": "acct",
            "format_variant": "tiktok_9x16",
            "dry_run": True,
            "niche": "finance",
        },
    }

    outcome = await publish_approval_row(
        row,
        channels_dir=tmp_path / "channels",
        output_dir=tmp_path,
        registry=registry,
    )

    assert outcome["publish_status"] == "draft"
    assert outcome["platform_post_id"] == "draft_123"
    assert outcome["platform_id"] == "tiktok"
    assert "publish_error" not in outcome
    assert platform.requests[0].account_id == "acct"
    assert platform.requests[0].format_variant == "tiktok_9x16"


@pytest.mark.asyncio
async def test_approval_decision_accepts_non_youtube_platform_success(tmp_path, monkeypatch):
    from omnicast.api import server

    monkeypatch.setattr(server, "OUTPUT_DIR", tmp_path)

    async def fake_publish(row):
        return {
            "platform_id": "tiktok",
            "platform_post_id": "draft_123",
            "publish_status": "draft",
            "url": "https://www.tiktok.com/@acct/video/draft_123",
        }

    monkeypatch.setattr(server, "_publish_approved_video", fake_publish)
    created = await server.create_approval({
        "approval_id": "appr1",
        "channel_id": "ch1",
        "video_id": "vid1",
        "destination_id": "ch1_tiktok",
        "platform_id": "tiktok",
        "video_path": str(tmp_path / "video.mp4"),
        "title": "Draft Title",
        "summary": "Made with AI assistance.",
    })

    decided = await server.decide_approval(created["approval"]["approval_id"], "approve", {})

    assert decided["status"] == "published"
    assert decided["approval"]["raw"]["platform_post_id"] == "draft_123"


@pytest.mark.asyncio
async def test_queue_channel_publish_creates_approval_instead_of_uploading(tmp_path, monkeypatch):
    from omnicast.api import server

    channels = tmp_path / "channels"
    channels.mkdir()
    (channels / "ch1.json").write_text(
        json.dumps({
            "channel_id": "ch1",
            "name": "Channel One",
            "niche": "finance",
            "market": "US",
            "youtube_channel_id": "UC123",
        }),
        encoding="utf-8",
    )
    video = tmp_path / "product" / "video.mp4"
    video.parent.mkdir()
    _write_video(video)
    monkeypatch.setattr(server, "CHANNELS_DIR", channels)
    monkeypatch.setattr(server, "OUTPUT_DIR", tmp_path / "output")

    queued = await server.queue_channel_publish("ch1", {
        "video_path": str(video),
        "privacy_status": "unlisted",
    })

    assert queued["status"] == "waiting_approval"
    assert queued["total"] == 1
    approval = queued["approvals"][0]
    assert approval["status"] == "waiting_approval"
    assert approval["platform_id"] == "youtube"
    assert approval["raw"]["privacy_status"] == "unlisted"
    assert approval["raw"]["account_id"] == "ch1"
    assert approval["raw"]["destination_account_id"] == "UC123"
