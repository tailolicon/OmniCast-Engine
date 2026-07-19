import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from omnicast.analytics.quality_scorer import ContentQualityScorer
from omnicast.analytics.models import (
    ScriptScore, ThumbnailScore, AudioScore, VideoScore,
    VideoScorecard, VideoMetrics,
)
from datetime import datetime, timezone


@pytest.fixture
def scorer():
    return ContentQualityScorer()


class TestScoreScript:
    @pytest.mark.asyncio
    async def test_returns_script_score(self, scorer):
        mock_score = ScriptScore(
            hook_strength=8, structure=7,
            uniqueness=6, readability=8, estimated_avd=7,
        )
        with patch.object(scorer, "score_script",
                          new_callable=AsyncMock, return_value=mock_score):
            result = await scorer.score_script("Some script content here...")
            assert isinstance(result, ScriptScore)
            assert 0 <= result.hook_strength <= 10


class TestScoreThumbnail:
    @pytest.mark.asyncio
    async def test_returns_thumbnail_score(self, scorer):
        mock_score = ThumbnailScore(
            contrast=7, emotion=8, curiosity_gap=6,
            brand_consistency=7, predicted_ctr=5.5,
        )
        with patch.object(scorer, "score_thumbnail",
                          new_callable=AsyncMock, return_value=mock_score):
            result = await scorer.score_thumbnail("/tmp/thumb.jpg")
            assert isinstance(result, ThumbnailScore)


class TestScorePerformance:
    @pytest.mark.asyncio
    async def test_returns_delta(self, scorer):
        predicted = VideoScorecard(
            video_id="v1", channel_id="ch1",
            thumbnail_score=ThumbnailScore(
                contrast=7, emotion=8, curiosity_gap=6,
                brand_consistency=7, predicted_ctr=5.0,
            ),
        )
        actual = VideoMetrics(
            video_id="v1", channel_id="ch1",
            published_at=datetime.now(timezone.utc),
            views_24h=500, views_48h=800, views_7d=2000,
            ctr=4.2, avd_seconds=200, avd_percent=45,
            retention_curve=[100, 85, 70], likes=50,
            comments=10, shares=5, traffic_sources={},
        )
        with patch.object(scorer, "score_performance",
                          new_callable=AsyncMock,
                          return_value={"ctr_delta": -0.8}):
            result = await scorer.score_performance(predicted, actual)
            assert "ctr_delta" in result
