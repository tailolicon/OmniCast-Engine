"""Video Intelligence Analyzer - analyze competitor video production patterns."""

from __future__ import annotations
from datetime import datetime, timezone
from statistics import mean
import structlog
from omnicast.analytics.models import ProductionBlueprint
from omnicast.analytics.crawler import AnalyticsCrawler

logger = structlog.get_logger()


class VideoIntelligenceAnalyzer:
    """Analyze competitor video production patterns → ProductionBlueprint."""

    def __init__(self, crawler: AnalyticsCrawler) -> None:
        self.crawler = crawler

    async def analyze_structure(self, transcript: str, duration_seconds: float) -> dict:
        """Analyze video structure from transcript and duration."""
        # Placeholder for actual structure analysis
        # In production: use NLP to identify segments, intro/outro
        return {
            "intro_length": duration_seconds * 0.05,  # 5% of video
            "segment_count": max(3, int(duration_seconds / 90)),
            "avg_segment_duration": duration_seconds / max(3, int(duration_seconds / 90)),
            "outro_length": duration_seconds * 0.04,
            "transition_types": ["cut", "fade"],
        }

    async def analyze_visual_style(self, frame_descriptions: list[str]) -> dict:
        """Analyze visual style from frame descriptions."""
        # Placeholder for actual visual analysis
        # In production: use CV to detect art style, colors, text overlay frequency
        return {
            "art_direction": "cinematic",
            "dominant_colors": ["#1a1a2e", "#e94560"],
            "text_overlay_freq": 0.3,
            "talking_head_ratio": 0.0,
            "b_roll_ratio": 0.4,
        }

    async def analyze_audio_pattern(self, audio_features: dict) -> dict:
        """Analyze audio pattern from features."""
        # Placeholder for actual audio analysis
        # In production: use librosa to detect music energy, pacing
        return {
            "music_energy": "medium",
            "words_per_min": 150,
            "voice_pacing": "moderate",
        }

    async def analyze_hook(self, first_30s_transcript: str) -> dict:
        """Analyze hook type from first 30 seconds."""
        # Placeholder for actual hook analysis
        # In production: use NLP to classify hook type (question, shock_stat, etc.)
        return {
            "hook_type": "question",
            "hook_strength": 8,
            "cta_present": False,
        }

    async def build_blueprint(self, niche: str, analyses: list[dict]) -> ProductionBlueprint:
        """Build ProductionBlueprint from aggregated analyses."""
        if not analyses:
            # Return default blueprint with low confidence
            return ProductionBlueprint(
                niche=niche,
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
                confidence=0.1,
                sample_size=0,
                generated_at=datetime.now(timezone.utc),
            )

        # Aggregate structure
        structure_analyses = [a.get("structure", {}) for a in analyses if a.get("structure")]
        if structure_analyses:
            avg_intro = mean([s.get("intro_length", 20) for s in structure_analyses])
            avg_segments = mean([s.get("segment_count", 5) for s in structure_analyses])
        else:
            avg_intro = 20.0
            avg_segments = 5

        # Aggregate visual
        visual_analyses = [a.get("visual", {}) for a in analyses if a.get("visual")]
        if visual_analyses:
            avg_broll = mean([v.get("broll_ratio", 0.3) for v in visual_analyses])
            avg_text = mean([v.get("text_overlay_freq", 0.3) for v in visual_analyses])
            art_direction = visual_analyses[0].get("art_direction", "cinematic")
        else:
            avg_broll = 0.3
            avg_text = 0.3
            art_direction = "cinematic"

        # Aggregate audio
        audio_analyses = [a.get("audio", {}) for a in analyses if a.get("audio")]
        if audio_analyses:
            music_energy = audio_analyses[0].get("music_energy", "medium")
        else:
            music_energy = "medium"

        # Aggregate hook
        hook_analyses = [a.get("hook", {}) for a in analyses if a.get("hook")]
        if hook_analyses:
            hook_type = hook_analyses[0].get("hook_type", "question")
        else:
            hook_type = "question"

        # Calculate confidence based on sample size
        sample_size = len(analyses)
        if sample_size >= 10:
            confidence = 0.8
        elif sample_size >= 5:
            confidence = 0.6
        elif sample_size >= 3:
            confidence = 0.4
        else:
            confidence = 0.2

        return ProductionBlueprint(
            niche=niche,
            video_format="documentary",
            art_style=art_direction,
            pacing_scene_duration=(avg_intro / 2, avg_intro * 2),
            crossfade_seconds=0.5,
            music_energy=music_energy,
            text_overlay_freq=avg_text,
            b_roll_ratio=avg_broll,
            hook_type=hook_type,
            intro_duration=avg_intro,
            target_duration_minutes=int(avg_segments * 2),
            color_mood="warm",
            confidence=confidence,
            sample_size=sample_size,
            generated_at=datetime.now(timezone.utc),
        )

    def aggregate_patterns(self, blueprints: list[ProductionBlueprint]) -> ProductionBlueprint:
        """Aggregate multiple blueprints into one consensus blueprint."""
        if not blueprints:
            raise ValueError("Cannot aggregate empty blueprint list")

        if len(blueprints) == 1:
            return blueprints[0]

        # Aggregate numeric values
        total_sample_size = sum(bp.sample_size for bp in blueprints)
        avg_intro = mean([bp.intro_duration for bp in blueprints])
        avg_broll = mean([bp.b_roll_ratio for bp in blueprints])
        avg_text = mean([bp.text_overlay_freq for bp in blueprints])
        avg_crossfade = mean([bp.crossfade_seconds for bp in blueprints])

        # Get most common categorical values
        niche = blueprints[0].niche
        video_format = blueprints[0].video_format
        art_style = blueprints[0].art_style
        music_energy = blueprints[0].music_energy
        hook_type = blueprints[0].hook_type
        color_mood = blueprints[0].color_mood

        # Aggregate pacing ranges
        min_pacing = min(bp.pacing_scene_duration[0] for bp in blueprints)
        max_pacing = max(bp.pacing_scene_duration[1] for bp in blueprints)

        # Calculate combined confidence
        avg_confidence = mean([bp.confidence for bp in blueprints])

        return ProductionBlueprint(
            niche=niche,
            video_format=video_format,
            art_style=art_style,
            pacing_scene_duration=(min_pacing, max_pacing),
            crossfade_seconds=avg_crossfade,
            music_energy=music_energy,
            text_overlay_freq=avg_text,
            b_roll_ratio=avg_broll,
            hook_type=hook_type,
            intro_duration=avg_intro,
            target_duration_minutes=int(mean([bp.target_duration_minutes for bp in blueprints])),
            color_mood=color_mood,
            confidence=min(1.0, avg_confidence * 1.2),  # Boost confidence for aggregation
            sample_size=total_sample_size,
            generated_at=datetime.now(timezone.utc),
        )
