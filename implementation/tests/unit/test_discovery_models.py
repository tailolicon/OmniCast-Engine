"""Tests for Phase 3 discovery models."""

import pytest
from datetime import datetime, timezone
from pydantic import ValidationError

from omnicast.discovery.models import (
    TopicRawData,
    SourceResult,
    ScoredTopic,
    DiscoveryConfig,
)
from omnicast.models.enums import Niche, Market, TopicSource


# === TopicRawData ===


class TestTopicRawData:
    def test_create_minimal(self):
        t = TopicRawData(
            title="Test Topic",
            source=TopicSource.GOOGLE_TRENDS,
            niche=Niche.FINANCE,
            market=Market.US,
        )
        assert t.title == "Test Topic"
        assert t.description == ""
        assert t.source_url == ""
        assert t.raw_metrics == {}
        assert isinstance(t.extracted_at, datetime)

    def test_create_full(self):
        t = TopicRawData(
            title="Bitcoin ETF Surge",
            description="Bitcoin ETFs see record inflows",
            source=TopicSource.NEWS_RSS,
            niche=Niche.FINANCE,
            market=Market.US,
            source_url="https://example.com/btc",
            raw_metrics={"mention_count": 15, "hours_since_first": 6},
        )
        assert t.raw_metrics["mention_count"] == 15
        assert t.source_url == "https://example.com/btc"

    def test_frozen(self):
        t = TopicRawData(
            title="X", source=TopicSource.REDDIT, niche=Niche.TECH, market=Market.US,
        )
        with pytest.raises(ValidationError):
            t.title = "Y"

    def test_extracted_at_auto(self):
        t = TopicRawData(
            title="X", source=TopicSource.REDDIT, niche=Niche.TECH, market=Market.US,
        )
        assert t.extracted_at.tzinfo is not None


# === SourceResult ===


class TestSourceResult:
    def test_success_result(self):
        topics = [
            TopicRawData(
                title=f"Topic {i}",
                source=TopicSource.GOOGLE_TRENDS,
                niche=Niche.FINANCE,
                market=Market.US,
            )
            for i in range(3)
        ]
        r = SourceResult(source=TopicSource.GOOGLE_TRENDS, topics=topics)
        assert r.success is True
        assert r.count == 3
        assert r.error is None

    def test_error_result(self):
        r = SourceResult(
            source=TopicSource.REDDIT,
            error="API rate limited",
        )
        assert r.success is False
        assert r.count == 0
        assert r.error == "API rate limited"

    def test_with_duration(self):
        r = SourceResult(
            source=TopicSource.NEWS_RSS,
            scan_duration_seconds=2.35,
        )
        assert r.scan_duration_seconds == 2.35


# === ScoredTopic ===


class TestScoredTopic:
    def _raw(self) -> TopicRawData:
        return TopicRawData(
            title="Test",
            source=TopicSource.GOOGLE_TRENDS,
            niche=Niche.FINANCE,
            market=Market.US,
        )

    def test_approve_action(self):
        s = ScoredTopic(
            raw=self._raw(),
            trend_momentum=25, gap_score=30, rpm_potential=15, novelty_score=5,
            total_score=75, auto_approved=True,
        )
        assert s.action == "approve"

    def test_review_action(self):
        s = ScoredTopic(
            raw=self._raw(),
            trend_momentum=15, gap_score=20, rpm_potential=10, novelty_score=5,
            total_score=55, needs_review=True,
        )
        assert s.action == "review"

    def test_discard_action(self):
        s = ScoredTopic(
            raw=self._raw(),
            trend_momentum=10, gap_score=10, rpm_potential=5, novelty_score=3,
            total_score=28,
        )
        assert s.action == "discard"

    def test_score_bounds_valid(self):
        s = ScoredTopic(
            raw=self._raw(),
            trend_momentum=0, gap_score=0, rpm_potential=0, novelty_score=0,
            total_score=0,
        )
        assert s.total_score == 0

    def test_score_bounds_max(self):
        s = ScoredTopic(
            raw=self._raw(),
            trend_momentum=30, gap_score=40, rpm_potential=20, novelty_score=10,
            total_score=100,
        )
        assert s.total_score == 100

    def test_trend_momentum_over_max_rejected(self):
        with pytest.raises(ValidationError):
            ScoredTopic(
                raw=self._raw(),
                trend_momentum=31, gap_score=0, rpm_potential=0, novelty_score=0,
                total_score=31,
            )

    def test_gap_score_over_max_rejected(self):
        with pytest.raises(ValidationError):
            ScoredTopic(
                raw=self._raw(),
                trend_momentum=0, gap_score=41, rpm_potential=0, novelty_score=0,
                total_score=41,
            )

    def test_boundary_70_is_approve(self):
        s = ScoredTopic(
            raw=self._raw(),
            trend_momentum=20, gap_score=30, rpm_potential=15, novelty_score=5,
            total_score=70,
        )
        assert s.action == "approve"

    def test_boundary_50_is_review(self):
        s = ScoredTopic(
            raw=self._raw(),
            trend_momentum=15, gap_score=20, rpm_potential=10, novelty_score=5,
            total_score=50,
        )
        assert s.action == "review"

    def test_boundary_49_is_discard(self):
        s = ScoredTopic(
            raw=self._raw(),
            trend_momentum=14, gap_score=20, rpm_potential=10, novelty_score=5,
            total_score=49,
        )
        assert s.action == "discard"


# === DiscoveryConfig ===


class TestDiscoveryConfig:
    def test_create_minimal(self):
        c = DiscoveryConfig(niche=Niche.FINANCE)
        assert c.niche == Niche.FINANCE
        assert c.markets == []
        assert c.rpm_floor == 7.0

    def test_create_full(self):
        c = DiscoveryConfig(
            niche=Niche.MYTHOLOGY,
            markets=[Market.US, Market.UK],
            competitor_channel_ids=["UC123", "UC456"],
            subreddits=["mythology", "ancientgreece"],
            rss_feeds=["https://example.com/rss"],
            podcast_keywords=["mythology", "greek gods"],
            trends_keywords=["mythology", "ancient history"],
            rpm_floor=12.0,
        )
        assert len(c.competitor_channel_ids) == 2
        assert c.rpm_floor == 12.0

    def test_frozen(self):
        c = DiscoveryConfig(niche=Niche.TECH)
        with pytest.raises(ValidationError):
            c.niche = Niche.HEALTH
