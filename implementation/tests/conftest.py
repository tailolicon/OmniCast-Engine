"""Shared test fixtures."""

import pytest

from omnicast.models.schemas import ChannelCreate, VideoCreate, BrandConfig
from omnicast.models.enums import Niche, Market, ChannelType, TopicSource


@pytest.fixture
def sample_channel_create() -> ChannelCreate:
    return ChannelCreate(
        name="Finance Hub US",
        niche=Niche.FINANCE,
        channel_type=ChannelType.HUB,
        target_market=Market.US,
        google_cloud_project="omnicast-fin-us",
        api_key_ref="sops://keys/fin_us.enc",
    )


@pytest.fixture
def sample_video_create() -> VideoCreate:
    return VideoCreate(
        channel_id=1,
        title="5 Investment Mistakes to Avoid in 2026",
        niche=Niche.FINANCE,
        target_market=Market.US,
        topic_source=TopicSource.GOOGLE_TRENDS,
    )


@pytest.fixture
def sample_brand_config() -> BrandConfig:
    return BrandConfig(
        channel_id="hub_finance_us",
        voice_profile="kokoro_en_us_v1",
        color_palette=["#1A1A2E", "#E94560", "#FFFFFF"],
        font="Montserrat Bold",
    )