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
from omnicast.models.enums import TopicSource, Market

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
        all_entries = []
        feeds = self.config.rss_feeds if self.config.rss_feeds else []
        keywords = self.config.trends_keywords if self.config.trends_keywords else []
        market = self.config.markets[0] if self.config.markets else Market.US
        feeds_scanned = 0
        feeds_failed = 0

        for feed_url in feeds:
            try:
                entries = await asyncio.to_thread(
                    self._parse_feed, feed_url
                )
                all_entries.extend(entries)
                feeds_scanned += 1

            except Exception as exc:
                feeds_failed += 1
                logger.warning(
                    "Failed to parse RSS feed",
                    feed_url=feed_url,
                    error=str(exc),
                )
                continue

        # If all feeds failed, raise an exception so BaseScanner wraps it in error result
        if feeds_failed > 0 and feeds_scanned == 0:
            raise RuntimeError(f"All {feeds_failed} feeds failed to parse")

        # Count keyword mentions
        keyword_matches = self._count_keyword_mentions(all_entries, keywords)

        # Convert to topics
        topics = []
        for keyword, matching_entries in keyword_matches.items():
            if len(matching_entries) >= MIN_MENTIONS:
                topic = self._entries_to_topic(
                    keyword, matching_entries, self.config.niche, market
                )
                topics.append(topic)

        return topics

    def _parse_feed(self, feed_url: str) -> list[dict]:
        """Parse one RSS feed, return entries within lookback window.

        Return list of {"title": str, "summary": str, "published": datetime, "link": str}.
        Skip entries without parseable published date.
        """
        feed = self._fetch_feed(feed_url)
        cutoff = datetime.now(timezone.utc) - timedelta(hours=LOOKBACK_HOURS)

        entries = []
        for entry in feed.entries:
            try:
                if hasattr(entry, "published_parsed") and entry.published_parsed:
                    # Convert time tuple to UTC datetime
                    import calendar
                    timestamp = calendar.timegm(entry.published_parsed)
                    published = datetime.fromtimestamp(timestamp, tz=timezone.utc)

                    if published >= cutoff:
                        entries.append({
                            "title": entry.get("title", ""),
                            "summary": entry.get("summary", ""),
                            "published": published,
                            "link": entry.get("link", ""),
                        })
            except Exception:
                continue

        return entries

    @staticmethod
    def _count_keyword_mentions(
        entries: list[dict],
        keywords: list[str],
    ) -> dict[str, list[dict]]:
        """Count how many entries mention each keyword (case-insensitive).

        Check keyword presence in title + summary.
        Return {keyword: [matching_entries]}.
        """
        keyword_matches = {kw: [] for kw in keywords}

        for entry in entries:
            text = (entry["title"] + " " + entry["summary"]).lower()

            for keyword in keywords:
                if keyword.lower() in text:
                    keyword_matches[keyword].append(entry)

        return keyword_matches

    @staticmethod
    def _entries_to_topic(
        keyword: str,
        matching_entries: list[dict],
        niche,
        market,
    ) -> TopicRawData:
        """Convert keyword + matching entries to TopicRawData."""
        if not matching_entries:
            raise ValueError("No entries provided")

        # Calculate hours since first mention
        first_published = min(e["published"] for e in matching_entries)
        hours_since_first = (datetime.now(timezone.utc) - first_published).total_seconds() / 3600

        # Collect unique feed sources
        feed_sources = list(set(e["link"] for e in matching_entries))

        return TopicRawData(
            title=keyword.title(),
            description=f"Breaking trend: {len(matching_entries)} mentions in {hours_since_first:.1f}h",
            source=TopicSource.NEWS_RSS,
            niche=niche,
            market=market,
            source_url=matching_entries[0]["link"],
            raw_metrics={
                "mention_count": len(matching_entries),
                "hours_since_first": round(hours_since_first, 1),
                "feed_sources": feed_sources,
            },
        )
