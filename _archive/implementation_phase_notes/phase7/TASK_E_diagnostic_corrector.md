# TASK_E: Diagnostic Engine + Auto-Corrector

## Model: sonnet | Dependencies: TASK_A, TASK_B, TASK_C, TASK_D complete

Root cause analysis from funnel bottleneck. Auto-correction actions + A/B testing.

## Interface

### src/omnicast/analytics/diagnostic.py

```python
class DiagnosticEngine:
    """Combine health, retention, quality signals → ranked root causes."""
    def __init__(self, health_scorer: HealthScorer, quality_scorer: ContentQualityScorer)
    async def diagnose(self, channel_id: str, metrics: list[ChannelMetrics], scorecards: list[VideoScorecard]) -> Diagnosis
    async def compare_videos(self, good: list[VideoScorecard], bad: list[VideoScorecard]) -> dict[str, float]
    def find_funnel_bottleneck(self, metrics: list[ChannelMetrics]) -> str
```

### src/omnicast/analytics/corrector.py

```python
class AutoCorrector:
    """Map diagnosis to correction actions. Run A/B tests."""
    def map_actions(self, diagnosis: Diagnosis) -> list[CorrectionAction]
    async def run_ab_test(self, channel_id: str, variable: str, variants: list[str], sample_size: int = 10) -> ABTestResult
```

## DO NOT

- Funnel: impressions → ctr → avd → engagement. Bottleneck = biggest drop layer.
- Diagnosis ranked by confidence (high → low)
- Auto-actions: THUMBNAIL_WEAK → style change, SCRIPT_BORING → hook update, TOPIC_FATIGUE → cap repeats
- A/B test needs scipy.stats for p-value (mock in tests)
- Never auto-execute without confidence > 0.7

## Tests

### tests/unit/test_diagnostic.py

```python
import pytest
from datetime import datetime, date, timezone, timedelta
from unittest.mock import MagicMock, AsyncMock, patch
from omnicast.analytics.diagnostic import DiagnosticEngine
from omnicast.analytics.models import (
    ChannelMetrics, Diagnosis, DiagnosisItem, VideoScorecard,
    ScriptScore, ThumbnailScore,
)
from omnicast.analytics.health import HealthScorer
from omnicast.analytics.quality_scorer import ContentQualityScorer


def _make_metrics(views=1000, ctr=4.5, avd=42.0, days=30):
    return [
        ChannelMetrics(
            channel_id="ch1", date=date(2025, 6, 1) + timedelta(days=i),
            impressions=int(views / (ctr / 100)) if ctr > 0 else 10000,
            ctr=ctr, views=views, avd_seconds=avd * 4.3,
            avd_percent=avd, watch_time_hours=50,
            subscriber_change=5, revenue=3.0, rpm=10.0,
            top_traffic_sources={"browse": 0.5},
        )
        for i in range(days)
    ]


@pytest.fixture
def engine():
    return DiagnosticEngine(
        health_scorer=MagicMock(spec=HealthScorer),
        quality_scorer=MagicMock(spec=ContentQualityScorer),
    )


class TestFindFunnelBottleneck:
    def test_ctr_bottleneck(self, engine):
        metrics = _make_metrics(views=200, ctr=1.5, avd=50.0)
        bottleneck = engine.find_funnel_bottleneck(metrics)
        assert bottleneck in ["impressions", "ctr", "avd", "engagement"]

    def test_avd_bottleneck(self, engine):
        metrics = _make_metrics(views=1000, ctr=5.0, avd=15.0)
        bottleneck = engine.find_funnel_bottleneck(metrics)
        assert bottleneck in ["impressions", "ctr", "avd", "engagement"]


class TestDiagnose:
    @pytest.mark.asyncio
    async def test_returns_diagnosis(self, engine):
        metrics = _make_metrics(views=200, ctr=2.0)
        scorecards = [
            VideoScorecard(
                video_id="v1", channel_id="ch1",
                thumbnail_score=ThumbnailScore(
                    contrast=3, emotion=4, curiosity_gap=3,
                    brand_consistency=5, predicted_ctr=4.0,
                ),
                performance_tier="poor",
            ),
        ]
        with patch.object(engine, "diagnose", new_callable=AsyncMock,
                          return_value=Diagnosis(
                              channel_id="ch1", funnel_bottleneck="ctr",
                              items=[DiagnosisItem(
                                  cause="THUMBNAIL_WEAK", confidence=0.8,
                                  evidence=["contrast=3"], suggested_action="change style",
                              )],
                              generated_at=datetime.now(timezone.utc),
                          )):
            result = await engine.diagnose("ch1", metrics, scorecards)
            assert isinstance(result, Diagnosis)
            assert len(result.items) >= 1
            assert result.items[0].confidence > 0


class TestCompareVideos:
    @pytest.mark.asyncio
    async def test_returns_diff(self, engine):
        good = [VideoScorecard(
            video_id="v1", channel_id="ch1", performance_tier="top",
            script_score=ScriptScore(hook_strength=9, structure=8,
                                      uniqueness=8, readability=9, estimated_avd=8),
        )]
        bad = [VideoScorecard(
            video_id="v2", channel_id="ch1", performance_tier="poor",
            script_score=ScriptScore(hook_strength=3, structure=4,
                                      uniqueness=3, readability=5, estimated_avd=3),
        )]
        with patch.object(engine, "compare_videos",
                          new_callable=AsyncMock,
                          return_value={"hook_strength_diff": 6.0}):
            result = await engine.compare_videos(good, bad)
            assert isinstance(result, dict)
```

### tests/unit/test_corrector.py

```python
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch
from omnicast.analytics.corrector import AutoCorrector
from omnicast.analytics.models import (
    Diagnosis, DiagnosisItem, CorrectionAction, ABTestResult,
)


@pytest.fixture
def corrector():
    return AutoCorrector()


class TestMapActions:
    def test_thumbnail_weak(self, corrector):
        diagnosis = Diagnosis(
            channel_id="ch1", funnel_bottleneck="ctr",
            items=[DiagnosisItem(
                cause="THUMBNAIL_WEAK", confidence=0.85,
                evidence=["low contrast"], suggested_action="change style",
            )],
            generated_at=datetime.now(timezone.utc),
        )
        actions = corrector.map_actions(diagnosis)
        assert len(actions) >= 1
        assert isinstance(actions[0], CorrectionAction)

    def test_multiple_causes(self, corrector):
        diagnosis = Diagnosis(
            channel_id="ch1", funnel_bottleneck="avd",
            items=[
                DiagnosisItem(cause="SCRIPT_BORING", confidence=0.7,
                              evidence=["weak hook"], suggested_action="update hook"),
                DiagnosisItem(cause="TTS_ROBOTIC", confidence=0.5,
                              evidence=["low naturalness"], suggested_action="switch voice"),
            ],
            generated_at=datetime.now(timezone.utc),
        )
        actions = corrector.map_actions(diagnosis)
        assert len(actions) >= 2

    def test_low_confidence_manual(self, corrector):
        diagnosis = Diagnosis(
            channel_id="ch1", funnel_bottleneck="ctr",
            items=[DiagnosisItem(
                cause="UNKNOWN", confidence=0.3,
                evidence=["unclear"], suggested_action="investigate",
            )],
            generated_at=datetime.now(timezone.utc),
        )
        actions = corrector.map_actions(diagnosis)
        for a in actions:
            assert a.action_type == "manual"


class TestABTest:
    @pytest.mark.asyncio
    async def test_returns_result(self, corrector):
        with patch.object(corrector, "run_ab_test",
                          new_callable=AsyncMock,
                          return_value=ABTestResult(
                              variable="thumbnail_style",
                              variants=["dark", "bright"],
                              sample_sizes=[10, 10],
                              metrics={"ctr": [3.2, 5.1]},
                              winner="bright", p_value=0.03, significant=True,
                          )):
            result = await corrector.run_ab_test("ch1", "thumbnail_style", ["dark", "bright"])
            assert isinstance(result, ABTestResult)
            assert result.significant
```
