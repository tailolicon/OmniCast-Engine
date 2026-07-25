"""Discovery Orchestrator — run all scanners, score, generate briefs.

Main entry point for the topic discovery pipeline.
"""

from __future__ import annotations

import asyncio
import time
import uuid

import structlog

from omnicast.discovery import shadow_log
from omnicast.discovery.base import BaseScanner
from omnicast.discovery.brief_generator import BriefGenerator
from omnicast.discovery.models import (
    ScoredTopic,
    SourceResult,
    TopicRawData,
)
from omnicast.discovery.news_scanner import NewsScanner
from omnicast.discovery.reddit_scanner import RedditScanner
from omnicast.discovery.scorer import TopicScorer
from omnicast.discovery.trends_scanner import TrendsScanner
from omnicast.discovery.youtube_scanner import YouTubeScanner
from omnicast.models.script import TopicBrief

logger = structlog.get_logger()


class DiscoveryResult:
    """Result of a full discovery run."""

    def __init__(
        self,
        source_results: list[SourceResult],
        scored_topics: list[ScoredTopic],
        briefs: list[TopicBrief],
        review_topics: list[ScoredTopic],
        duration_seconds: float,
    ) -> None:
        self.source_results = source_results
        self.scored_topics = scored_topics
        self.briefs = briefs
        self.review_topics = review_topics
        self.duration_seconds = duration_seconds

    @property
    def approved_count(self) -> int:
        return len(self.briefs)

    @property
    def review_count(self) -> int:
        return len(self.review_topics)

    @property
    def total_raw(self) -> int:
        return sum(r.count for r in self.source_results)

    @property
    def failed_sources(self) -> list[str]:
        return [r.source for r in self.source_results if not r.success]


class DiscoveryOrchestrator:
    """Run full discovery pipeline.

    Pipeline:
    1. Run all scanners in parallel (asyncio.gather)
    2. Collect all TopicRawData from successful results
    3. Score all topics
    4. Generate briefs for auto-approved topics
    5. Collect review topics for Telegram notification
    6. Return DiscoveryResult

    Failed scanners log errors but don't block others.
    """

    def __init__(
        self,
        scanners: list[BaseScanner],
        scorer: TopicScorer,
        brand_voice: str = "",
        channel=None,  # ChannelProfile | None
    ) -> None:
        self.scanners = scanners
        self.scorer = scorer
        self.brand_voice = brand_voice
        # Set per run; carried on the instance so the API layer can mark which
        # topics the real router selected (see shadow_log.mark_selected).
        self.run_id = ""
        self.shadow_rows: list[dict] = []
        self.channel = channel

    @classmethod
    def for_channel(cls, channel) -> "DiscoveryOrchestrator":
        """Build orchestrator from channel profile."""
        from omnicast.config.channel import ChannelProfile
        if not isinstance(channel, ChannelProfile):
            raise TypeError("channel must be a ChannelProfile")

        from omnicast.config.settings import get_settings
        settings = get_settings()

        config = channel.to_discovery_config()
        scanners = []
        if config.rss_feeds:
            scanners.append(NewsScanner(config=config))
        if config.trends_keywords:
            scanners.append(TrendsScanner(config=config))
        if config.has_youtube_targets and settings.youtube_api_key:
            scanners.append(YouTubeScanner(config=config, api_key=settings.youtube_api_key))
        elif config.has_youtube_targets and not settings.youtube_api_key:
            logger.warning("YouTube competitors configured but YOUTUBE_API_KEY missing — skipping")
        if config.subreddits:
            scanners.append(RedditScanner(config=config))
        # P0.1 group 3: `TopicScorer()` with no profile made stack fit return a
        # constant 7.5 on every production run — a dimension worth 15 points
        # that could not move. The profile is derived from config that already
        # exists, so this changes behaviour on channels nobody has to re-edit.
        from omnicast.analytics.pillars import load_pillars
        from omnicast.discovery.opportunity import AudienceProfile

        scorer = TopicScorer(
            stack_profile=channel.to_stack_profile(),
            # §3.1: audience fit and repeatability read configuration that has
            # existed on ChannelProfile for months and that nothing scored.
            audience_profile=AudienceProfile.from_channel(channel),
            pillars=load_pillars(getattr(channel, "content_pillars", None)),
        )
        # `channel` was also dropped here, which silently disabled every
        # per-channel policy downstream: BriefGenerator received None, so
        # `competitor_intel_required` (put on ChannelProfile precisely to make
        # the fail-closed branch reachable) was never read on this path, and
        # every shadow-corpus row was written with an empty channel_id.
        return cls(scanners=scanners, scorer=scorer,
                   brand_voice=channel.brand_voice, channel=channel)

    async def run(self) -> DiscoveryResult:
        """Execute full discovery pipeline."""
        start = time.time()
        self.run_id = uuid.uuid4().hex[:12]

        # 1. Run all scanners in parallel
        source_results: list[SourceResult] = await asyncio.gather(
            *[s.scan() for s in self.scanners]
        )

        # 2. Collect raw topics from successful scans
        all_raw: list[TopicRawData] = []
        for result in source_results:
            if result.success:
                all_raw.extend(result.topics)

        # 3. Score
        scored = await self.scorer.score_batch(all_raw)

        # 3b. Persist the shadow corpus. Without this, v2's score exists only on
        # an in-memory object for the length of one request, and the calibration
        # that gates promoting v2 has nothing to run on.
        self.shadow_rows = shadow_log.rows_for_run(
            scored,
            channel_id=getattr(self.channel, "channel_id", "") if self.channel else "",
            run_id=self.run_id,
        )
        await asyncio.to_thread(shadow_log.append_rows, self.shadow_rows)

        # 4. Generate briefs for approved
        briefs = BriefGenerator.generate_batch(scored, self.brand_voice, self.channel)

        # 5. Collect review topics
        review = [s for s in scored if s.action == "review"]

        duration = time.time() - start

        logger.info(
            "Discovery complete",
            total_raw=len(all_raw),
            approved=len(briefs),
            review=len(review),
            discarded=len(scored) - len(briefs) - len(review),
            failed_sources=[r.source for r in source_results if not r.success],
            duration_s=round(duration, 2),
        )

        return DiscoveryResult(
            source_results=source_results,
            scored_topics=scored,
            briefs=briefs,
            review_topics=review,
            duration_seconds=round(duration, 2),
        )
