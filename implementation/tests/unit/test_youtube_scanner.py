"""Tests for YouTube Competitor Scanner."""

import pytest
import httpx

from omnicast.discovery.youtube_scanner import YouTubeScanner, OUTLIER_MULTIPLIER
from omnicast.discovery.models import DiscoveryConfig, TopicRawData
from omnicast.models.enums import Niche, Market, TopicSource


def _v(video_id: str, title: str, views: int, published_at: str, description: str = "") -> dict:
    """Build a minimal video dict compatible with _find_outliers."""
    likes = max(1, views // 100)
    comments = max(0, views // 500)
    engagement_rate = round((likes + comments) / views, 4) if views > 0 else 0.0
    return {
        "video_id": video_id,
        "title": title,
        "description": description,
        "views": views,
        "likes": likes,
        "comments": comments,
        "engagement_rate": engagement_rate,
        "duration_minutes": 10.0,
        "published_at": published_at,
        "tags": [],
    }


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
            _v("v1", "Normal 1", 10000, "2025-01-01"),
            _v("v2", "Normal 2", 12000, "2025-01-02"),
            _v("v3", "Normal 3", 11000, "2025-01-03"),
            _v("v4", "Outlier!", 500000, "2025-01-04"),
        ]
        outliers = YouTubeScanner._find_outliers(
            videos, "UC_TEST", Niche.FINANCE, Market.US,
        )
        assert len(outliers) == 1
        assert outliers[0].title == "Outlier!"
        assert outliers[0].raw_metrics["outlier_ratio"] > OUTLIER_MULTIPLIER

    def test_no_outliers_when_all_similar(self):
        videos = [
            _v(f"v{i}", f"Vid {i}", 10000 + i * 100, "2025-01-01")
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
            _v("v1", "Solo", 100000, "2025-01-01"),
        ]
        outliers = YouTubeScanner._find_outliers(
            videos, "UC_TEST", Niche.FINANCE, Market.US,
        )
        assert outliers == []

    def test_outlier_has_correct_source(self):
        videos = [
            _v(f"v{i}", f"V{i}", 1000, "2025-01-01")
            for i in range(5)
        ] + [
            _v("vX", "Big Hit", 100000, "2025-01-06", "Big vid"),
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
            _v(f"v{i}", f"V{i}", 1000, "2025-01-01")
            for i in range(4)
        ] + [
            _v("vBig", "Big", 9000, "2025-01-05"),
        ]
        outliers = YouTubeScanner._find_outliers(
            videos, "UC_TEST", Niche.FINANCE, Market.US,
        )
        assert len(outliers) == 1
        assert outliers[0].raw_metrics["outlier_ratio"] == pytest.approx(9.0, rel=0.01)
        assert outliers[0].raw_metrics["channel_median_views"] == pytest.approx(1000.0)


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
