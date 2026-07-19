"""Topic scoring engine.

Scores raw topics 0-100 across 4 dimensions:
- Trend Momentum: 0-30 (growth rate from raw_metrics)
- Gap Score: 0-40 (competition level — fewer quality videos = higher gap)
- RPM Potential: 0-20 (market RPM floor)
- Novelty vs KB: 0-10 (ChromaDB similarity check, decay-aware)

Thresholds:
  >= 70: auto_approved
  50-69: needs_review (Telegram alert)
  < 50:  discard
"""

from __future__ import annotations

import structlog

from omnicast.discovery.models import TopicRawData, ScoredTopic
from omnicast.models.enums import Market, TopicSource

logger = structlog.get_logger()

# RPM floor by market (USD)
MARKET_RPM: dict[Market, float] = {
    Market.US: 15.0,
    Market.UK: 12.0,
    Market.AU: 10.0,
    Market.CA: 10.0,
    Market.JP: 8.0,
    Market.KR: 7.0,
}


class TopicScorer:
    """Score raw topics using 4 dimensions.

    kb_client is optional. If None, novelty_score defaults to 5 (neutral).
    """

    def __init__(self, kb_client=None) -> None:
        """
        kb_client: KBClient instance for novelty check.
        If None, skip novelty check (novelty_score = 5).
        """
        self._kb = kb_client

    async def score(self, topic: TopicRawData) -> ScoredTopic:
        """Score a single topic across all 4 dimensions."""
        trend = self._calc_trend_momentum(topic)
        gap = self._calc_gap_score(topic)
        rpm = self._calc_rpm_potential(topic.market)
        novelty = await self._calc_novelty(topic)
        total = trend + gap + rpm + novelty

        return ScoredTopic(
            raw=topic,
            trend_momentum=trend,
            gap_score=gap,
            rpm_potential=rpm,
            novelty_score=novelty,
            total_score=min(total, 100),
            auto_approved=total >= 70,
            needs_review=50 <= total < 70,
        )

    async def score_batch(self, topics: list[TopicRawData]) -> list[ScoredTopic]:
        """Score multiple topics. Return sorted by total_score descending."""
        scored = [await self.score(t) for t in topics]
        return sorted(scored, key=lambda s: s.total_score, reverse=True)

    @staticmethod
    def _calc_trend_momentum(topic: TopicRawData) -> float:
        """Calculate trend momentum (0-30).

        Heuristics by source:
        - YOUTUBE_COMPETITOR: outlier_ratio → min(ratio * 3, 30)
        - GOOGLE_TRENDS: growth_pct → min(growth_pct / 10, 30)
        - REDDIT: (score / 100) → min(score_norm, 30)
        - PODCAST: listen_score → min((listen_score - 50) * 0.6, 30)
        - NEWS_RSS: mention_count → min(mention_count * 2, 30)
        """
        metrics = topic.raw_metrics or {}
        source = topic.source

        if source == TopicSource.YOUTUBE_COMPETITOR:
            ratio = metrics.get("outlier_ratio", 0)
            return min(ratio * 3, 30)
        elif source == TopicSource.GOOGLE_TRENDS:
            growth = metrics.get("growth_pct", 0)
            return min(growth / 10, 30)
        elif source == TopicSource.REDDIT:
            score = metrics.get("score", 0)
            return min(score / 100, 30)
        elif source == TopicSource.PODCAST:
            listen_score = metrics.get("listen_score", 50)
            return min((listen_score - 50) * 0.6, 30)
        elif source == TopicSource.NEWS_RSS:
            mentions = metrics.get("mention_count", 0)
            return min(mentions * 2, 30)
        else:
            return 0

    @staticmethod
    def _calc_gap_score(topic: TopicRawData) -> float:
        """Calculate gap score (0-40).

        YouTube outliers = validated demand signal. Gap score scales with outlier_ratio:
        - ratio 2.5-4x  → 20 (proven topic, moderate competition)
        - ratio 4-8x    → 28 (hot topic, high demand)
        - ratio >8x     → 35 (viral-level demand)

        Other sources:
        - GOOGLE_TRENDS: 25
        - REDDIT: 30 (often no video coverage yet)
        - PODCAST: 35 (podcast→video conversion is high gap)
        - NEWS_RSS: 20
        """
        source = topic.source
        metrics = topic.raw_metrics or {}

        if source == TopicSource.YOUTUBE_COMPETITOR:
            ratio = metrics.get("outlier_ratio", 0)
            if ratio >= 8:
                return 35
            elif ratio >= 4:
                return 28
            else:
                return 20  # minimum for any outlier that passed the filter

        gap_scores = {
            TopicSource.GOOGLE_TRENDS: 25,
            TopicSource.REDDIT: 30,
            TopicSource.PODCAST: 35,
            TopicSource.NEWS_RSS: 20,
        }

        return gap_scores.get(source, 10)

    @staticmethod
    def _calc_rpm_potential(market: Market) -> float:
        """Calculate RPM potential (0-20).

        = min(MARKET_RPM[market], 20)
        """
        return min(MARKET_RPM.get(market, 7.0), 20.0)

    async def _calc_novelty(self, topic: TopicRawData) -> float:
        """Calculate novelty vs knowledge base (0-10).

        If kb_client is None → return 5 (neutral).
        Otherwise:
        - Query KB "scripts" collection with topic.title
        - If best match similarity > 0.85 → 0 (duplicate)
        - If similarity 0.7-0.85 → 3 (related)
        - If similarity < 0.7 → 10 (novel)
        """
        if self._kb is None:
            return 5

        try:
            result = await self._kb.query(
                collection="scripts",
                query_text=topic.title,
                n_results=1,
            )

            if not result or not result.get("distances"):
                return 10  # No matches = novel

            distance = result["distances"][0][0]
            similarity = 1 - distance

            if similarity > 0.85:
                return 0  # Duplicate
            elif similarity >= 0.7:
                return 3  # Related
            else:
                return 10  # Novel

        except Exception as exc:
            logger.warning(
                "Novelty check failed",
                topic=topic.title,
                error=str(exc),
            )
            return 5  # Neutral on error
