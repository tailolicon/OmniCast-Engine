"""Generate TopicBrief from scored topics.

Converts ScoredTopic → TopicBrief (input for Writer Agent).
"""

from __future__ import annotations

import structlog

from omnicast.discovery.models import ScoredTopic
from omnicast.models.script import TopicBrief
from omnicast.models.enums import TopicSource
from omnicast.config.niches import get_niche_config

logger = structlog.get_logger()


class BriefGenerator:
    """Convert approved ScoredTopics into TopicBriefs for the writing pipeline.

    Determines angle based on source type:
    - YOUTUBE_COMPETITOR → "Competitor analysis" angle
    - GOOGLE_TRENDS → "Trending now" angle
    - REDDIT → "Community discussion" angle
    - PODCAST → "Deep dive" angle
    - NEWS_RSS → "Breaking news" angle
    """

    @staticmethod
    def generate(scored: ScoredTopic, brand_voice: str = "", channel=None) -> TopicBrief:
        """Convert ScoredTopic to TopicBrief.

        - title from scored.raw.title
        - angle from source type (or niche-aware if channel provided)
        - key_points from raw_metrics (extract relevant data points)
        - source_urls from scored.raw.source_url
        - target_duration_min = 10 (default)
        - channel_id and sub_niche from channel if provided
        """
        from omnicast.config.channel import ChannelProfile

        # Get niche config if channel provided
        niche_cfg = None
        if channel and isinstance(channel, ChannelProfile):
            niche_cfg = get_niche_config(channel.niche.value, channel.sub_niche)

        angle = BriefGenerator._determine_angle(scored, niche_cfg)
        key_points = BriefGenerator._extract_key_points(scored)
        source_urls = [scored.raw.source_url] if scored.raw.source_url else []

        channel_id = channel.channel_id if channel else ""
        sub_niche = channel.sub_niche if channel else ""
        target_duration = channel.target_duration_min if channel else 10
        intel_required = bool(getattr(channel, "competitor_intel_required", False))

        return TopicBrief(
            title=scored.raw.title,
            niche=scored.raw.niche,
            market=scored.raw.market,
            source=scored.raw.source,
            angle=angle,
            key_points=key_points,
            source_urls=source_urls,
            target_duration_min=target_duration,
            brand_voice=brand_voice,
            channel_id=channel_id,
            sub_niche=sub_niche,
            competitor_intel_required=intel_required,
        )

    @staticmethod
    def generate_batch(
        scored_topics: list[ScoredTopic],
        brand_voice: str = "",
        channel=None,
    ) -> list[TopicBrief]:
        """Generate briefs for all approved topics (action == 'approve')."""
        return [
            BriefGenerator.generate(s, brand_voice, channel)
            for s in scored_topics
            if s.action == "approve"
        ]

    @staticmethod
    def _determine_angle(scored: ScoredTopic, niche_cfg=None) -> str:
        """Map source type to default angle suggestion, with niche-aware enhancement."""
        source = scored.raw.source

        angles = {
            TopicSource.YOUTUBE_COMPETITOR: "Competitor analysis - analyze what worked and improve",
            TopicSource.GOOGLE_TRENDS: "Trending now - capitalize on current search interest",
            TopicSource.REDDIT: "Community discussion - explore popular talking points",
            TopicSource.PODCAST: "Deep dive - convert audio content to video format",
            TopicSource.NEWS_RSS: "Breaking news - timely coverage of current events",
        }

        base_angle = angles.get(source, "General topic exploration")

        # Enhance angle with niche-specific context if available
        if niche_cfg:
            return f"{base_angle}. Niche angle: {niche_cfg.insider_angle}"

        return base_angle

    @staticmethod
    def _extract_key_points(scored: ScoredTopic) -> list[str]:
        """Extract key talking points from raw_metrics."""
        metrics = scored.raw.raw_metrics or {}
        source = scored.raw.source
        points = []

        if source == TopicSource.YOUTUBE_COMPETITOR:
            if "views" in metrics:
                points.append(f"Competitor video has {metrics['views']:,} views")
            if "outlier_ratio" in metrics:
                points.append(f"Outlier ratio: {metrics['outlier_ratio']:.1f}x median")
        elif source == TopicSource.GOOGLE_TRENDS:
            if "growth_pct" in metrics:
                points.append(f"Search interest grew {metrics['growth_pct']}% in 7 days")
            if "keyword" in metrics:
                points.append(f"Related to keyword: {metrics['keyword']}")
        elif source == TopicSource.REDDIT:
            if "score" in metrics:
                points.append(f"Post score: {metrics['score']}")
            if "comments" in metrics:
                points.append(f"Comments: {metrics['comments']}")
            if "subreddit" in metrics:
                points.append(f"From r/{metrics['subreddit']}")
        elif source == TopicSource.PODCAST:
            if "listen_score" in metrics:
                points.append(f"Listen score: {metrics['listen_score']}")
            if "podcast_title" in metrics:
                points.append(f"From podcast: {metrics['podcast_title']}")
        elif source == TopicSource.NEWS_RSS:
            if "mention_count" in metrics:
                points.append(f"Mentioned in {metrics['mention_count']} articles in 24h")
            if "hours_since_first" in metrics:
                points.append(f"Trending for {metrics['hours_since_first']:.1f} hours")

        return points
