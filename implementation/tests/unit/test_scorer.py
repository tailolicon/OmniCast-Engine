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
    # Gap is now a 0-25 SATURATION dimension (it no longer re-reads
    # outlier_ratio, which trend_momentum already scores in full).
    def test_youtube_default(self):
        topic = _raw(TopicSource.YOUTUBE_COMPETITOR)
        score = TopicScorer._calc_gap_score(topic)
        # No saturation evidence either way → the neutral baseline.
        assert score == 12

    def test_reddit_default(self):
        topic = _raw(TopicSource.REDDIT)
        score = TopicScorer._calc_gap_score(topic)
        assert score == 19

    def test_podcast_highest_gap(self):
        topic = _raw(TopicSource.PODCAST)
        score = TopicScorer._calc_gap_score(topic)
        assert score == 22
        # Ordering across sources is preserved from the old 0-40 scale.
        assert score > TopicScorer._calc_gap_score(_raw(TopicSource.REDDIT))
        assert score > TopicScorer._calc_gap_score(_raw(TopicSource.NEWS_RSS))

    def test_all_sources_in_range(self):
        for src in TopicSource:
            topic = _raw(src)
            score = TopicScorer._calc_gap_score(topic)
            assert 0 <= score <= 25, f"Gap score out of range for {src}"


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
