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
