# TASK_B: YouTube Analytics Crawler

## Model: sonnet | Dependencies: TASK_A complete

Pull channel + video metrics from YouTube Analytics API daily.

## Interface

### src/omnicast/analytics/crawler.py

```python
class AnalyticsCrawler:
    """Pull YouTube Analytics data. Daily channel metrics + per-video metrics."""
    def __init__(self, oauth_manager: OAuth2Manager)
    async def collect_channel_metrics(self, channel_id: str, date_range: int = 7) -> list[ChannelMetrics]
    async def collect_video_metrics(self, video_id: str) -> VideoMetrics
    async def collect_retention_curve(self, video_id: str) -> list[float]
    async def batch_collect(self, channel_ids: list[str]) -> dict[str, list[ChannelMetrics]]
```

## DO NOT

- No actual API calls in tests — mock google-api-python-client
- Must use OAuth2Manager from Phase 5 for credentials
- Dry-run mode returns mock metrics
- Rate limit: max 5 concurrent API calls

## Tests

### tests/unit/test_analytics_crawler.py

```python
import pytest
from datetime import datetime, date, timezone
from unittest.mock import MagicMock, AsyncMock, patch
from omnicast.analytics.crawler import AnalyticsCrawler
from omnicast.analytics.models import ChannelMetrics, VideoMetrics
from omnicast.upload.oauth import OAuth2Manager


@pytest.fixture
def mock_oauth():
    oauth = MagicMock(spec=OAuth2Manager)
    oauth.get_credentials = AsyncMock(return_value=MagicMock())
    return oauth


@pytest.fixture
def crawler(mock_oauth):
    return AnalyticsCrawler(oauth_manager=mock_oauth)


class TestCollectChannelMetrics:
    @pytest.mark.asyncio
    async def test_returns_list(self, crawler):
        with patch.object(crawler, "collect_channel_metrics",
                          new_callable=AsyncMock,
                          return_value=[
                              ChannelMetrics(
                                  channel_id="ch1", date=date(2025, 6, 1),
                                  impressions=10000, ctr=4.5, views=450,
                                  avd_seconds=180, avd_percent=42,
                                  watch_time_hours=22.5, subscriber_change=10,
                                  revenue=5.0, rpm=11.1,
                                  top_traffic_sources={"browse": 0.5},
                              )
                          ]):
            result = await crawler.collect_channel_metrics("ch1")
            assert len(result) == 1
            assert isinstance(result[0], ChannelMetrics)

    @pytest.mark.asyncio
    async def test_date_range(self, crawler):
        with patch.object(crawler, "collect_channel_metrics",
                          new_callable=AsyncMock, return_value=[]):
            result = await crawler.collect_channel_metrics("ch1", date_range=30)
            assert isinstance(result, list)


class TestCollectVideoMetrics:
    @pytest.mark.asyncio
    async def test_returns_video_metrics(self, crawler):
        mock_vm = VideoMetrics(
            video_id="v1", channel_id="ch1",
            published_at=datetime.now(timezone.utc),
            views_24h=500, views_48h=800, views_7d=2000,
            ctr=5.0, avd_seconds=200, avd_percent=45,
            retention_curve=[100, 85, 72, 60],
            likes=50, comments=10, shares=5,
            traffic_sources={"browse": 0.5},
        )
        with patch.object(crawler, "collect_video_metrics",
                          new_callable=AsyncMock, return_value=mock_vm):
            result = await crawler.collect_video_metrics("v1")
            assert isinstance(result, VideoMetrics)
            assert result.views_24h == 500


class TestCollectRetentionCurve:
    @pytest.mark.asyncio
    async def test_returns_list_of_floats(self, crawler):
        with patch.object(crawler, "collect_retention_curve",
                          new_callable=AsyncMock,
                          return_value=[100, 90, 80, 70, 60]):
            result = await crawler.collect_retention_curve("v1")
            assert all(isinstance(x, (int, float)) for x in result)


class TestBatchCollect:
    @pytest.mark.asyncio
    async def test_returns_dict(self, crawler):
        with patch.object(crawler, "batch_collect",
                          new_callable=AsyncMock,
                          return_value={"ch1": [], "ch2": []}):
            result = await crawler.batch_collect(["ch1", "ch2"])
            assert isinstance(result, dict)
            assert "ch1" in result
            assert "ch2" in result
```
