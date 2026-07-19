"""Test Pydantic models validation."""

import pytest
from pydantic import ValidationError

from omnicast.models.schemas import (
    ChannelCreate,
    VideoCreate,
    TopicCandidate,
    AlertCreate,
    BrandConfig,
)
from omnicast.models.enums import (
    Niche,
    Market,
    ChannelType,
    TopicSource,
    AlertSeverity,
)


class TestChannelCreate:
    def test_valid(self, sample_channel_create):
        assert sample_channel_create.name == "Finance Hub US"
        assert sample_channel_create.niche == Niche.FINANCE

    def test_name_too_long(self):
        with pytest.raises(ValidationError):
            ChannelCreate(
                name="x" * 101,
                niche=Niche.FINANCE,
                channel_type=ChannelType.HUB,
                target_market=Market.US,
                google_cloud_project="proj",
                api_key_ref="ref",
            )

    def test_frozen(self, sample_channel_create):
        with pytest.raises(ValidationError):
            sample_channel_create.name = "new name"


class TestTopicCandidate:
    def test_score_bounds(self):
        with pytest.raises(ValidationError):
            TopicCandidate(
                title="Test",
                niche=Niche.FINANCE,
                market=Market.US,
                source=TopicSource.REDDIT,
                trend_momentum=50,  # max 30 → should fail
                gap_score=0,
                rpm_potential=0,
                novelty_score=0,
                total_score=50,
            )

    def test_valid_topic(self):
        topic = TopicCandidate(
            title="Bitcoin ETF Impact",
            niche=Niche.FINANCE,
            market=Market.US,
            source=TopicSource.GOOGLE_TRENDS,
            trend_momentum=25,
            gap_score=35,
            rpm_potential=15,
            novelty_score=8,
            total_score=83,
        )
        assert topic.total_score == 83


class TestAlertCreate:
    def test_valid(self):
        alert = AlertCreate(
            severity=AlertSeverity.CRITICAL,
            source="worker_2",
            alert_type="heartbeat_failed",
            message="Worker 2 heartbeat missed for 90s",
        )
        assert alert.severity == AlertSeverity.CRITICAL


class TestBrandConfig:
    def test_defaults(self):
        config = BrandConfig(channel_id="test")
        assert config.voice_profile == "kokoro_en_us_v1"
        assert config.max_segment_duration == 60
        assert config.use_video_gen is False