import pytest
from omnicast.analytics.retention import RetentionAnalyst


@pytest.fixture
def analyst():
    return RetentionAnalyst()


class TestFindDropPoints:
    def test_no_drops(self, analyst):
        curve = [100, 98, 96, 94, 92, 90]
        drops = analyst.find_drop_points(curve)
        assert len(drops) == 0

    def test_single_drop(self, analyst):
        curve = [100, 95, 90, 80, 60, 55, 50]  # drop at index 3→4
        drops = analyst.find_drop_points(curve)
        assert len(drops) >= 1

    def test_multiple_drops(self, analyst):
        curve = [100, 85, 80, 60, 55, 35, 30]
        drops = analyst.find_drop_points(curve)
        assert len(drops) >= 2

    def test_custom_threshold(self, analyst):
        curve = [100, 93, 90, 85]
        drops_strict = analyst.find_drop_points(curve, threshold=3.0)
        drops_loose = analyst.find_drop_points(curve, threshold=10.0)
        assert len(drops_strict) >= len(drops_loose)

    def test_empty_curve(self, analyst):
        drops = analyst.find_drop_points([])
        assert drops == []


class TestCorrelateWithScript:
    def test_maps_drops_to_segments(self, analyst):
        drops = [{"index": 3, "drop_pct": 15.0}]
        segments = ["intro", "point 1", "transition", "point 2", "outro"]
        result = analyst.correlate_with_script(drops, segments)
        assert len(result) >= 1
        assert "segment" in result[0] or "index" in result[0]

    def test_empty_drops(self, analyst):
        result = analyst.correlate_with_script([], ["intro", "body"])
        assert result == []


class TestSummarizePatterns:
    def test_aggregates(self, analyst):
        analyses = [
            {"drops": [{"segment": "transition", "drop_pct": 12}]},
            {"drops": [{"segment": "transition", "drop_pct": 10}]},
            {"drops": [{"segment": "intro", "drop_pct": 8}]},
        ]
        patterns = analyst.summarize_patterns(analyses)
        assert isinstance(patterns, dict)
