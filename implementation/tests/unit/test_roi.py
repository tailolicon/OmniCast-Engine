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
