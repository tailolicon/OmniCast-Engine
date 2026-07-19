# TASK_D: Retention Analyst + Content Quality Scorer

## Model: sonnet | Dependencies: TASK_A, TASK_B complete

Retention drop-off analysis + pre/post-publish content quality scoring.

## Interface

### src/omnicast/analytics/retention.py

```python
class RetentionAnalyst:
    """Analyze retention curves, find drop-off points, correlate with script segments."""
    def find_drop_points(self, retention_curve: list[float], threshold: float = 5.0) -> list[dict]
    def correlate_with_script(self, drop_points: list[dict], script_segments: list[str]) -> list[dict]
    def summarize_patterns(self, video_analyses: list[dict]) -> dict[str, list[str]]
```

### src/omnicast/analytics/quality_scorer.py

```python
class ContentQualityScorer:
    """Score content on multiple dimensions pre and post-publish."""
    async def score_script(self, script: str) -> ScriptScore
    async def score_thumbnail(self, image_path: str) -> ThumbnailScore
    async def score_audio(self, audio_path: str) -> AudioScore
    async def score_video(self, video_path: str) -> VideoScore
    async def score_performance(self, predicted: VideoScorecard, actual: VideoMetrics) -> dict[str, float]
```

## DO NOT

- Drop point = retention drops > threshold% between intervals
- score_script/thumbnail use LLM (mock in tests)
- score_audio/video use signal processing (mock in tests)
- score_performance returns delta dict (predicted vs actual)

## Tests

### tests/unit/test_retention.py

```python
import pytest
from omnicast.analytics.retention import RetentionAnalyst


@pytest.fixture
def analyst():
    return RetentionAnalyst()


class TestFindDropPoints:
    def test_no_drops(self, analyst):
        curve = [100, 98, 96, 94, 92, 90]
        drops = analyst.find_drop_points(curve)
        assert len(drops) == 0

    def test_single_drop(self, analyst):
        curve = [100, 95, 90, 80, 60, 55, 50]  # drop at index 3→4
        drops = analyst.find_drop_points(curve)
        assert len(drops) >= 1

    def test_multiple_drops(self, analyst):
        curve = [100, 85, 80, 60, 55, 35, 30]
        drops = analyst.find_drop_points(curve)
        assert len(drops) >= 2

    def test_custom_threshold(self, analyst):
        curve = [100, 93, 90, 85]
        drops_strict = analyst.find_drop_points(curve, threshold=3.0)
        drops_loose = analyst.find_drop_points(curve, threshold=10.0)
        assert len(drops_strict) >= len(drops_loose)

    def test_empty_curve(self, analyst):
        drops = analyst.find_drop_points([])
        assert drops == []


class TestCorrelateWithScript:
    def test_maps_drops_to_segments(self, analyst):
        drops = [{"index": 3, "drop_pct": 15.0}]
        segments = ["intro", "point 1", "transition", "point 2", "outro"]
        result = analyst.correlate_with_script(drops, segments)
        assert len(result) >= 1
        assert "segment" in result[0] or "index" in result[0]

    def test_empty_drops(self, analyst):
        result = analyst.correlate_with_script([], ["intro", "body"])
        assert result == []


class TestSummarizePatterns:
    def test_aggregates(self, analyst):
        analyses = [
            {"drops": [{"segment": "transition", "drop_pct": 12}]},
            {"drops": [{"segment": "transition", "drop_pct": 10}]},
            {"drops": [{"segment": "intro", "drop_pct": 8}]},
        ]
        patterns = analyst.summarize_patterns(analyses)
        assert isinstance(patterns, dict)
```

### tests/unit/test_quality_scorer.py

```python
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
```
