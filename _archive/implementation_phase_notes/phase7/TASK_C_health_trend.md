# TASK_C: Health Score + Trend Analyzer

## Model: sonnet | Dependencies: TASK_A complete

Channel health scoring (0-100) + moving average trend detection + anomaly detection.

## Interface

### src/omnicast/analytics/health.py

```python
class HealthScorer:
    """Calculate channel health score 0-100 from metrics."""
    def score(self, metrics: list[ChannelMetrics]) -> HealthReport

class TrendAnalyzer:
    """Detect declining trends via moving averages. Z-score anomaly detection."""
    def analyze(self, metrics: list[ChannelMetrics]) -> HealthReport
    def detect_anomaly(self, metric_series: list[float], threshold: float = 2.0) -> list[Anomaly]
    def moving_average(self, values: list[float], window: int) -> list[float]
    def classify_severity(self, trend_7d: float, trend_30d: float, trend_90d: float, consecutive_low_days: int = 0) -> HealthSeverity
```

## DO NOT

- Severity: HEALTHY (stable/growing), WARNING (7d MA < 30d MA > 15%), CRITICAL (7d < 90d > 30%), DEAD (views < threshold 14+ days)
- Anomaly = z_score > threshold (default 2.0)
- Health score weights: CTR 25%, AVD 25%, views trend 20%, subscriber growth 15%, revenue 15%

## Tests

### tests/unit/test_health.py

```python
import pytest
from datetime import datetime, date, timezone, timedelta
from omnicast.analytics.health import HealthScorer, TrendAnalyzer
from omnicast.analytics.models import (
    ChannelMetrics, HealthReport, HealthSeverity, Anomaly,
)


def _make_metrics(channel_id: str, days: int, base_views: int = 1000,
                  trend: float = 0.0) -> list[ChannelMetrics]:
    """Generate mock metrics with optional trend."""
    metrics = []
    for i in range(days):
        factor = 1.0 + (trend * i / days)
        metrics.append(ChannelMetrics(
            channel_id=channel_id,
            date=date(2025, 6, 1) + timedelta(days=i),
            impressions=int(20000 * factor),
            ctr=4.5 * factor,
            views=int(base_views * factor),
            avd_seconds=180 * factor,
            avd_percent=42 * factor,
            watch_time_hours=50 * factor,
            subscriber_change=int(10 * factor),
            revenue=5.0 * factor,
            rpm=11.0,
            top_traffic_sources={"browse": 0.5},
        ))
    return metrics


@pytest.fixture
def scorer():
    return HealthScorer()


@pytest.fixture
def analyzer():
    return TrendAnalyzer()


class TestHealthScorer:
    def test_healthy_channel(self, scorer):
        metrics = _make_metrics("ch1", 30, base_views=2000, trend=0.1)
        report = scorer.score(metrics)
        assert isinstance(report, HealthReport)
        assert report.health_score > 50
        assert report.severity in [HealthSeverity.HEALTHY, HealthSeverity.WARNING]

    def test_returns_health_report(self, scorer):
        metrics = _make_metrics("ch1", 7)
        report = scorer.score(metrics)
        assert isinstance(report, HealthReport)
        assert 0 <= report.health_score <= 100

    def test_low_metrics_low_score(self, scorer):
        metrics = _make_metrics("ch1", 30, base_views=10, trend=-0.5)
        report = scorer.score(metrics)
        assert report.health_score < 50


class TestTrendAnalyzer:
    def test_stable_trend(self, analyzer):
        metrics = _make_metrics("ch1", 90, trend=0.0)
        report = analyzer.analyze(metrics)
        assert report.severity == HealthSeverity.HEALTHY

    def test_declining_trend(self, analyzer):
        metrics = _make_metrics("ch1", 90, trend=-0.5)
        report = analyzer.analyze(metrics)
        assert report.severity in [HealthSeverity.WARNING, HealthSeverity.CRITICAL]

    def test_growing_trend(self, analyzer):
        metrics = _make_metrics("ch1", 90, trend=0.3)
        report = analyzer.analyze(metrics)
        assert report.severity == HealthSeverity.HEALTHY


class TestMovingAverage:
    def test_basic(self, analyzer):
        values = [10, 20, 30, 40, 50]
        ma = analyzer.moving_average(values, window=3)
        assert len(ma) == 3
        assert ma[0] == pytest.approx(20.0)

    def test_window_larger_than_data(self, analyzer):
        values = [10, 20]
        ma = analyzer.moving_average(values, window=5)
        assert len(ma) == 0


class TestAnomalyDetection:
    def test_no_anomaly_stable(self, analyzer):
        values = [100, 102, 98, 101, 99, 100, 101]
        anomalies = analyzer.detect_anomaly(values)
        assert len(anomalies) == 0

    def test_detect_spike(self, analyzer):
        values = [100, 100, 100, 100, 100, 100, 500]
        anomalies = analyzer.detect_anomaly(values)
        assert len(anomalies) >= 1
        assert anomalies[0].direction == "up"

    def test_detect_drop(self, analyzer):
        values = [100, 100, 100, 100, 100, 100, 10]
        anomalies = analyzer.detect_anomaly(values)
        assert len(anomalies) >= 1
        assert anomalies[0].direction == "down"

    def test_custom_threshold(self, analyzer):
        values = [100, 100, 100, 100, 150]
        anomalies_strict = analyzer.detect_anomaly(values, threshold=1.0)
        anomalies_loose = analyzer.detect_anomaly(values, threshold=3.0)
        assert len(anomalies_strict) >= len(anomalies_loose)


class TestClassifySeverity:
    def test_healthy(self, analyzer):
        s = analyzer.classify_severity(trend_7d=5.0, trend_30d=3.0, trend_90d=2.0)
        assert s == HealthSeverity.HEALTHY

    def test_warning(self, analyzer):
        s = analyzer.classify_severity(trend_7d=-20.0, trend_30d=-5.0, trend_90d=0.0)
        assert s == HealthSeverity.WARNING

    def test_critical(self, analyzer):
        s = analyzer.classify_severity(trend_7d=-40.0, trend_30d=-25.0, trend_90d=-35.0)
        assert s == HealthSeverity.CRITICAL

    def test_dead(self, analyzer):
        s = analyzer.classify_severity(
            trend_7d=-50.0, trend_30d=-40.0, trend_90d=-30.0,
            consecutive_low_days=14,
        )
        assert s == HealthSeverity.DEAD
```
