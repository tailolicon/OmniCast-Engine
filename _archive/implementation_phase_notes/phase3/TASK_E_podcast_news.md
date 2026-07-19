# TASK_E: Podcast Scanner + News RSS Scanner

## Model: sonnet
## Estimated time: 40 minutes
## Dependencies: TASK_A

## Overview

Two scanners in one task:

1. **PodcastScanner**: Query Podcast Index API for episodes with listenScore > 70.
   Extract episode titles as topic candidates (podcast → video = high gap score).

2. **NewsScanner**: Parse RSS feeds (feedparser). Count topic mentions in 24h window.
   Mentions > 10 = breaking trend.

## Files

| File | Lines | Description |
|------|------:|-------------|
| `src/omnicast/discovery/podcast_scanner.py` | ~140 | PodcastScanner |
| `src/omnicast/discovery/news_scanner.py` | ~140 | NewsScanner |
| `tests/unit/test_podcast_scanner.py` | ~160 | Pre-written tests |
| `tests/unit/test_news_scanner.py` | ~160 | Pre-written tests |

## Context Files

- `src/omnicast/discovery/base.py` — BaseScanner
- `src/omnicast/discovery/models.py` — TopicRawData, DiscoveryConfig
- `src/omnicast/models/enums.py` — TopicSource.PODCAST, TopicSource.NEWS_RSS

## Interface Definitions

### src/omnicast/discovery/podcast_scanner.py

```python
"""Podcast scanner using Podcast Index API.

Finds episodes with high listen scores matching niche keywords.
"""

from __future__ import annotations

import hashlib
import time

import httpx
import structlog

from omnicast.discovery.base import BaseScanner
from omnicast.discovery.models import TopicRawData, DiscoveryConfig
from omnicast.models.enums import TopicSource

logger = structlog.get_logger()

PODCAST_INDEX_BASE = "https://api.podcastindex.org/api/1.0"
MIN_LISTEN_SCORE = 70


class PodcastScanner(BaseScanner):
    """Scan Podcast Index for high-engagement episodes.

    Algorithm:
    1. For each keyword in config.podcast_keywords:
       a. Search episodes via Podcast Index API (search/byterm)
       b. Filter: listenScore >= MIN_LISTEN_SCORE (from feed-level metadata)
       c. Convert to TopicRawData with raw_metrics:
          {"listen_score": int, "podcast_title": str, "episode_id": int}
    2. Deduplicate by title (case-insensitive).

    Auth: Podcast Index uses API key + secret → SHA-1 header auth.
    """

    source = TopicSource.PODCAST

    def __init__(
        self,
        config: DiscoveryConfig,
        api_key: str = "",
        api_secret: str = "",
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        super().__init__(config)
        self.api_key = api_key
        self.api_secret = api_secret
        self._http = http_client or httpx.AsyncClient(timeout=30)

    def _auth_headers(self) -> dict[str, str]:
        """Generate Podcast Index auth headers.

        X-Auth-Date: epoch timestamp
        X-Auth-Key: api_key
        Authorization: SHA-1(api_key + api_secret + epoch)
        """
        epoch = str(int(time.time()))
        auth_hash = hashlib.sha1(
            (self.api_key + self.api_secret + epoch).encode()
        ).hexdigest()
        return {
            "X-Auth-Date": epoch,
            "X-Auth-Key": self.api_key,
            "Authorization": auth_hash,
            "User-Agent": "OmniCast/1.0",
        }

    async def _scan(self) -> list[TopicRawData]:
        """Search all podcast keywords, filter by listen score."""
        ...

    async def _search_episodes(self, keyword: str) -> list[dict]:
        """Search Podcast Index for episodes matching keyword.

        GET /search/byterm?q={keyword}&max=20
        Return list of {"title", "listen_score", "podcast_title", "episode_id"}.
        Filter by MIN_LISTEN_SCORE.
        """
        ...
```

### src/omnicast/discovery/news_scanner.py

```python
"""News RSS scanner using feedparser.

Counts topic keyword mentions across RSS feeds in 24h window.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone, timedelta
from collections import Counter

import feedparser
import structlog

from omnicast.discovery.base import BaseScanner
from omnicast.discovery.models import TopicRawData, DiscoveryConfig
from omnicast.models.enums import TopicSource

logger = structlog.get_logger()

MIN_MENTIONS = 10
LOOKBACK_HOURS = 24


class NewsScanner(BaseScanner):
    """Scan RSS feeds for breaking trends.

    Algorithm:
    1. Parse each RSS feed in config.rss_feeds
    2. Filter entries published within LOOKBACK_HOURS
    3. Count keyword mentions across all entries (title + summary)
    4. Keywords with mentions >= MIN_MENTIONS become TopicRawData
       raw_metrics: {"mention_count": int, "hours_since_first": float,
                     "feed_sources": list[str]}
    """

    source = TopicSource.NEWS_RSS

    def __init__(
        self,
        config: DiscoveryConfig,
        feed_fetcher=None,
    ) -> None:
        """
        feed_fetcher: callable(url) -> feedparser.FeedParserDict.
        Default uses feedparser.parse(). Injectable for testing.
        """
        super().__init__(config)
        self._fetch_feed = feed_fetcher or feedparser.parse

    async def _scan(self) -> list[TopicRawData]:
        """Parse all RSS feeds, count keyword mentions, return trends."""
        ...

    def _parse_feed(self, feed_url: str) -> list[dict]:
        """Parse one RSS feed, return entries within lookback window.

        Return list of {"title": str, "summary": str, "published": datetime, "link": str}.
        Skip entries without parseable published date.
        """
        ...

    @staticmethod
    def _count_keyword_mentions(
        entries: list[dict],
        keywords: list[str],
    ) -> dict[str, list[dict]]:
        """Count how many entries mention each keyword (case-insensitive).

        Check keyword presence in title + summary.
        Return {keyword: [matching_entries]}.
        """
        ...

    @staticmethod
    def _entries_to_topic(
        keyword: str,
        matching_entries: list[dict],
        niche,
        market,
    ) -> TopicRawData:
        """Convert keyword + matching entries to TopicRawData."""
        ...
```

## DO NOT

- Do NOT download or transcribe podcast audio — metadata only
- Do NOT use Whisper/TTS in this task — transcription is a future feature
- Do NOT implement feed caching/persistence — stateless scan
- Do NOT filter by language — that's handled by niche/market config

## Tests

### tests/unit/test_podcast_scanner.py

```python
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
```

### tests/unit/test_news_scanner.py

```python
"""Tests for News RSS Scanner."""

import pytest
from datetime import datetime, timezone, timedelta

from omnicast.discovery.news_scanner import (
    NewsScanner,
    MIN_MENTIONS,
    LOOKBACK_HOURS,
)
from omnicast.discovery.models import DiscoveryConfig, TopicRawData
from omnicast.models.enums import Niche, Market, TopicSource


@pytest.fixture
def config():
    return DiscoveryConfig(
        niche=Niche.FINANCE,
        markets=[Market.US],
        rss_feeds=["https://example.com/rss1", "https://example.com/rss2"],
        trends_keywords=["bitcoin", "inflation"],
    )


def _make_feed(entries):
    """Create a mock feedparser result."""
    class MockFeed:
        def __init__(self, items):
            self.entries = items
            self.bozo = 0
    return MockFeed(entries)


def _make_entry(title, summary="", hours_ago=1):
    """Create a mock RSS entry."""
    published = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
    return {
        "title": title,
        "summary": summary,
        "published_parsed": published.timetuple(),
        "link": f"https://example.com/{title.lower().replace(' ', '-')}",
    }


class TestCountKeywordMentions:
    def test_counts_title_mentions(self):
        entries = [
            {"title": "Bitcoin Surges Past 100K", "summary": ""},
            {"title": "Bitcoin ETF Approved", "summary": ""},
            {"title": "Stock Market Rally", "summary": ""},
        ]
        result = NewsScanner._count_keyword_mentions(entries, ["bitcoin"])
        assert len(result["bitcoin"]) == 2

    def test_counts_summary_mentions(self):
        entries = [
            {"title": "Market Update", "summary": "Bitcoin and ethereum rally today"},
            {"title": "Crypto News", "summary": "bitcoin reaches new high"},
        ]
        result = NewsScanner._count_keyword_mentions(entries, ["bitcoin"])
        assert len(result["bitcoin"]) == 2

    def test_case_insensitive(self):
        entries = [
            {"title": "BITCOIN News", "summary": ""},
            {"title": "Bitcoin Update", "summary": ""},
            {"title": "bitcoin rally", "summary": ""},
        ]
        result = NewsScanner._count_keyword_mentions(entries, ["bitcoin"])
        assert len(result["bitcoin"]) == 3

    def test_multiple_keywords(self):
        entries = [
            {"title": "Bitcoin and Inflation Report", "summary": ""},
            {"title": "Fed Inflation Data", "summary": ""},
            {"title": "Crypto Market", "summary": ""},
        ]
        result = NewsScanner._count_keyword_mentions(entries, ["bitcoin", "inflation"])
        assert len(result["bitcoin"]) == 1
        assert len(result["inflation"]) == 2

    def test_empty_entries(self):
        result = NewsScanner._count_keyword_mentions([], ["bitcoin"])
        assert result["bitcoin"] == []

    def test_no_matches(self):
        entries = [{"title": "Weather Update", "summary": "Sunny day"}]
        result = NewsScanner._count_keyword_mentions(entries, ["bitcoin"])
        assert result["bitcoin"] == []


class TestParseFeed:
    def test_parses_recent_entries(self, config):
        entries = [
            _make_entry("Recent Article 1", hours_ago=2),
            _make_entry("Recent Article 2", hours_ago=5),
            _make_entry("Old Article", hours_ago=48),
        ]
        feed = _make_feed(entries)
        scanner = NewsScanner(config, feed_fetcher=lambda url: feed)
        parsed = scanner._parse_feed("https://example.com/rss")
        # Only entries within LOOKBACK_HOURS (24h) should be included
        assert len(parsed) == 2

    def test_empty_feed(self, config):
        feed = _make_feed([])
        scanner = NewsScanner(config, feed_fetcher=lambda url: feed)
        parsed = scanner._parse_feed("https://example.com/rss")
        assert parsed == []


class TestEntriesToTopic:
    def test_creates_topic_raw_data(self):
        entries = [
            {"title": "Bitcoin News 1", "summary": "", "published": datetime.now(timezone.utc), "link": "https://a.com"},
            {"title": "Bitcoin News 2", "summary": "", "published": datetime.now(timezone.utc), "link": "https://b.com"},
        ]
        topic = NewsScanner._entries_to_topic(
            "bitcoin", entries, Niche.FINANCE, Market.US,
        )
        assert isinstance(topic, TopicRawData)
        assert topic.source == TopicSource.NEWS_RSS
        assert topic.raw_metrics["mention_count"] == 2
        assert topic.niche == Niche.FINANCE


class TestNewsScannerIntegration:
    @pytest.mark.asyncio
    async def test_scan_finds_trending_topic(self, config):
        """12 entries mentioning bitcoin across 2 feeds → topic discovered."""
        entries = [_make_entry(f"Bitcoin Article {i}", hours_ago=i) for i in range(12)]
        feed = _make_feed(entries)

        scanner = NewsScanner(config, feed_fetcher=lambda url: feed)
        result = await scanner.scan()
        assert result.success
        assert result.source == TopicSource.NEWS_RSS
        # "bitcoin" appears in all 12 titles, > MIN_MENTIONS (10)
        bitcoin_topics = [t for t in result.topics if "bitcoin" in t.title.lower()]
        assert len(bitcoin_topics) >= 1

    @pytest.mark.asyncio
    async def test_scan_no_trending(self, config):
        """Only 3 mentions — below threshold."""
        entries = [
            _make_entry("Bitcoin News 1", hours_ago=1),
            _make_entry("Bitcoin News 2", hours_ago=2),
            _make_entry("Bitcoin News 3", hours_ago=3),
        ]
        feed = _make_feed(entries)
        scanner = NewsScanner(config, feed_fetcher=lambda url: feed)
        result = await scanner.scan()
        assert result.success
        # 3 mentions < MIN_MENTIONS (10) → no topics
        bitcoin_topics = [t for t in result.topics if "bitcoin" in t.title.lower()]
        assert len(bitcoin_topics) == 0

    @pytest.mark.asyncio
    async def test_scan_feed_error_handled(self, config):
        def bad_feed(url):
            raise Exception("Network timeout")

        scanner = NewsScanner(config, feed_fetcher=bad_feed)
        result = await scanner.scan()
        assert result.success is False
        assert "Network timeout" in result.error

    @pytest.mark.asyncio
    async def test_scan_empty_feeds_config(self):
        config = DiscoveryConfig(niche=Niche.TECH, rss_feeds=[])
        scanner = NewsScanner(config)
        result = await scanner.scan()
        assert result.success
        assert result.count == 0
```
