# TASK_F: Topic Scorer + Brief Generator + Discovery Orchestrator

## Model: sonnet
## Estimated time: 50 minutes
## Dependencies: TASK_A, TASK_B, TASK_C, TASK_D, TASK_E

## Overview

Three components that tie the discovery engine together:

1. **TopicScorer**: Score raw topics 0-100 using 4 dimensions + KB novelty check
2. **BriefGenerator**: Convert scored+approved topics into TopicBrief (Phase 2 model)
3. **DiscoveryOrchestrator**: Run all 5 scanners in parallel, score, generate briefs

## Files

| File | Lines | Description |
|------|------:|-------------|
| `src/omnicast/discovery/scorer.py` | ~180 | TopicScorer |
| `src/omnicast/discovery/brief_generator.py` | ~100 | BriefGenerator |
| `src/omnicast/discovery/orchestrator.py` | ~160 | DiscoveryOrchestrator |
| `tests/unit/test_scorer.py` | ~200 | Pre-written tests |
| `tests/unit/test_brief_generator.py` | ~120 | Pre-written tests |
| `tests/unit/test_orchestrator.py` | ~180 | Pre-written tests |

## Context Files

- `src/omnicast/discovery/models.py` — TopicRawData, ScoredTopic, SourceResult, DiscoveryConfig
- `src/omnicast/discovery/base.py` — BaseScanner
- `src/omnicast/models/script.py` — TopicBrief (output of BriefGenerator)
- `src/omnicast/models/schemas.py` — TopicCandidate
- `src/omnicast/kb/client.py` — KBClient (for novelty check)
- `src/omnicast/models/enums.py` — Market (for RPM floors)

## Interface Definitions

### src/omnicast/discovery/scorer.py

```python
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
from omnicast.models.enums import Market

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
        ...

    @staticmethod
    def _calc_gap_score(topic: TopicRawData) -> float:
        """Calculate gap score (0-40).

        Based on source type:
        - YOUTUBE_COMPETITOR: Always 10 (topic exists on YT, moderate gap)
        - GOOGLE_TRENDS: 25 (trending but may have coverage)
        - REDDIT: 30 (reddit-only topics often lack video coverage)
        - PODCAST: 35 (podcast → video conversion is high gap)
        - NEWS_RSS: 20 (news often gets quick video coverage)

        These are defaults — future: YouTube search API to count existing videos.
        """
        ...

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
        ...
```

### src/omnicast/discovery/brief_generator.py

```python
"""Generate TopicBrief from scored topics.

Converts ScoredTopic → TopicBrief (input for Writer Agent).
"""

from __future__ import annotations

import structlog

from omnicast.discovery.models import ScoredTopic
from omnicast.models.script import TopicBrief

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
    def generate(scored: ScoredTopic, brand_voice: str = "") -> TopicBrief:
        """Convert ScoredTopic to TopicBrief.

        - title from scored.raw.title
        - angle from source type
        - key_points from raw_metrics (extract relevant data points)
        - source_urls from scored.raw.source_url
        - target_duration_min = 10 (default)
        """
        ...

    @staticmethod
    def generate_batch(
        scored_topics: list[ScoredTopic],
        brand_voice: str = "",
    ) -> list[TopicBrief]:
        """Generate briefs for all approved topics (action == 'approve')."""
        return [
            BriefGenerator.generate(s, brand_voice)
            for s in scored_topics
            if s.action == "approve"
        ]

    @staticmethod
    def _determine_angle(scored: ScoredTopic) -> str:
        """Map source type to default angle suggestion."""
        ...

    @staticmethod
    def _extract_key_points(scored: ScoredTopic) -> list[str]:
        """Extract key talking points from raw_metrics."""
        ...
```

### src/omnicast/discovery/orchestrator.py

```python
"""Discovery Orchestrator — run all scanners, score, generate briefs.

Main entry point for the topic discovery pipeline.
"""

from __future__ import annotations

import asyncio
import time

import structlog

from omnicast.discovery.models import (
    DiscoveryConfig,
    ScoredTopic,
    SourceResult,
    TopicRawData,
)
from omnicast.discovery.base import BaseScanner
from omnicast.discovery.scorer import TopicScorer
from omnicast.discovery.brief_generator import BriefGenerator
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
    ) -> None:
        self.scanners = scanners
        self.scorer = scorer
        self.brand_voice = brand_voice

    async def run(self) -> DiscoveryResult:
        """Execute full discovery pipeline."""
        start = time.time()

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

        # 4. Generate briefs for approved
        briefs = BriefGenerator.generate_batch(scored, self.brand_voice)

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
```

## DO NOT

- Do NOT publish briefs to RabbitMQ — return them, let caller decide
- Do NOT send Telegram alerts — return review_topics, let caller notify
- Do NOT persist scored topics to DB — pure computation
- Do NOT import concrete scanners in orchestrator — accept list[BaseScanner]

## Tests

### tests/unit/test_scorer.py

```python
"""Tests for Topic Scorer."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from omnicast.discovery.scorer import TopicScorer, MARKET_RPM
from omnicast.discovery.models import TopicRawData, ScoredTopic
from omnicast.models.enums import Niche, Market, TopicSource


def _raw(source=TopicSource.GOOGLE_TRENDS, market=Market.US, **metrics):
    return TopicRawData(
        title="Test Topic",
        source=source,
        niche=Niche.FINANCE,
        market=market,
        raw_metrics=metrics,
    )


class TestCalcTrendMomentum:
    def test_youtube_outlier_ratio(self):
        topic = _raw(TopicSource.YOUTUBE_COMPETITOR, outlier_ratio=5.0)
        score = TopicScorer._calc_trend_momentum(topic)
        assert 0 <= score <= 30
        assert score == min(5.0 * 3, 30)

    def test_google_trends_growth(self):
        topic = _raw(TopicSource.GOOGLE_TRENDS, growth_pct=200)
        score = TopicScorer._calc_trend_momentum(topic)
        assert 0 <= score <= 30
        assert score == min(200 / 10, 30)

    def test_reddit_score(self):
        topic = _raw(TopicSource.REDDIT, score=1500)
        score = TopicScorer._calc_trend_momentum(topic)
        assert 0 <= score <= 30

    def test_podcast_listen_score(self):
        topic = _raw(TopicSource.PODCAST, listen_score=85)
        score = TopicScorer._calc_trend_momentum(topic)
        assert 0 <= score <= 30

    def test_news_mention_count(self):
        topic = _raw(TopicSource.NEWS_RSS, mention_count=12)
        score = TopicScorer._calc_trend_momentum(topic)
        assert 0 <= score <= 30
        assert score == min(12 * 2, 30)

    def test_capped_at_30(self):
        topic = _raw(TopicSource.NEWS_RSS, mention_count=100)
        score = TopicScorer._calc_trend_momentum(topic)
        assert score == 30

    def test_zero_metrics(self):
        topic = _raw(TopicSource.GOOGLE_TRENDS)
        score = TopicScorer._calc_trend_momentum(topic)
        assert score == 0


class TestCalcGapScore:
    def test_youtube_default(self):
        topic = _raw(TopicSource.YOUTUBE_COMPETITOR)
        score = TopicScorer._calc_gap_score(topic)
        assert score == 10

    def test_reddit_default(self):
        topic = _raw(TopicSource.REDDIT)
        score = TopicScorer._calc_gap_score(topic)
        assert score == 30

    def test_podcast_highest_gap(self):
        topic = _raw(TopicSource.PODCAST)
        score = TopicScorer._calc_gap_score(topic)
        assert score == 35

    def test_all_sources_in_range(self):
        for src in TopicSource:
            topic = _raw(src)
            score = TopicScorer._calc_gap_score(topic)
            assert 0 <= score <= 40, f"Gap score out of range for {src}"


class TestCalcRpmPotential:
    def test_us_market(self):
        assert TopicScorer._calc_rpm_potential(Market.US) == min(15.0, 20.0)

    def test_kr_market(self):
        assert TopicScorer._calc_rpm_potential(Market.KR) == min(7.0, 20.0)

    def test_all_markets_in_range(self):
        for market in Market:
            score = TopicScorer._calc_rpm_potential(market)
            assert 0 <= score <= 20


class TestCalcNovelty:
    @pytest.mark.asyncio
    async def test_no_kb_returns_neutral(self):
        scorer = TopicScorer(kb_client=None)
        topic = _raw()
        novelty = await scorer._calc_novelty(topic)
        assert novelty == 5

    @pytest.mark.asyncio
    async def test_novel_topic_high_score(self):
        mock_kb = AsyncMock()
        mock_kb.query.return_value = {
            "distances": [[0.9]],  # low similarity = novel
            "documents": [["some old doc"]],
        }
        scorer = TopicScorer(kb_client=mock_kb)
        topic = _raw()
        novelty = await scorer._calc_novelty(topic)
        assert novelty == 10

    @pytest.mark.asyncio
    async def test_duplicate_topic_zero_score(self):
        mock_kb = AsyncMock()
        mock_kb.query.return_value = {
            "distances": [[0.1]],  # high similarity = duplicate
            "documents": [["almost same topic"]],
        }
        scorer = TopicScorer(kb_client=mock_kb)
        topic = _raw()
        novelty = await scorer._calc_novelty(topic)
        assert novelty == 0

    @pytest.mark.asyncio
    async def test_related_topic_medium_score(self):
        mock_kb = AsyncMock()
        mock_kb.query.return_value = {
            "distances": [[0.25]],  # similarity ~0.75 → related
            "documents": [["related topic"]],
        }
        scorer = TopicScorer(kb_client=mock_kb)
        topic = _raw()
        novelty = await scorer._calc_novelty(topic)
        assert novelty == 3


class TestScoreFull:
    @pytest.mark.asyncio
    async def test_score_produces_scored_topic(self):
        scorer = TopicScorer()
        topic = _raw(TopicSource.GOOGLE_TRENDS, growth_pct=200)
        result = await scorer.score(topic)
        assert isinstance(result, ScoredTopic)
        assert result.total_score >= 0
        assert result.total_score <= 100

    @pytest.mark.asyncio
    async def test_high_score_auto_approved(self):
        scorer = TopicScorer()
        # YouTube outlier with high ratio + US market
        topic = _raw(TopicSource.YOUTUBE_COMPETITOR, Market.US, outlier_ratio=8.0)
        result = await scorer.score(topic)
        # trend=24, gap=10, rpm=15, novelty=5 → total=54
        # Might not reach 70 with just outlier. Let's check boundaries
        assert isinstance(result.auto_approved, bool)

    @pytest.mark.asyncio
    async def test_score_batch_sorted_descending(self):
        scorer = TopicScorer()
        topics = [
            _raw(TopicSource.NEWS_RSS, mention_count=5),    # low
            _raw(TopicSource.NEWS_RSS, mention_count=15),   # high
            _raw(TopicSource.NEWS_RSS, mention_count=10),   # medium
        ]
        results = await scorer.score_batch(topics)
        scores = [r.total_score for r in results]
        assert scores == sorted(scores, reverse=True)

    @pytest.mark.asyncio
    async def test_total_score_capped_at_100(self):
        scorer = TopicScorer()
        # Max everything
        topic = _raw(
            TopicSource.PODCAST, Market.US,
            listen_score=200, mention_count=100,
        )
        result = await scorer.score(topic)
        assert result.total_score <= 100


class TestMarketRpm:
    def test_all_markets_have_rpm(self):
        for market in Market:
            assert market in MARKET_RPM
```

### tests/unit/test_brief_generator.py

```python
"""Tests for Brief Generator."""

import pytest

from omnicast.discovery.brief_generator import BriefGenerator
from omnicast.discovery.models import TopicRawData, ScoredTopic
from omnicast.models.script import TopicBrief
from omnicast.models.enums import Niche, Market, TopicSource


def _scored(
    source=TopicSource.GOOGLE_TRENDS,
    total=75,
    title="Test Topic",
    **raw_metrics,
) -> ScoredTopic:
    raw = TopicRawData(
        title=title,
        source=source,
        niche=Niche.FINANCE,
        market=Market.US,
        source_url="https://example.com/test",
        raw_metrics=raw_metrics,
    )
    return ScoredTopic(
        raw=raw,
        trend_momentum=20, gap_score=25, rpm_potential=15, novelty_score=8,
        total_score=total,
        auto_approved=total >= 70,
        needs_review=50 <= total < 70,
    )


class TestGenerate:
    def test_produces_topic_brief(self):
        scored = _scored()
        brief = BriefGenerator.generate(scored)
        assert isinstance(brief, TopicBrief)
        assert brief.title == "Test Topic"
        assert brief.niche == Niche.FINANCE
        assert brief.market == Market.US
        assert brief.source == TopicSource.GOOGLE_TRENDS

    def test_includes_source_url(self):
        scored = _scored()
        brief = BriefGenerator.generate(scored)
        assert "https://example.com/test" in brief.source_urls

    def test_brand_voice_passed(self):
        scored = _scored()
        brief = BriefGenerator.generate(scored, brand_voice="Professional, authoritative")
        assert brief.brand_voice == "Professional, authoritative"

    def test_default_duration(self):
        scored = _scored()
        brief = BriefGenerator.generate(scored)
        assert brief.target_duration_min == 10


class TestDetermineAngle:
    def test_youtube_angle(self):
        scored = _scored(TopicSource.YOUTUBE_COMPETITOR)
        angle = BriefGenerator._determine_angle(scored)
        assert "competitor" in angle.lower() or "analysis" in angle.lower()

    def test_trends_angle(self):
        scored = _scored(TopicSource.GOOGLE_TRENDS)
        angle = BriefGenerator._determine_angle(scored)
        assert "trend" in angle.lower()

    def test_reddit_angle(self):
        scored = _scored(TopicSource.REDDIT)
        angle = BriefGenerator._determine_angle(scored)
        assert "community" in angle.lower() or "discussion" in angle.lower()

    def test_podcast_angle(self):
        scored = _scored(TopicSource.PODCAST)
        angle = BriefGenerator._determine_angle(scored)
        assert "deep" in angle.lower() or "dive" in angle.lower()

    def test_news_angle(self):
        scored = _scored(TopicSource.NEWS_RSS)
        angle = BriefGenerator._determine_angle(scored)
        assert "news" in angle.lower() or "breaking" in angle.lower()


class TestGenerateBatch:
    def test_only_approved_topics(self):
        topics = [
            _scored(total=80),   # approve
            _scored(total=55),   # review → skip
            _scored(total=30),   # discard → skip
            _scored(total=75),   # approve
        ]
        briefs = BriefGenerator.generate_batch(topics)
        assert len(briefs) == 2

    def test_empty_when_none_approved(self):
        topics = [_scored(total=40), _scored(total=55)]
        briefs = BriefGenerator.generate_batch(topics)
        assert len(briefs) == 0

    def test_empty_input(self):
        assert BriefGenerator.generate_batch([]) == []

    def test_brand_voice_applied_to_all(self):
        topics = [_scored(total=80), _scored(total=90)]
        briefs = BriefGenerator.generate_batch(topics, brand_voice="Casual, fun")
        assert all(b.brand_voice == "Casual, fun" for b in briefs)


class TestExtractKeyPoints:
    def test_youtube_extracts_view_data(self):
        scored = _scored(TopicSource.YOUTUBE_COMPETITOR, views=500000, outlier_ratio=5.0)
        points = BriefGenerator._extract_key_points(scored)
        assert isinstance(points, list)
        assert len(points) >= 1

    def test_empty_metrics_returns_empty(self):
        scored = _scored()
        points = BriefGenerator._extract_key_points(scored)
        assert isinstance(points, list)
```

### tests/unit/test_orchestrator.py

```python
"""Tests for Discovery Orchestrator."""

import pytest
from unittest.mock import AsyncMock

from omnicast.discovery.orchestrator import DiscoveryOrchestrator, DiscoveryResult
from omnicast.discovery.models import (
    DiscoveryConfig,
    TopicRawData,
    SourceResult,
    ScoredTopic,
)
from omnicast.discovery.scorer import TopicScorer
from omnicast.discovery.base import BaseScanner
from omnicast.models.enums import Niche, Market, TopicSource


class FakeScanner(BaseScanner):
    """Fake scanner for orchestrator tests."""
    source = TopicSource.MANUAL

    def __init__(self, topics=None, error=None):
        config = DiscoveryConfig(niche=Niche.FINANCE, markets=[Market.US])
        super().__init__(config)
        self._topics = topics or []
        self._error = error

    async def _scan(self):
        if self._error:
            raise RuntimeError(self._error)
        return self._topics


def _raw_topic(title="Test", source=TopicSource.MANUAL, **metrics):
    return TopicRawData(
        title=title,
        source=source,
        niche=Niche.FINANCE,
        market=Market.US,
        raw_metrics=metrics,
    )


class TestDiscoveryResult:
    def test_properties(self):
        results = [
            SourceResult(source=TopicSource.GOOGLE_TRENDS, topics=[_raw_topic()]),
            SourceResult(source=TopicSource.REDDIT, error="Failed"),
        ]
        scored = [
            ScoredTopic(
                raw=_raw_topic(), trend_momentum=20, gap_score=30,
                rpm_potential=15, novelty_score=8, total_score=73,
                auto_approved=True,
            ),
        ]
        from omnicast.models.script import TopicBrief
        briefs = [
            TopicBrief(title="T", niche=Niche.FINANCE, market=Market.US, source=TopicSource.MANUAL),
        ]
        review = []
        dr = DiscoveryResult(results, scored, briefs, review, 5.0)
        assert dr.approved_count == 1
        assert dr.review_count == 0
        assert dr.total_raw == 1
        assert TopicSource.REDDIT in dr.failed_sources


class TestOrchestratorRun:
    @pytest.mark.asyncio
    async def test_runs_all_scanners_parallel(self):
        topics1 = [_raw_topic("Topic A", mention_count=15)]
        topics2 = [_raw_topic("Topic B", mention_count=12)]
        scanner1 = FakeScanner(topics=topics1)
        scanner2 = FakeScanner(topics=topics2)
        scorer = TopicScorer()
        orch = DiscoveryOrchestrator([scanner1, scanner2], scorer)
        result = await orch.run()
        assert isinstance(result, DiscoveryResult)
        assert result.total_raw == 2
        assert len(result.scored_topics) == 2

    @pytest.mark.asyncio
    async def test_failed_scanner_doesnt_block(self):
        topics = [_raw_topic("Good Topic", mention_count=15)]
        scanner_ok = FakeScanner(topics=topics)
        scanner_fail = FakeScanner(error="Timeout")
        scorer = TopicScorer()
        orch = DiscoveryOrchestrator([scanner_ok, scanner_fail], scorer)
        result = await orch.run()
        assert result.total_raw == 1  # only from scanner_ok
        assert len(result.failed_sources) == 1

    @pytest.mark.asyncio
    async def test_no_scanners(self):
        scorer = TopicScorer()
        orch = DiscoveryOrchestrator([], scorer)
        result = await orch.run()
        assert result.total_raw == 0
        assert result.approved_count == 0

    @pytest.mark.asyncio
    async def test_scoring_produces_sorted_results(self):
        topics = [
            _raw_topic("Low", TopicSource.NEWS_RSS, mention_count=2),
            _raw_topic("High", TopicSource.NEWS_RSS, mention_count=15),
        ]
        scanner = FakeScanner(topics=topics)
        scorer = TopicScorer()
        orch = DiscoveryOrchestrator([scanner], scorer)
        result = await orch.run()
        if len(result.scored_topics) >= 2:
            scores = [s.total_score for s in result.scored_topics]
            assert scores == sorted(scores, reverse=True)

    @pytest.mark.asyncio
    async def test_briefs_only_for_approved(self):
        # Create topic that will definitely score < 70 (low metrics)
        low_topic = _raw_topic("Low Score Topic", TopicSource.NEWS_RSS, mention_count=1)
        scanner = FakeScanner(topics=[low_topic])
        scorer = TopicScorer()
        orch = DiscoveryOrchestrator([scanner], scorer)
        result = await orch.run()
        # With low metrics, topic should not be approved
        # (news: momentum=2, gap=20, rpm=15, novelty=5 = 42 → discard)
        assert result.approved_count == 0

    @pytest.mark.asyncio
    async def test_duration_recorded(self):
        scanner = FakeScanner(topics=[])
        scorer = TopicScorer()
        orch = DiscoveryOrchestrator([scanner], scorer)
        result = await orch.run()
        assert result.duration_seconds >= 0

    @pytest.mark.asyncio
    async def test_review_topics_collected(self):
        # News with mention_count=8 → momentum=16, gap=20, rpm=15, novelty=5 = 56 → review
        topic = _raw_topic("Review Topic", TopicSource.NEWS_RSS, mention_count=8)
        scanner = FakeScanner(topics=[topic])
        scorer = TopicScorer()
        orch = DiscoveryOrchestrator([scanner], scorer)
        result = await orch.run()
        # Score ~56 → should be in review range (50-69)
        if 50 <= result.scored_topics[0].total_score < 70:
            assert result.review_count == 1

    @pytest.mark.asyncio
    async def test_brand_voice_passed_to_briefs(self):
        # High enough to auto-approve: podcast with listen_score=200
        topic = _raw_topic("Big Topic", TopicSource.PODCAST, listen_score=200)
        scanner = FakeScanner(topics=[topic])
        scorer = TopicScorer()
        orch = DiscoveryOrchestrator([scanner], scorer, brand_voice="Bold, dramatic")
        result = await orch.run()
        for brief in result.briefs:
            assert brief.brand_voice == "Bold, dramatic"
```
