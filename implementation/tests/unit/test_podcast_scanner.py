"""Tests for Podcast Scanner."""

import pytest
import httpx

from omnicast.discovery.podcast_scanner import PodcastScanner, MIN_LISTEN_SCORE
from omnicast.discovery.models import DiscoveryConfig
from omnicast.models.enums import Niche, Market, TopicSource


@pytest.fixture
def config():
    return DiscoveryConfig(
        niche=Niche.MYTHOLOGY,
        markets=[Market.US],
        podcast_keywords=["greek mythology", "norse gods"],
    )


def _podcast_search_response(episodes: list[dict]) -> dict:
    """Mock Podcast Index search response."""
    return {
        "feeds": [
            {
                "title": ep.get("podcast_title", "Test Podcast"),
                "id": ep.get("episode_id", 12345),
                "description": ep.get("title", "Episode"),
                "itunesInfo": {"listenScore": ep.get("listen_score", 50)},
            }
            for ep in episodes
        ],
        "count": len(episodes),
    }


class TestAuthHeaders:
    def test_headers_contain_required_keys(self, config):
        scanner = PodcastScanner(config, api_key="testkey", api_secret="testsecret")
        headers = scanner._auth_headers()
        assert "X-Auth-Date" in headers
        assert "X-Auth-Key" in headers
        assert headers["X-Auth-Key"] == "testkey"
        assert "Authorization" in headers
        assert len(headers["Authorization"]) == 40  # SHA-1 hex digest


class TestSearchEpisodes:
    @pytest.mark.asyncio
    async def test_returns_qualifying_episodes(self, config):
        resp_data = _podcast_search_response([
            {"title": "Greek Gods Deep Dive", "listen_score": 85, "podcast_title": "Myth Pod"},
            {"title": "Low Score Ep", "listen_score": 30, "podcast_title": "Small Pod"},
            {"title": "Norse Mythology 101", "listen_score": 92, "podcast_title": "Viking Cast"},
        ])
        transport = httpx.MockTransport(lambda req: httpx.Response(200, json=resp_data))
        client = httpx.AsyncClient(transport=transport)
        scanner = PodcastScanner(config, api_key="k", api_secret="s", http_client=client)
        episodes = await scanner._search_episodes("greek mythology")
        # Only listen_score >= 70 should pass
        assert len(episodes) == 2
        scores = [e["listen_score"] for e in episodes]
        assert all(s >= MIN_LISTEN_SCORE for s in scores)

    @pytest.mark.asyncio
    async def test_empty_on_no_results(self, config):
        transport = httpx.MockTransport(
            lambda req: httpx.Response(200, json={"feeds": [], "count": 0})
        )
        client = httpx.AsyncClient(transport=transport)
        scanner = PodcastScanner(config, api_key="k", api_secret="s", http_client=client)
        episodes = await scanner._search_episodes("nonexistent topic")
        assert episodes == []


class TestPodcastScannerIntegration:
    @pytest.mark.asyncio
    async def test_full_scan(self, config):
        resp_data = _podcast_search_response([
            {"title": "Myth Deep Dive", "listen_score": 80, "podcast_title": "MythCast"},
        ])
        transport = httpx.MockTransport(lambda req: httpx.Response(200, json=resp_data))
        client = httpx.AsyncClient(transport=transport)
        scanner = PodcastScanner(config, api_key="k", api_secret="s", http_client=client)
        result = await scanner.scan()
        assert result.success
        assert result.source == TopicSource.PODCAST
        assert result.count >= 1

    @pytest.mark.asyncio
    async def test_scan_api_error(self, config):
        transport = httpx.MockTransport(lambda req: httpx.Response(500))
        client = httpx.AsyncClient(transport=transport)
        scanner = PodcastScanner(config, api_key="k", api_secret="s", http_client=client)
        result = await scanner.scan()
        assert result.success is False
        assert result.error is not None
