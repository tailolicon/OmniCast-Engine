from unittest.mock import AsyncMock

import pytest

from omnicast.config.channel import ChannelProfile
from omnicast.models.enums import ChannelType, Market, Niche
from omnicast.platforms.models import (
    Destination,
    PlatformId,
    PlatformStatus,
    PublishMetadata,
    PublishRequest,
    PublishResult,
)
from omnicast.platforms.publisher import MultiPlatformPublisher, destinations_for_channel
from omnicast.platforms.registry import PlatformRegistry


def _channel(**kwargs) -> ChannelProfile:
    defaults = {
        "channel_id": "ch1",
        "name": "Channel One",
        "niche": Niche.FINANCE,
        "market": Market.US,
        "channel_type": ChannelType.HUB,
    }
    defaults.update(kwargs)
    return ChannelProfile(**defaults)


def _request() -> PublishRequest:
    return PublishRequest(
        video_id="v1",
        channel_id="ch1",
        account_id="placeholder",
        video_path="/tmp/master.mp4",
        metadata=PublishMetadata(title="Title", description="Made with AI assistance."),
        dry_run=True,
    )


class FakePlatform:
    id = "youtube"

    def __init__(self) -> None:
        self.publish = AsyncMock(return_value=PublishResult(
            platform_id=PlatformId.YOUTUBE,
            account_id="acct1",
            post_id="post1",
            status=PlatformStatus.PUBLISHED,
        ))


def test_destinations_for_legacy_channel_defaults_to_youtube():
    channel = _channel(youtube_channel_id="UC123")

    destinations = destinations_for_channel(channel)

    assert len(destinations) == 1
    assert destinations[0].platform_id == PlatformId.YOUTUBE
    assert destinations[0].account_id == "UC123"
    assert destinations[0].format_variant == "youtube_16x9"


@pytest.mark.asyncio
async def test_publisher_stops_at_approval_gate():
    channel = _channel(destinations=[
        Destination(
            destination_id="ch1_tiktok",
            platform_id=PlatformId.TIKTOK,
            account_id="acct1",
            approval_required=True,
        )
    ])
    registry = PlatformRegistry()
    publisher = MultiPlatformPublisher(registry)

    outcomes = await publisher.publish(channel, _request())

    assert outcomes[0].result.status == PlatformStatus.WAITING_APPROVAL
    assert outcomes[0].result.platform_id == PlatformId.TIKTOK


@pytest.mark.asyncio
async def test_publisher_calls_registered_platform_for_enabled_destination():
    channel = _channel(destinations=[
        Destination(
            destination_id="ch1_youtube",
            platform_id=PlatformId.YOUTUBE,
            account_id="acct1",
            format_variant="youtube_16x9",
        )
    ])
    platform = FakePlatform()
    registry = PlatformRegistry()
    registry.register(platform)
    publisher = MultiPlatformPublisher(registry)

    outcomes = await publisher.publish(channel, _request())

    assert outcomes[0].result.status == PlatformStatus.PUBLISHED
    platform.publish.assert_awaited_once()
    sent_request = platform.publish.await_args.args[0]
    assert sent_request.account_id == "acct1"
    assert sent_request.format_variant == "youtube_16x9"
