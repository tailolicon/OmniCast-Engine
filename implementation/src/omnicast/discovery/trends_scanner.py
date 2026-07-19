"""Google Trends scanner using pytrends.

Finds rising queries with growth > 100% in 7 days.
"""

from __future__ import annotations

import asyncio

import structlog
from pytrends.request import TrendReq

from omnicast.discovery.base import BaseScanner
from omnicast.discovery.models import TopicRawData, DiscoveryConfig
from omnicast.models.enums import TopicSource, Market

logger = structlog.get_logger()

# Market → pytrends geo code
MARKET_GEO: dict[Market, str] = {
    Market.US: "US",
    Market.UK: "GB",
    Market.AU: "AU",
    Market.CA: "CA",
    Market.JP: "JP",
    Market.KR: "KR",
}

RISING_THRESHOLD = 100  # minimum growth % to qualify


class TrendsScanner(BaseScanner):
    """Scan Google Trends for rising queries.

    Algorithm:
    1. For each market in config.markets:
       a. For each keyword in config.trends_keywords:
          - Build payload (timeframe="now 7-d", geo=market_geo)
          - Get related_queries()
          - Filter "rising" queries with value >= RISING_THRESHOLD
    2. Convert to TopicRawData with raw_metrics:
       {"growth_pct": int, "interest_score": int, "keyword": str, "geo": str}
    3. Deduplicate by title (case-insensitive)
    """

    source = TopicSource.GOOGLE_TRENDS

    def __init__(
        self,
        config: DiscoveryConfig,
        pytrends_client: TrendReq | None = None,
    ) -> None:
        """
        pytrends_client: injectable for testing. Default creates TrendReq().
        """
        super().__init__(config)
        self._pytrends = pytrends_client or TrendReq(hl="en-US", tz=360)

    async def _scan(self) -> list[TopicRawData]:
        """Scan trends for all markets × keywords."""
        all_topics = []

        markets = self.config.markets if self.config.markets else [Market.US]
        keywords = self.config.trends_keywords if self.config.trends_keywords else []

        for market in markets:
            geo = MARKET_GEO.get(market, "US")

            for keyword in keywords:
                try:
                    queries = await asyncio.to_thread(
                        self._fetch_rising_queries, keyword, geo
                    )

                    for query_data in queries:
                        topic = TopicRawData(
                            title=query_data["query"],
                            description=f"Rising search query for {keyword}",
                            source=TopicSource.GOOGLE_TRENDS,
                            niche=self.config.niche,
                            market=market,
                            source_url=f"https://trends.google.com/trends/explore?q={query_data['query']}",
                            raw_metrics={
                                "growth_pct": query_data["value"],
                                "interest_score": query_data["value"],
                                "keyword": keyword,
                                "geo": geo,
                            },
                        )
                        all_topics.append(topic)

                except Exception as exc:
                    logger.warning(
                        "Failed to fetch trends for keyword",
                        keyword=keyword,
                        geo=geo,
                        error=str(exc),
                    )
                    continue

        return self._deduplicate(all_topics)

    def _fetch_rising_queries(
        self, keyword: str, geo: str,
    ) -> list[dict]:
        """Synchronous pytrends call (run in thread).

        Build payload → related_queries → return list of
        {"query": str, "value": int} from "rising" table.
        Return empty list on error.
        """
        try:
            self._pytrends.build_payload(
                [keyword],
                timeframe="now 7-d",
                geo=geo,
            )
            related = self._pytrends.related_queries()

            if not related or keyword not in related:
                return []

            rising_df = related[keyword].get("rising")

            if rising_df is None or rising_df.empty:
                return []

            # Filter by threshold
            filtered = rising_df[rising_df["value"] >= RISING_THRESHOLD]

            return [
                {"query": row["query"], "value": int(row["value"])}
                for _, row in filtered.iterrows()
            ]

        except Exception:
            return []

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
