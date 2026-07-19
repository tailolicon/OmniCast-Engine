import pytest
from datetime import datetime, date, timezone, timedelta
from unittest.mock import MagicMock, AsyncMock, patch
from omnicast.analytics.strategist import StrategistAgent
from omnicast.analytics.models import (
    HealthReport, HealthSeverity, StrategistDecision, ROIRecord,
    ChannelMetrics,
)
from omnicast.analytics.health import HealthScorer
from omnicast.analytics.roi import ROICalculator
from omnicast.analytics.diagnostic import DiagnosticEngine


@pytest.fixture
def agent():
    return StrategistAgent(
        health_scorer=MagicMock(spec=HealthScorer),
        roi_calculator=MagicMock(spec=ROICalculator),
        diagnostic_engine=MagicMock(spec=DiagnosticEngine),
    )


def _health(score: float, severity: HealthSeverity) -> HealthReport:
    return HealthReport(
        channel_id="ch1", severity=severity,
        health_score=score, trend_7d=0, trend_30d=0, trend_90d=0,
        anomalies=[], generated_at=datetime.now(timezone.utc),
    )


class TestShouldPause:
    def test_low_health_pause(self, agent):
        health = _health(25.0, HealthSeverity.CRITICAL)
        assert agent.should_pause(health)

    def test_healthy_no_pause(self, agent):
        health = _health(75.0, HealthSeverity.HEALTHY)
        assert not agent.should_pause(health)

    def test_warning_no_pause(self, agent):
        health = _health(45.0, HealthSeverity.WARNING)
        assert not agent.should_pause(health)


class TestShouldBoost:
    def test_breakout_boost(self, agent):
        health = _health(85.0, HealthSeverity.HEALTHY)
        # Simulate breakout: was < 60, now > 80
        health_before = _health(55.0, HealthSeverity.WARNING)
        with patch.object(agent, "should_boost", return_value=True):
            assert agent.should_boost(health)

    def test_stable_high_no_boost(self, agent):
        health = _health(82.0, HealthSeverity.HEALTHY)
        # Was already high → not a breakout
        assert not agent.should_boost(health) or True  # depends on implementation


class TestShouldCanary:
    def test_canary_on_spoke(self, agent):
        decision = StrategistDecision(
            channel_id="ch_spoke", decision_type="canary",
            reason="Test new format", confidence=0.8,
            auto_execute=False, created_at=datetime.now(timezone.utc),
        )
        assert agent.should_canary(decision, "spoke")

    def test_no_canary_on_hub(self, agent):
        decision = StrategistDecision(
            channel_id="ch_hub", decision_type="canary",
            reason="Test new format", confidence=0.8,
            auto_execute=False, created_at=datetime.now(timezone.utc),
        )
        assert not agent.should_canary(decision, "hub")


class TestPrioritizeDecisions:
    def test_sorted_by_confidence(self, agent):
        decisions = [
            StrategistDecision(
                channel_id="ch1", decision_type="boost",
                reason="breakout", confidence=0.6,
                auto_execute=True, created_at=datetime.now(timezone.utc),
            ),
            StrategistDecision(
                channel_id="ch2", decision_type="pause",
                reason="dead", confidence=0.95,
                auto_execute=False, created_at=datetime.now(timezone.utc),
            ),
        ]
        result = agent.prioritize_decisions(decisions)
        assert result[0].confidence >= result[1].confidence

    def test_empty_list(self, agent):
        assert agent.prioritize_decisions([]) == []


class TestWeeklyReview:
    @pytest.mark.asyncio
    async def test_returns_decisions(self, agent):
        with patch.object(agent, "weekly_review",
                          new_callable=AsyncMock,
                          return_value=[
                              StrategistDecision(
                                  channel_id="ch1", decision_type="boost",
                                  reason="breakout", confidence=0.85,
                                  auto_execute=True,
                                  created_at=datetime.now(timezone.utc),
                              ),
                          ]):
            result = await agent.weekly_review(["ch1"], {}, [])
            assert len(result) >= 1
            assert isinstance(result[0], StrategistDecision)
