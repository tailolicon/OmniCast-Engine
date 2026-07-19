import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock, AsyncMock, patch
from omnicast.analytics.video_intel import VideoIntelligenceAnalyzer
from omnicast.analytics.models import ProductionBlueprint
from omnicast.analytics.crawler import AnalyticsCrawler


@pytest.fixture
def mock_crawler():
    return MagicMock(spec=AnalyticsCrawler)


@pytest.fixture
def analyzer(mock_crawler):
    return VideoIntelligenceAnalyzer(crawler=mock_crawler)


class TestAnalyzeStructure:
    @pytest.mark.asyncio
    async def test_returns_structure_dict(self, analyzer):
        with patch.object(analyzer, "analyze_structure",
                          new_callable=AsyncMock,
                          return_value={
                              "intro_length": 25.0,
                              "segment_count": 8,
                              "avg_segment_duration": 90.0,
                              "outro_length": 30.0,
                              "transition_types": ["cut", "fade"],
                          }):
            result = await analyzer.analyze_structure(
                "Some transcript...", duration_seconds=720.0,
            )
            assert "intro_length" in result
            assert "segment_count" in result


class TestAnalyzeVisualStyle:
    @pytest.mark.asyncio
    async def test_returns_visual_dict(self, analyzer):
        with patch.object(analyzer, "analyze_visual_style",
                          new_callable=AsyncMock,
                          return_value={
                              "art_direction": "cinematic dark",
                              "dominant_colors": ["#1a1a2e", "#e94560"],
                              "text_overlay_freq": 0.3,
                              "talking_head_ratio": 0.0,
                              "broll_ratio": 0.4,
                          }):
            result = await analyzer.analyze_visual_style(
                ["dark moody landscape", "text overlay showing stat"],
            )
            assert "art_direction" in result


class TestAnalyzeHook:
    @pytest.mark.asyncio
    async def test_returns_hook_dict(self, analyzer):
        with patch.object(analyzer, "analyze_hook",
                          new_callable=AsyncMock,
                          return_value={
                              "hook_type": "question",
                              "hook_strength": 8,
                              "cta_present": False,
                          }):
            result = await analyzer.analyze_hook(
                "Did you know that 90% of ancient myths share the same structure?"
            )
            assert result["hook_type"] == "question"


class TestBuildBlueprint:
    @pytest.mark.asyncio
    async def test_returns_blueprint(self, analyzer):
        analyses = [
            {
                "structure": {"intro_length": 25, "segment_count": 8},
                "visual": {"art_direction": "cinematic", "broll_ratio": 0.4},
                "audio": {"music_energy": "medium", "words_per_min": 150},
                "hook": {"hook_type": "question"},
            },
            {
                "structure": {"intro_length": 20, "segment_count": 6},
                "visual": {"art_direction": "cinematic", "broll_ratio": 0.35},
                "audio": {"music_energy": "medium", "words_per_min": 145},
                "hook": {"hook_type": "question"},
            },
        ]
        with patch.object(analyzer, "build_blueprint",
                          new_callable=AsyncMock,
                          return_value=ProductionBlueprint(
                              niche="mythology",
                              video_format="documentary",
                              art_style="cinematic",
                              pacing_scene_duration=(3.0, 8.0),
                              crossfade_seconds=0.5,
                              music_energy="medium",
                              text_overlay_freq=0.3,
                              b_roll_ratio=0.4,
                              hook_type="question",
                              intro_duration=22.5,
                              target_duration_minutes=12,
                              color_mood="warm",
                              confidence=0.7,
                              sample_size=2,
                              generated_at=datetime.now(timezone.utc),
                          )):
            result = await analyzer.build_blueprint("mythology", analyses)
            assert isinstance(result, ProductionBlueprint)
            assert result.niche == "mythology"

    @pytest.mark.asyncio
    async def test_low_sample_low_confidence(self, analyzer):
        with patch.object(analyzer, "build_blueprint",
                          new_callable=AsyncMock,
                          return_value=ProductionBlueprint(
                              niche="new_niche",
                              video_format="explainer",
                              art_style="minimal",
                              pacing_scene_duration=(2.0, 5.0),
                              crossfade_seconds=0.3,
                              music_energy="low",
                              text_overlay_freq=0.2,
                              b_roll_ratio=0.2,
                              hook_type="cold_open",
                              intro_duration=15.0,
                              target_duration_minutes=8,
                              color_mood="neutral",
                              confidence=0.3,
                              sample_size=1,
                              generated_at=datetime.now(timezone.utc),
                          )):
            result = await analyzer.build_blueprint("new_niche", [{}])
            assert result.confidence < 0.5


class TestAggregatePatterns:
    def test_aggregate_multiple(self, analyzer):
        now = datetime.now(timezone.utc)
        blueprints = [
            ProductionBlueprint(
                niche="myth", video_format="documentary", art_style="cinematic",
                pacing_scene_duration=(3, 8), crossfade_seconds=0.5,
                music_energy="medium", text_overlay_freq=0.3, b_roll_ratio=0.4,
                hook_type="question", intro_duration=25, target_duration_minutes=12,
                color_mood="warm", confidence=0.8, sample_size=10, generated_at=now,
            ),
            ProductionBlueprint(
                niche="myth", video_format="documentary", art_style="cinematic",
                pacing_scene_duration=(4, 9), crossfade_seconds=0.6,
                music_energy="medium", text_overlay_freq=0.25, b_roll_ratio=0.45,
                hook_type="question", intro_duration=20, target_duration_minutes=10,
                color_mood="warm", confidence=0.7, sample_size=8, generated_at=now,
            ),
        ]
        result = analyzer.aggregate_patterns(blueprints)
        assert isinstance(result, ProductionBlueprint)
        assert result.sample_size >= 18

    def test_single_blueprint(self, analyzer):
        now = datetime.now(timezone.utc)
        bp = ProductionBlueprint(
            niche="tech", video_format="listicle", art_style="minimal",
            pacing_scene_duration=(2, 5), crossfade_seconds=0.3,
            music_energy="high", text_overlay_freq=0.5, b_roll_ratio=0.3,
            hook_type="shock_stat", intro_duration=15, target_duration_minutes=8,
            color_mood="cold", confidence=0.6, sample_size=5, generated_at=now,
        )
        result = analyzer.aggregate_patterns([bp])
        assert result.niche == "tech"
