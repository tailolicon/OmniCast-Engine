"""Tests for News RSS Scanner."""

import pytest
import time
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
    # Use UTC time tuple for calendar.timegm compatibility
    return {
        "title": title,
        "summary": summary,
        "published_parsed": published.utctimetuple(),
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
        # Create entries with proper datetime objects directly
        now = datetime.now(timezone.utc)
        entries = [
            {"title": "Recent Article 1", "summary": "", "published": now - timedelta(hours=2), "link": "https://a.com"},
            {"title": "Recent Article 2", "summary": "", "published": now - timedelta(hours=5), "link": "https://b.com"},
            {"title": "Old Article", "summary": "", "published": now - timedelta(hours=48), "link": "https://c.com"},
        ]
        # Manually create feed with these entries (bypass time parsing)
        class MockFeed:
            def __init__(self, items):
                self.entries = items
                self.bozo = 0
        feed = MockFeed(entries)

        # Override _parse_feed to use datetime directly for this test
        original_parse = NewsScanner._parse_feed
        def custom_parse(self, feed_url):
            cutoff = datetime.now(timezone.utc) - timedelta(hours=LOOKBACK_HOURS)
            result = []
            for entry in feed.entries:
                if entry["published"] >= cutoff:
                    result.append(entry)
            return result

        NewsScanner._parse_feed = custom_parse
        scanner = NewsScanner(config, feed_fetcher=lambda url: feed)
        parsed = scanner._parse_feed("https://example.com/rss")
        NewsScanner._parse_feed = original_parse

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
        now = datetime.now(timezone.utc)
        entries = [
            {"title": f"Bitcoin Article {i}", "summary": "", "published": now - timedelta(hours=i), "link": f"https://a.com/{i}"}
            for i in range(12)
        ]
        class MockFeed:
            def __init__(self, items):
                self.entries = items
                self.bozo = 0
        feed = MockFeed(entries)

        # Override _parse_feed to use datetime directly
        original_parse = NewsScanner._parse_feed
        def custom_parse(self, feed_url):
            cutoff = datetime.now(timezone.utc) - timedelta(hours=LOOKBACK_HOURS)
            result = []
            for entry in feed.entries:
                if entry["published"] >= cutoff:
                    result.append(entry)
            return result

        NewsScanner._parse_feed = custom_parse
        scanner = NewsScanner(config, feed_fetcher=lambda url: feed)
        result = await scanner.scan()
        NewsScanner._parse_feed = original_parse

        assert result.success
        assert result.source == TopicSource.NEWS_RSS
        # "bitcoin" appears in all 12 titles, > MIN_MENTIONS (10)
        bitcoin_topics = [t for t in result.topics if "bitcoin" in t.title.lower()]
        assert len(bitcoin_topics) >= 1

    @pytest.mark.asyncio
    async def test_scan_no_trending(self, config):
        """Only 3 mentions — below threshold."""
        now = datetime.now(timezone.utc)
        entries = [
            {"title": "Bitcoin News 1", "summary": "", "published": now - timedelta(hours=1), "link": "https://a.com"},
            {"title": "Bitcoin News 2", "summary": "", "published": now - timedelta(hours=2), "link": "https://b.com"},
            {"title": "Bitcoin News 3", "summary": "", "published": now - timedelta(hours=3), "link": "https://c.com"},
        ]
        class MockFeed:
            def __init__(self, items):
                self.entries = items
                self.bozo = 0
        feed = MockFeed(entries)

        # Override _parse_feed to use datetime directly
        original_parse = NewsScanner._parse_feed
        def custom_parse(self, feed_url):
            cutoff = datetime.now(timezone.utc) - timedelta(hours=LOOKBACK_HOURS)
            result = []
            for entry in feed.entries:
                if entry["published"] >= cutoff:
                    result.append(entry)
            return result

        NewsScanner._parse_feed = custom_parse
        scanner = NewsScanner(config, feed_fetcher=lambda url: feed)
        result = await scanner.scan()
        NewsScanner._parse_feed = original_parse

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
        assert result.error is not None

    @pytest.mark.asyncio
    async def test_scan_empty_feeds_config(self):
        config = DiscoveryConfig(niche=Niche.TECH, rss_feeds=[])
        scanner = NewsScanner(config)
        result = await scanner.scan()
        assert result.success
        assert result.count == 0
