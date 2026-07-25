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
    # Narrowed from 40 to 25 when gap stopped re-reading outlier_ratio (which
    # trend_momentum already scores) and the freed budget moved to stack_fit.
    gap_score: float = Field(ge=0, le=25)
    rpm_potential: float = Field(ge=0, le=20)
    novelty_score: float = Field(ge=0, le=10)
    # Can WE make this well? Demand for a topic we cannot produce is not value.
    stack_fit: float = Field(ge=0, le=15, default=0.0)
    # v2 revision 2 (brief §3.1): the rest of the opportunity formula.
    # Is it for OUR audience; can it become a series; what does it expose us to.
    audience_fit: float = Field(ge=0, le=10, default=0.0)
    repeatability: float = Field(ge=0, le=10, default=0.0)
    risk_penalty: float = Field(ge=0, le=40, default=0.0)
    total_score: float = Field(ge=0, le=100)
    # Human-readable reasons for the stack_fit verdict — a topic rejected for
    # fit should say which constraint it hit.
    score_notes: list[str] = Field(default_factory=list)

    # === Shadow scoring ===
    # v2 changed the dimension budget (gap 40→25, +stack_fit 15) and stopped
    # double-counting outlier_ratio. That shifts the approve/review boundary by
    # up to ~20 points for YouTube-sourced topics, in a direction that depends on
    # the competitor's channel size. Until the shift is calibrated against
    # labelled topics, BOTH scores ride along on every topic and the active
    # generation is a setting, not an assumption.
    scoring_version: str = "v2"          # which generation decided the flags below
    total_score_v1: float = Field(ge=0, le=100, default=0.0)
    total_score_v2: float = Field(ge=0, le=100, default=0.0)
    gap_score_v1: float = Field(ge=0, le=40, default=0.0)
    # Which COMPOSITION of v2 produced total_score_v2. Rows from two revisions
    # describe different functions; calibrating on a mixture would fit a scorer
    # that never ran.
    scoring_v2_revision: int = 1

    @property
    def shadow_delta(self) -> float:
        """v2 minus v1. Positive = v2 is more generous on this topic."""
        return round(self.total_score_v2 - self.total_score_v1, 2)

    @property
    def shadow_disagrees(self) -> bool:
        """Would the two generations route this topic differently?"""
        def action_of(total: float) -> str:
            return "approve" if total >= 70 else "review" if total >= 50 else "discard"

        return action_of(self.total_score_v1) != action_of(self.total_score_v2)
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
