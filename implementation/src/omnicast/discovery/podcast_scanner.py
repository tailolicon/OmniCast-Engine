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
from omnicast.models.enums import TopicSource, Market

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
        all_topics = []
        keywords = self.config.podcast_keywords if self.config.podcast_keywords else []
        market = self.config.markets[0] if self.config.markets else Market.US
        keywords_scanned = 0
        keywords_failed = 0

        for keyword in keywords:
            try:
                episodes = await self._search_episodes(keyword)

                for ep in episodes:
                    topic = TopicRawData(
                        title=ep["title"],
                        description=f"Episode from {ep['podcast_title']}",
                        source=TopicSource.PODCAST,
                        niche=self.config.niche,
                        market=market,
                        source_url=f"https://podcastindex.org/podcast/{ep['episode_id']}",
                        raw_metrics={
                            "listen_score": ep["listen_score"],
                            "podcast_title": ep["podcast_title"],
                            "episode_id": ep["episode_id"],
                        },
                    )
                    all_topics.append(topic)

                keywords_scanned += 1

            except Exception as exc:
                keywords_failed += 1
                logger.warning(
                    "Failed to search podcast keyword",
                    keyword=keyword,
                    error=str(exc),
                )
                continue

        # If all keywords failed, raise an exception so BaseScanner wraps it in error result
        if keywords_failed > 0 and keywords_scanned == 0:
            raise RuntimeError(f"All {keywords_failed} keywords failed to scan")

        return self._deduplicate(all_topics)

    async def _search_episodes(self, keyword: str) -> list[dict]:
        """Search Podcast Index for episodes matching keyword.

        GET /search/byterm?q={keyword}&max=20
        Return list of {"title", "listen_score", "podcast_title", "episode_id"}.
        Filter by MIN_LISTEN_SCORE.
        """
        url = f"{PODCAST_INDEX_BASE}/search/byterm"
        params = {"q": keyword, "max": 20}
        headers = self._auth_headers()

        response = await self._http.get(url, params=params, headers=headers)
        response.raise_for_status()
        data = response.json()

        episodes = []
        for feed in data.get("feeds", []):
            listen_score = feed.get("itunesInfo", {}).get("listenScore", 0)

            if listen_score >= MIN_LISTEN_SCORE:
                episodes.append({
                    "title": feed.get("description", feed.get("title", "")),
                    "listen_score": listen_score,
                    "podcast_title": feed.get("title", ""),
                    "episode_id": feed.get("id", 0),
                })

        return episodes

    @staticmethod
    def _deduplicate(topics: list[TopicRawData]) -> list[TopicRawData]:
        """Remove duplicates by title (case-insensitive, first wins)."""
        seen = set()
        deduped = []

        for topic in topics:
            key = topic.title.lower()
            if key not in seen:
                seen.add(key)
                deduped.append(topic)

        return deduped
