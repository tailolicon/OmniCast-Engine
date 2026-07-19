"""Pydantic models for Topic Discovery Engine.

All frozen (immutable), inherit OmnicastSchema.
"""

from __future__ import annotations

from datetime import datetime, timezone

from pydantic import Field

from omnicast.models.schemas import OmnicastSchema
from omnicast.models.enums import Niche, Market, TopicSource


class TopicRawData(OmnicastSchema):
    """Raw topic data from a single source before scoring.

    Each scanner produces a list of these.
    """
    title: str
    description: str = ""
    source: TopicSource
    niche: Niche
    market: Market
    source_url: str = ""
    raw_metrics: dict = Field(default_factory=dict)
    # raw_metrics examples:
    #   YouTube: {"views": 500000, "channel_median": 50000, "outlier_ratio": 10.0}
    #   Trends: {"growth_pct": 250, "interest_score": 85}
    #   Reddit: {"score": 1200, "comments": 89, "upvote_ratio": 0.95}
    #   Podcast: {"listen_score": 82}
    #   News: {"mention_count": 15, "hours_since_first": 12}
    extracted_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class SourceResult(OmnicastSchema):
    """Result from one scanner run. Wraps list of TopicRawData + metadata."""
    source: TopicSource
    topics: list[TopicRawData] = Field(default_factory=list)
    scan_duration_seconds: float = 0.0
    error: str | None = None
    scanned_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def success(self) -> bool:
        return self.error is None

    @property
    def count(self) -> int:
        return len(self.topics)


class ScoredTopic(OmnicastSchema):
    """Topic after scoring (0-100). Ready for threshold check."""
    raw: TopicRawData
    trend_momentum: float = Field(ge=0, le=30)
    gap_score: float = Field(ge=0, le=40)
    rpm_potential: float = Field(ge=0, le=20)
    novelty_score: float = Field(ge=0, le=10)
    total_score: float = Field(ge=0, le=100)
    auto_approved: bool = False       # total >= 70
    needs_review: bool = False        # 50 <= total < 70

    @property
    def action(self) -> str:
        """Return 'approve', 'review', or 'discard'."""
        if self.total_score >= 70:
            return "approve"
        if self.total_score >= 50:
            return "review"
        return "discard"


class DiscoveryConfig(OmnicastSchema):
    """Per-niche discovery configuration."""
    niche: Niche
    markets: list[Market] = Field(default_factory=list)
    competitor_handles: list[str] = Field(default_factory=list)   # YouTube @handles
    competitor_channel_ids: list[str] = Field(default_factory=list)  # raw IDs (legacy)
    subreddits: list[str] = Field(default_factory=list)
    rss_feeds: list[str] = Field(default_factory=list)
    podcast_keywords: list[str] = Field(default_factory=list)
    trends_keywords: list[str] = Field(default_factory=list)
    rpm_floor: float = 7.0

    @property
    def has_youtube_targets(self) -> bool:
        return bool(self.competitor_handles or self.competitor_channel_ids)
