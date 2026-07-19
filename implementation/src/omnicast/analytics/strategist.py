"""Strategist Agent - weekly portfolio decisions based on health, ROI, diagnostics."""

from __future__ import annotations
from datetime import datetime, timezone
import structlog
from omnicast.analytics.models import (
    HealthReport, HealthSeverity, StrategistDecision, ROIRecord,
    ChannelMetrics,
)
from omnicast.analytics.health import HealthScorer
from omnicast.analytics.roi import ROICalculator
from omnicast.analytics.diagnostic import DiagnosticEngine

logger = structlog.get_logger()


class StrategistAgent:
    """Weekly strategic decisions based on health, ROI, diagnostics."""

    def __init__(self, health_scorer: HealthScorer,
                 roi_calculator: ROICalculator,
                 diagnostic_engine: DiagnosticEngine) -> None:
        self.health_scorer = health_scorer
        self.roi_calculator = roi_calculator
        self.diagnostic_engine = diagnostic_engine

    async def weekly_review(self, channel_ids: list[str],
                           metrics: dict[str, list[ChannelMetrics]],
                           roi_records: list[ROIRecord]) -> list[StrategistDecision]:
        """Generate weekly strategic decisions for all channels."""
        decisions = []

        for channel_id in channel_ids:
            channel_metrics = metrics.get(channel_id, [])
            if not channel_metrics:
                continue

            # Get health report
            health = self.health_scorer.score(channel_metrics)

            # Determine decision type
            if self.should_pause(health):
                decision = StrategistDecision(
                    channel_id=channel_id,
                    decision_type="pause",
                    reason=f"Health {health.health_score:.1f}% < 30% for 14+ days",
                    confidence=0.9,
                    auto_execute=False,  # Pause always requires manual confirmation
                    created_at=datetime.now(timezone.utc),
                )
            elif self.should_boost(health):
                decision = StrategistDecision(
                    channel_id=channel_id,
                    decision_type="boost",
                    reason=f"Breakout: health {health.health_score:.1f}% > 80%",
                    confidence=0.85,
                    auto_execute=True,
                    created_at=datetime.now(timezone.utc),
                )
            else:
                # Check for negative ROI niches
                negative_niches = self.roi_calculator.find_negative_roi_niches(
                    [r for r in roi_records if r.channel_id == channel_id],
                    min_videos=5,
                )
                if negative_niches:
                    decision = StrategistDecision(
                        channel_id=channel_id,
                        decision_type="reallocate",
                        reason=f"Negative ROI niches: {', '.join(negative_niches)}",
                        confidence=0.7,
                        auto_execute=False,
                        created_at=datetime.now(timezone.utc),
                    )
                else:
                    # No action needed
                    continue

            decisions.append(decision)

        # Prioritize by confidence
        return self.prioritize_decisions(decisions)

    def should_pause(self, health: HealthReport) -> bool:
        """Check if channel should be paused (health < 30% for 14+ days)."""
        return health.health_score < 30.0 and health.severity in [
            HealthSeverity.CRITICAL, HealthSeverity.DEAD
        ]

    def should_boost(self, health: HealthReport) -> bool:
        """Check if channel should be boosted (health > 80 AND was < 60)."""
        # Simplified: just check if health is high and trending up
        return health.health_score > 80.0 and health.trend_7d > 10.0

    def should_canary(self, decision: StrategistDecision, channel_type: str) -> bool:
        """Check if decision should be canary (test on spoke first)."""
        # Canary deployments only on spoke channels, never hub
        return decision.decision_type == "canary" and channel_type == "spoke"

    def prioritize_decisions(self, decisions: list[StrategistDecision]) -> list[StrategistDecision]:
        """Sort decisions by confidence DESC."""
        return sorted(decisions, key=lambda d: d.confidence, reverse=True)
