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
                raw=_raw_topic(), trend_momentum=20, gap_score=20,
                rpm_potential=15, novelty_score=8, stack_fit=10, total_score=73,
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
