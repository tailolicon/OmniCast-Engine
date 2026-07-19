# TASK_F: ROI Calculator + Knowledge Base Decay

## Model: sonnet | Dependencies: TASK_A complete

Per-video ROI tracking + KB pattern expiration (trend-based, 30-day default).

## Interface

### src/omnicast/analytics/roi.py

```python
class ROICalculator:
    """Calculate ROI per video, per niche, per channel."""
    def calculate_video_roi(self, video_id: str, costs: dict[str, float], revenue: float) -> ROIRecord
    def aggregate_by_niche(self, records: list[ROIRecord]) -> dict[str, float]
    def aggregate_by_channel(self, records: list[ROIRecord]) -> dict[str, float]
    def find_negative_roi_niches(self, records: list[ROIRecord], min_videos: int = 5) -> list[str]
```

### src/omnicast/analytics/kb_decay.py

```python
class KBDecayManager:
    """Expire stale KB patterns. Trend-based = shorter TTL, evergreen = longer."""
    def __init__(self, default_ttl_days: int = 30)
    def should_expire(self, pattern_created: datetime, is_trend: bool, last_used: datetime | None = None) -> bool
    def get_expired_patterns(self, patterns: list[dict]) -> list[str]
    def get_decay_stats(self, patterns: list[dict]) -> dict[str, int]
```

## DO NOT

- ROI = (revenue - cost) / cost
- cost_breakdown keys: "claude_api", "gpu_hours", "bandwidth", "nas_storage"
- KB decay: trend patterns expire after default_ttl, evergreen after 3x default_ttl
- Patterns used recently get TTL extension (+50%)

## Tests

### tests/unit/test_roi.py

```python
import pytest
from omnicast.analytics.roi import ROICalculator
from omnicast.analytics.models import ROIRecord


@pytest.fixture
def calculator():
    return ROICalculator()


class TestCalculateVideoROI:
    def test_positive_roi(self, calculator):
        record = calculator.calculate_video_roi(
            "v1", {"claude_api": 0.5, "gpu_hours": 1.2}, revenue=5.0,
        )
        assert isinstance(record, ROIRecord)
        assert record.roi > 0
        assert record.total_cost == pytest.approx(1.7)

    def test_negative_roi(self, calculator):
        record = calculator.calculate_video_roi(
            "v2", {"claude_api": 1.0, "gpu_hours": 3.0}, revenue=0.5,
        )
        assert record.roi < 0

    def test_zero_revenue(self, calculator):
        record = calculator.calculate_video_roi(
            "v3", {"claude_api": 0.5}, revenue=0,
        )
        assert record.roi == -1.0

    def test_cost_breakdown_summed(self, calculator):
        record = calculator.calculate_video_roi(
            "v4", {"claude_api": 1.0, "gpu_hours": 2.0, "bandwidth": 0.5},
            revenue=10.0,
        )
        assert record.total_cost == pytest.approx(3.5)


class TestAggregateByNiche:
    def test_groups_correctly(self, calculator):
        records = [
            ROIRecord(video_id="v1", channel_id="ch1", niche="finance",
                      cost_breakdown={}, total_cost=1, revenue=3, roi=2.0),
            ROIRecord(video_id="v2", channel_id="ch1", niche="finance",
                      cost_breakdown={}, total_cost=2, revenue=4, roi=1.0),
            ROIRecord(video_id="v3", channel_id="ch1", niche="cooking",
                      cost_breakdown={}, total_cost=1, revenue=0.5, roi=-0.5),
        ]
        result = calculator.aggregate_by_niche(records)
        assert "finance" in result
        assert "cooking" in result


class TestFindNegativeROI:
    def test_finds_negative_niches(self, calculator):
        records = [
            ROIRecord(video_id=f"v{i}", channel_id="ch1", niche="bad_niche",
                      cost_breakdown={}, total_cost=5, revenue=1, roi=-0.8)
            for i in range(6)
        ]
        result = calculator.find_negative_roi_niches(records, min_videos=5)
        assert "bad_niche" in result

    def test_ignores_small_sample(self, calculator):
        records = [
            ROIRecord(video_id="v1", channel_id="ch1", niche="new_niche",
                      cost_breakdown={}, total_cost=5, revenue=1, roi=-0.8),
        ]
        result = calculator.find_negative_roi_niches(records, min_videos=5)
        assert "new_niche" not in result
```

### tests/unit/test_kb_decay.py

```python
import pytest
from datetime import datetime, timezone, timedelta
from omnicast.analytics.kb_decay import KBDecayManager


@pytest.fixture
def manager():
    return KBDecayManager(default_ttl_days=30)


class TestShouldExpire:
    def test_fresh_trend_not_expired(self, manager):
        created = datetime.now(timezone.utc) - timedelta(days=5)
        assert not manager.should_expire(created, is_trend=True)

    def test_old_trend_expired(self, manager):
        created = datetime.now(timezone.utc) - timedelta(days=35)
        assert manager.should_expire(created, is_trend=True)

    def test_evergreen_longer_ttl(self, manager):
        created = datetime.now(timezone.utc) - timedelta(days=35)
        assert not manager.should_expire(created, is_trend=False)

    def test_evergreen_expired(self, manager):
        created = datetime.now(timezone.utc) - timedelta(days=95)
        assert manager.should_expire(created, is_trend=False)

    def test_recently_used_extends_ttl(self, manager):
        created = datetime.now(timezone.utc) - timedelta(days=35)
        last_used = datetime.now(timezone.utc) - timedelta(days=2)
        assert not manager.should_expire(created, is_trend=True, last_used=last_used)


class TestGetExpiredPatterns:
    def test_returns_expired_ids(self, manager):
        now = datetime.now(timezone.utc)
        patterns = [
            {"id": "p1", "created": now - timedelta(days=5), "is_trend": True},
            {"id": "p2", "created": now - timedelta(days=40), "is_trend": True},
            {"id": "p3", "created": now - timedelta(days=100), "is_trend": False},
        ]
        expired = manager.get_expired_patterns(patterns)
        assert "p2" in expired
        assert "p3" in expired
        assert "p1" not in expired


class TestGetDecayStats:
    def test_returns_counts(self, manager):
        now = datetime.now(timezone.utc)
        patterns = [
            {"id": "p1", "created": now - timedelta(days=5), "is_trend": True},
            {"id": "p2", "created": now - timedelta(days=40), "is_trend": True},
        ]
        stats = manager.get_decay_stats(patterns)
        assert "total" in stats
        assert "expired" in stats
        assert "active" in stats
        assert stats["total"] == 2
```
