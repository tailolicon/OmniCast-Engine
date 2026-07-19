import pytest
from datetime import datetime, date, timezone
from omnicast.analytics.models import (
    ChannelMetrics, VideoMetrics, HealthSeverity, HealthReport,
    Anomaly, ScriptScore, ThumbnailScore, AudioScore, VideoScore,
    VideoScorecard, DiagnosisItem, Diagnosis, CorrectionAction,
    ABTestResult, ROIRecord, ProductionBlueprint, StrategistDecision,
)


class TestChannelMetrics:
    def test_create(self):
        m = ChannelMetrics(
            channel_id="ch1", date=date(2025, 6, 1),
            impressions=50000, ctr=4.5, views=2250,
            avd_seconds=180.0, avd_percent=42.0,
            watch_time_hours=112.5, subscriber_change=50,
            revenue=25.0, rpm=11.1,
            top_traffic_sources={"browse": 0.45, "search": 0.30},
        )
        assert m.ctr == 4.5
        assert m.impressions == 50000

    def test_frozen(self):
        m = ChannelMetrics(
            channel_id="ch1", date=date(2025, 6, 1),
            impressions=100, ctr=1.0, views=1,
            avd_seconds=10.0, avd_percent=5.0,
            watch_time_hours=0.01, subscriber_change=0,
            revenue=0, rpm=0,
            top_traffic_sources={},
        )
        with pytest.raises(Exception):
            m.ctr = 5.0


class TestVideoMetrics:
    def test_create(self):
        m = VideoMetrics(
            video_id="v1", channel_id="ch1",
            published_at=datetime.now(timezone.utc),
            views_24h=500, views_48h=800, views_7d=2000,
            ctr=5.0, avd_seconds=200.0, avd_percent=45.0,
            retention_curve=[100, 85, 72, 60, 55, 50, 48, 45],
            likes=50, comments=10, shares=5,
            traffic_sources={"browse": 0.5},
        )
        assert len(m.retention_curve) == 8

    def test_retention_curve_type(self):
        m = VideoMetrics(
            video_id="v1", channel_id="ch1",
            published_at=datetime.now(timezone.utc),
            views_24h=0, views_48h=0, views_7d=0,
            ctr=0, avd_seconds=0, avd_percent=0,
            retention_curve=[], likes=0, comments=0, shares=0,
            traffic_sources={},
        )
        assert isinstance(m.retention_curve, list)


class TestHealthReport:
    def test_healthy(self):
        r = HealthReport(
            channel_id="ch1", severity=HealthSeverity.HEALTHY,
            health_score=85.0, trend_7d=5.0, trend_30d=10.0,
            trend_90d=15.0, anomalies=[],
            generated_at=datetime.now(timezone.utc),
        )
        assert r.severity == HealthSeverity.HEALTHY

    def test_critical(self):
        r = HealthReport(
            channel_id="ch1", severity=HealthSeverity.CRITICAL,
            health_score=25.0, trend_7d=-30.0, trend_30d=-20.0,
            trend_90d=-10.0, anomalies=["views_drop", "ctr_drop"],
            generated_at=datetime.now(timezone.utc),
        )
        assert r.health_score == 25.0
        assert len(r.anomalies) == 2


class TestAnomaly:
    def test_create(self):
        a = Anomaly(
            metric_name="ctr", value=1.5, z_score=-2.5,
            direction="down", detected_at=datetime.now(timezone.utc),
        )
        assert a.z_score == -2.5


class TestScores:
    def test_script_score(self):
        s = ScriptScore(
            hook_strength=8.0, structure=7.0,
            uniqueness=6.5, readability=8.5, estimated_avd=7.0,
        )
        assert 0 <= s.hook_strength <= 10

    def test_thumbnail_score(self):
        t = ThumbnailScore(
            contrast=7.0, emotion=8.0,
            curiosity_gap=6.0, brand_consistency=7.5,
            predicted_ctr=5.5,
        )
        assert t.predicted_ctr == 5.5

    def test_audio_score(self):
        a = AudioScore(
            voice_naturalness=7.0, pacing=8.0,
            music_balance=6.5, clipping_detected=False,
        )
        assert not a.clipping_detected

    def test_video_score(self):
        v = VideoScore(
            visual_variety=7.0, transition_quality=6.0,
            text_readability=8.0, technical_quality=7.5,
        )
        assert v.visual_variety == 7.0


class TestVideoScorecard:
    def test_minimal(self):
        sc = VideoScorecard(video_id="v1", channel_id="ch1")
        assert sc.performance_tier == "pending"
        assert sc.script_score is None

    def test_with_scores(self):
        sc = VideoScorecard(
            video_id="v1", channel_id="ch1",
            script_score=ScriptScore(
                hook_strength=8, structure=7,
                uniqueness=6, readability=8, estimated_avd=7,
            ),
            performance_tier="top",
        )
        assert sc.performance_tier == "top"
        assert sc.script_score.hook_strength == 8


class TestDiagnosis:
    def test_create(self):
        d = Diagnosis(
            channel_id="ch1", funnel_bottleneck="ctr",
            items=[
                DiagnosisItem(
                    cause="THUMBNAIL_WEAK", confidence=0.82,
                    evidence=["contrast dropped 40%"],
                    suggested_action="Switch thumbnail style",
                ),
            ],
            generated_at=datetime.now(timezone.utc),
        )
        assert d.funnel_bottleneck == "ctr"
        assert d.items[0].confidence == 0.82


class TestABTestResult:
    def test_significant(self):
        r = ABTestResult(
            variable="thumbnail_style",
            variants=["dark", "bright"],
            sample_sizes=[10, 10],
            metrics={"ctr": [3.2, 5.1]},
            winner="bright", p_value=0.03, significant=True,
        )
        assert r.significant
        assert r.winner == "bright"

    def test_inconclusive(self):
        r = ABTestResult(
            variable="voice", variants=["v1", "v2"],
            sample_sizes=[5, 5], metrics={"avd": [42, 44]},
            winner=None, p_value=0.45, significant=False,
        )
        assert not r.significant


class TestROIRecord:
    def test_positive_roi(self):
        r = ROIRecord(
            video_id="v1", channel_id="ch1", niche="finance",
            cost_breakdown={"claude_api": 0.50, "gpu_hours": 1.20},
            total_cost=1.70, revenue=5.00,
            roi=(5.00 - 1.70) / 1.70,
        )
        assert r.roi > 0

    def test_negative_roi(self):
        r = ROIRecord(
            video_id="v2", channel_id="ch1", niche="cooking",
            cost_breakdown={"claude_api": 0.50, "gpu_hours": 2.00},
            total_cost=2.50, revenue=0.80,
            roi=(0.80 - 2.50) / 2.50,
        )
        assert r.roi < 0


class TestProductionBlueprint:
    def test_create(self):
        bp = ProductionBlueprint(
            niche="mythology",
            video_format="documentary",
            art_style="cinematic",
            pacing_scene_duration=(3.0, 8.0),
            crossfade_seconds=0.5,
            music_energy="medium",
            text_overlay_freq=0.3,
            b_roll_ratio=0.4,
            hook_type="question",
            intro_duration=25.0,
            target_duration_minutes=12,
            color_mood="warm",
            confidence=0.78,
            sample_size=15,
            generated_at=datetime.now(timezone.utc),
        )
        assert bp.video_format == "documentary"
        assert bp.confidence == 0.78

    def test_frozen(self):
        bp = ProductionBlueprint(
            niche="tech", video_format="listicle", art_style="minimal",
            pacing_scene_duration=(2.0, 5.0), crossfade_seconds=0.3,
            music_energy="high", text_overlay_freq=0.5, b_roll_ratio=0.3,
            hook_type="shock_stat", intro_duration=15.0,
            target_duration_minutes=8, color_mood="cold",
            confidence=0.6, sample_size=10,
            generated_at=datetime.now(timezone.utc),
        )
        with pytest.raises(Exception):
            bp.niche = "gaming"


class TestStrategistDecision:
    def test_pause(self):
        d = StrategistDecision(
            channel_id="ch1", decision_type="pause",
            reason="Health < 30% for 14 days",
            confidence=0.9, auto_execute=True,
            created_at=datetime.now(timezone.utc),
        )
        assert d.decision_type == "pause"
        assert d.auto_execute

    def test_canary(self):
        d = StrategistDecision(
            channel_id="ch_spoke1", decision_type="canary",
            reason="Test new format on spoke before hub",
            confidence=0.7, auto_execute=False,
            created_at=datetime.now(timezone.utc),
        )
        assert d.decision_type == "canary"
        assert not d.auto_execute
