# TASK_B: YouTube Competitor Scanner

## Model: sonnet
## Estimated time: 40 minutes
## Dependencies: TASK_A

## Overview

Scan YouTube competitor channels to find outlier videos (views > 3x channel median).
Uses YouTube Data API v3 via httpx (async). Extract video metadata for topic candidates.

## Files

| File | Lines | Description |
|------|------:|-------------|
| `src/omnicast/discovery/youtube_scanner.py` | ~200 | YouTubeScanner |
| `tests/unit/test_youtube_scanner.py` | ~220 | Pre-written tests |

## Context Files

- `src/omnicast/discovery/base.py` — BaseScanner (from TASK_A)
- `src/omnicast/discovery/models.py` — TopicRawData, DiscoveryConfig
- `src/omnicast/config/settings.py` — Settings (youtube_quota_daily)
- `src/omnicast/models/enums.py` — TopicSource.YOUTUBE_COMPETITOR

## Interface Definition

### src/omnicast/discovery/youtube_scanner.py

```python
"""YouTube competitor channel scanner.

Finds outlier videos (views > 3x channel median) from competitor channels.
Uses YouTube Data API v3 via httpx.
"""

from __future__ import annotations

import statistics

import httpx
import structlog

from omnicast.discovery.base import BaseScanner
from omnicast.discovery.models import TopicRawData, DiscoveryConfig
from omnicast.models.enums import TopicSource, Niche, Market
from omnicast.shared.errors import DiscoveryError

logger = structlog.get_logger()

YOUTUBE_API_BASE = "https://www.googleapis.com/youtube/v3"
OUTLIER_MULTIPLIER = 3.0


class YouTubeScanner(BaseScanner):
    """Scan competitor channels for outlier videos.

    Algorithm:
    1. For each channel_id in config.competitor_channel_ids:
       a. Fetch recent uploads (playlistItems.list, maxResults=50)
       b. Batch fetch video stats (videos.list, part=statistics,snippet)
       c. Calculate channel median views
       d. Filter outliers: views > OUTLIER_MULTIPLIER * median
    2. Convert outliers to TopicRawData with raw_metrics:
       {"views": int, "channel_median": float, "outlier_ratio": float,
        "channel_id": str, "video_id": str, "published_at": str}
    """

    source = TopicSource.YOUTUBE_COMPETITOR

    def __init__(
        self,
        config: DiscoveryConfig,
        api_key: str,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        """
        api_key: YouTube Data API v3 key.
        http_client: injectable for testing.
        """
        super().__init__(config)
        self.api_key = api_key
        self._http = http_client or httpx.AsyncClient(timeout=30)

    async def _scan(self) -> list[TopicRawData]:
        """Scan all competitor channels, return outlier topics."""
        ...

    async def _get_channel_uploads_playlist_id(self, channel_id: str) -> str:
        """Get the 'uploads' playlist ID for a channel.

        GET channels?part=contentDetails&id={channel_id}
        Return contentDetails.relatedPlaylists.uploads
        Raise DiscoveryError if channel not found.
        """
        ...

    async def _get_recent_video_ids(
        self, playlist_id: str, max_results: int = 50,
    ) -> list[str]:
        """Fetch recent video IDs from an uploads playlist.

        GET playlistItems?part=contentDetails&playlistId={id}&maxResults={max_results}
        Return list of video IDs.
        """
        ...

    async def _get_video_stats(self, video_ids: list[str]) -> list[dict]:
        """Batch fetch video statistics + snippet.

        GET videos?part=statistics,snippet&id={comma_separated_ids}
        YouTube allows max 50 IDs per request.
        Return list of {"video_id", "title", "views", "published_at", "description"}.
        """
        ...

    @staticmethod
    def _find_outliers(
        videos: list[dict],
        channel_id: str,
        niche: Niche,
        market: Market,
    ) -> list[TopicRawData]:
        """Filter videos with views > 3x median.

        Static for testability.
        Return TopicRawData for each outlier.
        """
        ...
```

## DO NOT

- Do NOT use youtube-dl, yt-dlp, or browser automation — API only
- Do NOT download video content or transcripts — metadata only in this task
- Do NOT handle API quota tracking — that's a future concern
- Do NOT paginate beyond 50 results per channel — sufficient for outlier detection

## Tests

### tests/unit/test_youtube_scanner.py

```python
"""Tests for YouTube Competitor Scanner."""

import pytest
import httpx

from omnicast.discovery.youtube_scanner import YouTubeScanner, OUTLIER_MULTIPLIER
from omnicast.discovery.models import DiscoveryConfig, TopicRawData
from omnicast.models.enums import Niche, Market, TopicSource


@pytest.fixture
def config():
    return DiscoveryConfig(
        niche=Niche.FINANCE,
        markets=[Market.US],
        competitor_channel_ids=["UC_FAKE_001", "UC_FAKE_002"],
    )


def _channel_response(channel_id: str, uploads_playlist: str) -> dict:
    """Mock YouTube channels.list response."""
    return {
        "items": [{
            "id": channel_id,
            "contentDetails": {
                "relatedPlaylists": {"uploads": uploads_playlist}
            },
        }]
    }


def _playlist_items_response(video_ids: list[str]) -> dict:
    """Mock YouTube playlistItems.list response."""
    return {
        "items": [
            {"contentDetails": {"videoId": vid}} for vid in video_ids
        ]
    }


def _videos_response(videos: list[dict]) -> dict:
    """Mock YouTube videos.list response.

    videos: list of {"id", "title", "viewCount", "publishedAt"}
    """
    return {
        "items": [
            {
                "id": v["id"],
                "snippet": {
                    "title": v.get("title", f"Video {v['id']}"),
                    "publishedAt": v.get("publishedAt", "2025-01-01T00:00:00Z"),
                    "description": v.get("description", ""),
                },
                "statistics": {
                    "viewCount": str(v["viewCount"]),
                },
            }
            for v in videos
        ]
    }


class TestFindOutliers:
    """Test static outlier detection logic (no HTTP)."""

    def test_finds_outlier_above_3x_median(self):
        videos = [
            {"video_id": "v1", "title": "Normal 1", "views": 10000, "published_at": "2025-01-01", "description": ""},
            {"video_id": "v2", "title": "Normal 2", "views": 12000, "published_at": "2025-01-02", "description": ""},
            {"video_id": "v3", "title": "Normal 3", "views": 11000, "published_at": "2025-01-03", "description": ""},
            {"video_id": "v4", "title": "Outlier!", "views": 500000, "published_at": "2025-01-04", "description": ""},
        ]
        outliers = YouTubeScanner._find_outliers(
            videos, "UC_TEST", Niche.FINANCE, Market.US,
        )
        assert len(outliers) == 1
        assert outliers[0].title == "Outlier!"
        assert outliers[0].raw_metrics["outlier_ratio"] > OUTLIER_MULTIPLIER

    def test_no_outliers_when_all_similar(self):
        videos = [
            {"video_id": f"v{i}", "title": f"Vid {i}", "views": 10000 + i * 100,
             "published_at": "2025-01-01", "description": ""}
            for i in range(10)
        ]
        outliers = YouTubeScanner._find_outliers(
            videos, "UC_TEST", Niche.TECH, Market.US,
        )
        assert len(outliers) == 0

    def test_empty_videos_returns_empty(self):
        outliers = YouTubeScanner._find_outliers(
            [], "UC_TEST", Niche.FINANCE, Market.US,
        )
        assert outliers == []

    def test_single_video_no_outlier(self):
        """Can't compute median from 1 video, should return empty."""
        videos = [
            {"video_id": "v1", "title": "Solo", "views": 100000,
             "published_at": "2025-01-01", "description": ""},
        ]
        outliers = YouTubeScanner._find_outliers(
            videos, "UC_TEST", Niche.FINANCE, Market.US,
        )
        assert outliers == []

    def test_outlier_has_correct_source(self):
        videos = [
            {"video_id": f"v{i}", "title": f"V{i}", "views": 1000,
             "published_at": "2025-01-01", "description": ""}
            for i in range(5)
        ] + [
            {"video_id": "vX", "title": "Big Hit", "views": 100000,
             "published_at": "2025-01-06", "description": "Big vid"},
        ]
        outliers = YouTubeScanner._find_outliers(
            videos, "UC_TEST", Niche.FINANCE, Market.US,
        )
        assert len(outliers) == 1
        assert outliers[0].source == TopicSource.YOUTUBE_COMPETITOR
        assert outliers[0].niche == Niche.FINANCE
        assert outliers[0].market == Market.US
        assert outliers[0].raw_metrics["channel_id"] == "UC_TEST"
        assert outliers[0].raw_metrics["video_id"] == "vX"

    def test_outlier_ratio_calculated(self):
        # Median of [1000, 1000, 1000, 1000, 9000] = 1000
        # 9000 / 1000 = 9.0 > 3.0
        videos = [
            {"video_id": f"v{i}", "title": f"V{i}", "views": 1000,
             "published_at": "2025-01-01", "description": ""}
            for i in range(4)
        ] + [
            {"video_id": "vBig", "title": "Big", "views": 9000,
             "published_at": "2025-01-05", "description": ""},
        ]
        outliers = YouTubeScanner._find_outliers(
            videos, "UC_TEST", Niche.FINANCE, Market.US,
        )
        assert len(outliers) == 1
        assert outliers[0].raw_metrics["outlier_ratio"] == pytest.approx(9.0, rel=0.01)
        assert outliers[0].raw_metrics["channel_median"] == pytest.approx(1000.0)


class TestYouTubeScannerHTTP:
    """Test HTTP interactions with mocked transport."""

    @pytest.mark.asyncio
    async def test_get_uploads_playlist_id(self, config):
        responses = [
            httpx.Response(200, json=_channel_response("UC_FAKE_001", "UU_FAKE_001")),
        ]
        transport = httpx.MockTransport(lambda req: responses.pop(0))
        client = httpx.AsyncClient(transport=transport)
        scanner = YouTubeScanner(config, api_key="fake_key", http_client=client)
        playlist_id = await scanner._get_channel_uploads_playlist_id("UC_FAKE_001")
        assert playlist_id == "UU_FAKE_001"

    @pytest.mark.asyncio
    async def test_get_uploads_playlist_not_found(self, config):
        transport = httpx.MockTransport(
            lambda req: httpx.Response(200, json={"items": []})
        )
        client = httpx.AsyncClient(transport=transport)
        scanner = YouTubeScanner(config, api_key="fake_key", http_client=client)
        from omnicast.shared.errors import DiscoveryError
        with pytest.raises(DiscoveryError):
            await scanner._get_channel_uploads_playlist_id("UC_NONEXISTENT")

    @pytest.mark.asyncio
    async def test_get_recent_video_ids(self, config):
        resp = _playlist_items_response(["v1", "v2", "v3"])
        transport = httpx.MockTransport(lambda req: httpx.Response(200, json=resp))
        client = httpx.AsyncClient(transport=transport)
        scanner = YouTubeScanner(config, api_key="fake_key", http_client=client)
        ids = await scanner._get_recent_video_ids("UU_FAKE")
        assert ids == ["v1", "v2", "v3"]

    @pytest.mark.asyncio
    async def test_get_video_stats(self, config):
        videos_data = [
            {"id": "v1", "title": "Vid 1", "viewCount": 5000},
            {"id": "v2", "title": "Vid 2", "viewCount": 8000},
        ]
        resp = _videos_response(videos_data)
        transport = httpx.MockTransport(lambda req: httpx.Response(200, json=resp))
        client = httpx.AsyncClient(transport=transport)
        scanner = YouTubeScanner(config, api_key="fake_key", http_client=client)
        stats = await scanner._get_video_stats(["v1", "v2"])
        assert len(stats) == 2
        assert stats[0]["views"] == 5000
        assert stats[1]["views"] == 8000

    @pytest.mark.asyncio
    async def test_full_scan_with_mock(self, config):
        """Integration test: full scan with mocked responses."""
        call_count = {"n": 0}

        def mock_handler(request: httpx.Request):
            call_count["n"] += 1
            url = str(request.url)
            if "channels" in url:
                return httpx.Response(200, json=_channel_response("UC_FAKE_001", "UU_FAKE_001"))
            if "playlistItems" in url:
                return httpx.Response(200, json=_playlist_items_response(["v1", "v2", "v3"]))
            if "videos" in url:
                return httpx.Response(200, json=_videos_response([
                    {"id": "v1", "viewCount": 1000, "title": "Normal 1"},
                    {"id": "v2", "viewCount": 1200, "title": "Normal 2"},
                    {"id": "v3", "viewCount": 50000, "title": "Viral Hit"},
                ]))
            return httpx.Response(404)

        # Only use first channel
        config_single = DiscoveryConfig(
            niche=Niche.FINANCE,
            markets=[Market.US],
            competitor_channel_ids=["UC_FAKE_001"],
        )
        transport = httpx.MockTransport(mock_handler)
        client = httpx.AsyncClient(transport=transport)
        scanner = YouTubeScanner(config_single, api_key="fake", http_client=client)
        result = await scanner.scan()
        assert result.success
        assert result.count >= 1  # v3 is outlier (50k vs median ~1100)
        assert result.topics[0].raw_metrics["video_id"] == "v3"

    @pytest.mark.asyncio
    async def test_scan_handles_api_error(self, config):
        transport = httpx.MockTransport(
            lambda req: httpx.Response(500, json={"error": "Internal Server Error"})
        )
        client = httpx.AsyncClient(transport=transport)
        scanner = YouTubeScanner(config, api_key="fake", http_client=client)
        result = await scanner.scan()
        assert result.success is False
        assert result.error is not None
```
