"""Health Score + Trend Analyzer - channel health scoring and trend detection."""

from __future__ import annotations
from datetime import datetime, date, timezone, timedelta
from statistics import mean, stdev
import structlog
from omnicast.analytics.models import (
    ChannelMetrics, HealthReport, HealthSeverity, Anomaly,
)

logger = structlog.get_logger()


class HealthScorer:
    """Calculate channel health score 0-100 from metrics."""

    def score(self, metrics: list[ChannelMetrics]) -> HealthReport:
        """Calculate health score from channel metrics.
        Weights: CTR 25%, AVD 25%, views trend 20%, subscriber growth 15%, revenue 15%.
        """
        if not metrics:
            return HealthReport(
                channel_id="",
                severity=HealthSeverity.CRITICAL,
                health_score=0.0,
                trend_7d=0.0,
                trend_30d=0.0,
                trend_90d=0.0,
                anomalies=[],
                generated_at=datetime.now(timezone.utc),
            )

        channel_id = metrics[0].channel_id

        # Calculate component scores (0-10 scale). A component whose source data
        # is entirely absent (all zeros) is UNAVAILABLE, not bad: the public
        # Analytics API never returns impressions/CTR, and revenue is 0 for any
        # channel not yet in YPP. Excluding + renormalizing keeps the 0-100
        # scale honest instead of silently punishing young channels.
        ctr_vals = [m.ctr for m in metrics]
        rev_vals = [m.revenue for m in metrics]
        components: list[tuple[float, float]] = [  # (score 0-10, weight)
            (self._normalize_avd(mean(m.avd_percent for m in metrics)), 2.5),
            (self._calculate_views_trend(metrics), 2.0),
            (self._normalize_sub_growth(sum(m.subscriber_change for m in metrics)), 1.5),
        ]
        if any(v > 0 for v in ctr_vals):
            components.append((self._normalize_ctr(mean(ctr_vals)), 2.5))
        if any(v > 0 for v in rev_vals):
            components.append((self._normalize_revenue(mean(rev_vals)), 1.5))

        total_weight = sum(w for _, w in components)
        # Renormalize so the max stays 100 regardless of available components.
        health_score = sum(s * w for s, w in components) / total_weight * 10.0

        return HealthReport(
            channel_id=channel_id,
            severity=HealthSeverity.HEALTHY,  # Will be updated by TrendAnalyzer
            health_score=min(100.0, max(0.0, health_score)),
            trend_7d=0.0,  # Will be calculated by TrendAnalyzer
            trend_30d=0.0,
            trend_90d=0.0,
            anomalies=[],
            generated_at=datetime.now(timezone.utc),
        )

    def _normalize_ctr(self, ctr: float) -> float:
        """Normalize CTR to 0-10 scale. 5% = 10, 2% = 0."""
        return min(10.0, max(0.0, (ctr - 2.0) / 0.3))

    def _normalize_avd(self, avd_percent: float) -> float:
        """Normalize AVD to 0-10 scale. 50% = 10, 20% = 0."""
        return min(10.0, max(0.0, (avd_percent - 20.0) / 3.0))

    def _calculate_views_trend(self, metrics: list[ChannelMetrics]) -> float:
        """Calculate views trend score 0-10 based on growth rate."""
        if len(metrics) < 2:
            return 5.0

        first_views = metrics[0].views
        last_views = metrics[-1].views

        if first_views == 0:
            return 5.0

        growth_rate = (last_views - first_views) / first_views
        # Growth rate 0.5 = 10, -0.5 = 0
        return min(10.0, max(0.0, (growth_rate + 0.5) / 0.1))

    def _normalize_sub_growth(self, total_subs: float) -> float:
        """Normalize subscriber growth to 0-10 scale. 100 = 10, -50 = 0."""
        return min(10.0, max(0.0, (total_subs + 50) / 15.0))

    def _normalize_revenue(self, avg_revenue: float) -> float:
        """Normalize revenue to 0-10 scale. $10 = 10, $0 = 0."""
        return min(10.0, max(0.0, avg_revenue))


class TrendAnalyzer:
    """Detect declining trends via moving averages. Z-score anomaly detection."""

    def analyze(self, metrics: list[ChannelMetrics]) -> HealthReport:
        """Analyze trends and classify severity."""
        if not metrics:
            return HealthReport(
                channel_id="",
                severity=HealthSeverity.CRITICAL,
                health_score=0.0,
                trend_7d=0.0,
                trend_30d=0.0,
                trend_90d=0.0,
                anomalies=[],
                generated_at=datetime.now(timezone.utc),
            )

        channel_id = metrics[0].channel_id

        # Calculate trends
        trend_7d = self._calculate_trend(metrics, 7)
        trend_30d = self._calculate_trend(metrics, 30)
        trend_90d = self._calculate_trend(metrics, 90)

        # Detect anomalies
        views_series = [m.views for m in metrics]
        ctr_series = [m.ctr for m in metrics]
        anomalies = []
        anomalies.extend(self.detect_anomaly(views_series))
        anomalies.extend(self.detect_anomaly(ctr_series))

        # Classify severity
        severity = self.classify_severity(trend_7d, trend_30d, trend_90d)

        return HealthReport(
            channel_id=channel_id,
            severity=severity,
            health_score=0.0,  # Will be calculated by HealthScorer
            trend_7d=trend_7d,
            trend_30d=trend_30d,
            trend_90d=trend_90d,
            anomalies=[a.metric_name for a in anomalies],
            generated_at=datetime.now(timezone.utc),
        )

    def detect_anomaly(self, metric_series: list[float], threshold: float = 2.0) -> list[Anomaly]:
        """Detect anomalies using z-score."""
        if len(metric_series) < 3:
            return []

        anomalies = []
        mean_val = mean(metric_series)
        try:
            std_val = stdev(metric_series)
        except:
            std_val = 1.0

        if std_val == 0:
            return []

        for i, value in enumerate(metric_series):
            z_score = (value - mean_val) / std_val
            if abs(z_score) > threshold:
                direction = "up" if z_score > 0 else "down"
                anomalies.append(Anomaly(
                    metric_name="metric",
                    value=value,
                    z_score=z_score,
                    direction=direction,
                    detected_at=datetime.now(timezone.utc),
                ))

        return anomalies

    def moving_average(self, values: list[float], window: int) -> list[float]:
        """Calculate moving average with given window."""
        if len(values) < window:
            return []

        ma = []
        for i in range(len(values) - window + 1):
            window_values = values[i:i + window]
            ma.append(mean(window_values))
        return ma

    def classify_severity(self, trend_7d: float, trend_30d: float, trend_90d: float,
                         consecutive_low_days: int = 0) -> HealthSeverity:
        """Classify health severity based on trends."""
        # DEAD: views below threshold for 14+ days
        if consecutive_low_days >= 14:
            return HealthSeverity.DEAD

        # CRITICAL: 7d trend < -30% OR 30d trend < -25%
        if trend_7d < -30 or trend_30d < -25:
            return HealthSeverity.CRITICAL

        # WARNING: 7d trend < -15% OR 30d trend < -10%
        if trend_7d < -15 or trend_30d < -10:
            return HealthSeverity.WARNING

        # HEALTHY: stable or growing
        return HealthSeverity.HEALTHY

    def _calculate_trend(self, metrics: list[ChannelMetrics], days: int) -> float:
        """Calculate percentage trend over N days."""
        if len(metrics) < 2:
            return 0.0

        recent = metrics[:min(days, len(metrics))]
        if len(recent) < 2:
            return 0.0

        first_views = recent[0].views
        last_views = recent[-1].views

        if first_views == 0:
            return 0.0

        return ((last_views - first_views) / first_views) * 100
