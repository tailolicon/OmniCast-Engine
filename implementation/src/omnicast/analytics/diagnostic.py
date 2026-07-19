"""Diagnostic Engine - root cause analysis from funnel bottleneck."""

from __future__ import annotations
from datetime import datetime, date, timezone, timedelta
import structlog
from omnicast.analytics.models import (
    ChannelMetrics, Diagnosis, DiagnosisItem, VideoScorecard,
)
from omnicast.analytics.health import HealthScorer
from omnicast.analytics.quality_scorer import ContentQualityScorer

logger = structlog.get_logger()


class DiagnosticEngine:
    """Combine health, retention, quality signals → ranked root causes."""

    def __init__(self, health_scorer: HealthScorer,
                 quality_scorer: ContentQualityScorer) -> None:
        self.health_scorer = health_scorer
        self.quality_scorer = quality_scorer

    async def diagnose(self, channel_id: str, metrics: list[ChannelMetrics],
                       scorecards: list[VideoScorecard]) -> Diagnosis:
        """Diagnose root causes from metrics and scorecards."""
        # Find funnel bottleneck
        bottleneck = self.find_funnel_bottleneck(metrics)

        # Generate diagnosis items based on bottleneck and scorecards
        items = []

        if bottleneck == "ctr":
            # CTR issues usually relate to thumbnail/title
            for sc in scorecards:
                if sc.thumbnail_score and sc.thumbnail_score.contrast < 5:
                    items.append(DiagnosisItem(
                        cause="THUMBNAIL_WEAK",
                        confidence=0.8,
                        evidence=[f"contrast={sc.thumbnail_score.contrast}"],
                        suggested_action="change thumbnail style",
                    ))
                if sc.thumbnail_score and sc.thumbnail_score.curiosity_gap < 5:
                    items.append(DiagnosisItem(
                        cause="TITLE_BORING",
                        confidence=0.7,
                        evidence=[f"curiosity_gap={sc.thumbnail_score.curiosity_gap}"],
                        suggested_action="improve title",
                    ))

        elif bottleneck == "avd":
            # AVD issues relate to content quality
            for sc in scorecards:
                if sc.script_score and sc.script_score.hook_strength < 5:
                    items.append(DiagnosisItem(
                        cause="SCRIPT_BORING",
                        confidence=0.7,
                        evidence=[f"hook_strength={sc.script_score.hook_strength}"],
                        suggested_action="update hook",
                    ))
                if sc.audio_score and sc.audio_score.voice_naturalness < 5:
                    items.append(DiagnosisItem(
                        cause="TTS_ROBOTIC",
                        confidence=0.6,
                        evidence=[f"voice_naturalness={sc.audio_score.voice_naturalness}"],
                        suggested_action="switch voice",
                    ))

        elif bottleneck == "engagement":
            # Engagement issues relate to content structure
            for sc in scorecards:
                if sc.script_score and sc.script_score.structure < 5:
                    items.append(DiagnosisItem(
                        cause="POOR_STRUCTURE",
                        confidence=0.6,
                        evidence=[f"structure={sc.script_score.structure}"],
                        suggested_action="restructure script",
                    ))

        # Sort by confidence
        items.sort(key=lambda x: x.confidence, reverse=True)

        return Diagnosis(
            channel_id=channel_id,
            funnel_bottleneck=bottleneck,
            items=items,
            generated_at=datetime.now(timezone.utc),
        )

    async def compare_videos(self, good: list[VideoScorecard],
                             bad: list[VideoScorecard]) -> dict[str, float]:
        """Compare good vs bad videos to find differences."""
        diff = {}

        if not good or not bad:
            return diff

        # Compare script scores
        good_scripts = [sc.script_score for sc in good if sc.script_score]
        bad_scripts = [sc.script_score for sc in bad if sc.script_score]

        if good_scripts and bad_scripts:
            diff["hook_strength_diff"] = (
                sum(s.hook_strength for s in good_scripts) / len(good_scripts) -
                sum(s.hook_strength for s in bad_scripts) / len(bad_scripts)
            )
            diff["structure_diff"] = (
                sum(s.structure for s in good_scripts) / len(good_scripts) -
                sum(s.structure for s in bad_scripts) / len(bad_scripts)
            )

        # Compare thumbnail scores
        good_thumbs = [sc.thumbnail_score for sc in good if sc.thumbnail_score]
        bad_thumbs = [sc.thumbnail_score for sc in bad if sc.thumbnail_score]

        if good_thumbs and bad_thumbs:
            diff["contrast_diff"] = (
                sum(t.contrast for t in good_thumbs) / len(good_thumbs) -
                sum(t.contrast for t in bad_thumbs) / len(bad_thumbs)
            )

        return diff

    def find_funnel_bottleneck(self, metrics: list[ChannelMetrics]) -> str:
        """Find the biggest drop in the funnel: impressions → ctr → avd → engagement."""
        if not metrics:
            return "impressions"

        # Calculate averages
        avg_impressions = sum(m.impressions for m in metrics) / len(metrics)
        avg_ctr = sum(m.ctr for m in metrics) / len(metrics)
        avg_avd = sum(m.avd_percent for m in metrics) / len(metrics)
        avg_sub_change = sum(m.subscriber_change for m in metrics) / len(metrics)

        # Calculate funnel ratios
        # CTR = views / impressions
        # AVD = watch time / views
        # Engagement = subs / views

        # Normalize to 0-1 scale for comparison
        ctr_score = avg_ctr / 10.0  # 10% is good
        avd_score = avg_avd / 50.0  # 50% is good
        engagement_score = abs(avg_sub_change) / 100.0  # 100 subs is good

        # Find lowest score
        scores = {
            "impressions": 1.0,  # Assume impressions are baseline
            "ctr": ctr_score,
            "avd": avd_score,
            "engagement": engagement_score,
        }

        bottleneck = min(scores, key=scores.get)
        return bottleneck
