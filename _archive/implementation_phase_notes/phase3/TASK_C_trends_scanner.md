# TASK_C: Google Trends Scanner

## Model: sonnet
## Estimated time: 30 minutes
## Dependencies: TASK_A

## Overview

Scan Google Trends for rising queries using pytrends. Detect keywords with
growth > 100% in 7 days across 6 markets (US, UK, AU, CA, JP, KR).

## Files

| File | Lines | Description |
|------|------:|-------------|
| `src/omnicast/discovery/trends_scanner.py` | ~150 | TrendsScanner |
| `tests/unit/test_trends_scanner.py` | ~180 | Pre-written tests |

## Context Files

- `src/omnicast/discovery/base.py` — BaseScanner
- `src/omnicast/discovery/models.py` — TopicRawData, DiscoveryConfig
- `src/omnicast/models/enums.py` — TopicSource.GOOGLE_TRENDS, Market

## Interface Definition

### src/omnicast/discovery/trends_scanner.py

```python
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
        ...

    def _fetch_rising_queries(
        self, keyword: str, geo: str,
    ) -> list[dict]:
        """Synchronous pytrends call (run in thread).

        Build payload → related_queries → return list of
        {"query": str, "value": int} from "rising" table.
        Return empty list on error.
        """
        ...

    @staticmethod
    def _deduplicate(topics: list[TopicRawData]) -> list[TopicRawData]:
        """Remove duplicates by title (case-insensitive, first wins)."""
        ...
```

## DO NOT

- Do NOT use any unofficial Google API — pytrends only
- Do NOT cache results in Redis — that's orchestrator's concern
- Do NOT add rate limiting to pytrends — BaseScanner.scan() wraps errors
- Do NOT fetch interest_over_time — only related_queries "rising"

## Tests

### tests/unit/test_trends_scanner.py

```python
"""Tests for Google Trends Scanner."""

import pytest
from unittest.mock import MagicMock, patch
import pandas as pd

from omnicast.discovery.trends_scanner import (
    TrendsScanner,
    MARKET_GEO,
    RISING_THRESHOLD,
)
from omnicast.discovery.models import DiscoveryConfig, TopicRawData
from omnicast.models.enums import Niche, Market, TopicSource


@pytest.fixture
def config():
    return DiscoveryConfig(
        niche=Niche.FINANCE,
        markets=[Market.US],
        trends_keywords=["bitcoin", "investing"],
    )


@pytest.fixture
def mock_pytrends():
    return MagicMock()


class TestFetchRisingQueries:
    def test_returns_rising_queries(self, config, mock_pytrends):
        rising_df = pd.DataFrame({
            "query": ["bitcoin etf", "crypto tax"],
            "value": [500, 200],
        })
        mock_pytrends.related_queries.return_value = {
            "bitcoin": {"rising": rising_df}
        }
        scanner = TrendsScanner(config, pytrends_client=mock_pytrends)
        results = scanner._fetch_rising_queries("bitcoin", "US")
        assert len(results) == 2
        assert results[0]["query"] == "bitcoin etf"
        assert results[0]["value"] == 500

    def test_filters_below_threshold(self, config, mock_pytrends):
        rising_df = pd.DataFrame({
            "query": ["high growth", "low growth"],
            "value": [250, 50],
        })
        mock_pytrends.related_queries.return_value = {
            "bitcoin": {"rising": rising_df}
        }
        scanner = TrendsScanner(config, pytrends_client=mock_pytrends)
        results = scanner._fetch_rising_queries("bitcoin", "US")
        # Only "high growth" passes RISING_THRESHOLD (100)
        assert len(results) == 1
        assert results[0]["query"] == "high growth"

    def test_empty_when_no_rising(self, config, mock_pytrends):
        mock_pytrends.related_queries.return_value = {
            "bitcoin": {"rising": None}
        }
        scanner = TrendsScanner(config, pytrends_client=mock_pytrends)
        results = scanner._fetch_rising_queries("bitcoin", "US")
        assert results == []

    def test_empty_on_error(self, config, mock_pytrends):
        mock_pytrends.build_payload.side_effect = Exception("Rate limited")
        scanner = TrendsScanner(config, pytrends_client=mock_pytrends)
        results = scanner._fetch_rising_queries("bitcoin", "US")
        assert results == []


class TestDeduplicate:
    def test_dedup_case_insensitive(self):
        topics = [
            TopicRawData(
                title="Bitcoin ETF", source=TopicSource.GOOGLE_TRENDS,
                niche=Niche.FINANCE, market=Market.US,
            ),
            TopicRawData(
                title="bitcoin etf", source=TopicSource.GOOGLE_TRENDS,
                niche=Niche.FINANCE, market=Market.UK,
            ),
        ]
        result = TrendsScanner._deduplicate(topics)
        assert len(result) == 1
        assert result[0].title == "Bitcoin ETF"  # first wins

    def test_no_dedup_needed(self):
        topics = [
            TopicRawData(
                title="Topic A", source=TopicSource.GOOGLE_TRENDS,
                niche=Niche.FINANCE, market=Market.US,
            ),
            TopicRawData(
                title="Topic B", source=TopicSource.GOOGLE_TRENDS,
                niche=Niche.FINANCE, market=Market.US,
            ),
        ]
        result = TrendsScanner._deduplicate(topics)
        assert len(result) == 2

    def test_empty_list(self):
        assert TrendsScanner._deduplicate([]) == []


class TestTrendsScannerIntegration:
    @pytest.mark.asyncio
    async def test_scan_success(self, config, mock_pytrends):
        rising_df = pd.DataFrame({
            "query": ["bitcoin etf approval", "crypto regulation"],
            "value": [300, 150],
        })
        mock_pytrends.related_queries.return_value = {
            "bitcoin": {"rising": rising_df},
        }
        scanner = TrendsScanner(config, pytrends_client=mock_pytrends)
        result = await scanner.scan()
        assert result.success
        assert result.source == TopicSource.GOOGLE_TRENDS
        # At least some topics found
        assert result.count >= 1

    @pytest.mark.asyncio
    async def test_scan_all_keywords(self, config, mock_pytrends):
        """Both keywords should be scanned."""
        call_keywords = []

        def track_payload(kw_list, **kwargs):
            call_keywords.extend(kw_list)

        mock_pytrends.build_payload = track_payload
        mock_pytrends.related_queries.return_value = {
            "bitcoin": {"rising": None},
            "investing": {"rising": None},
        }
        scanner = TrendsScanner(config, pytrends_client=mock_pytrends)
        await scanner.scan()
        assert "bitcoin" in call_keywords or "investing" in call_keywords

    @pytest.mark.asyncio
    async def test_scan_error_handled(self, config, mock_pytrends):
        mock_pytrends.build_payload.side_effect = Exception("429 Too Many Requests")
        scanner = TrendsScanner(config, pytrends_client=mock_pytrends)
        result = await scanner.scan()
        # BaseScanner wraps errors — should not crash
        # Either returns empty success or error result
        assert isinstance(result.scan_duration_seconds, float)


class TestMarketGeo:
    def test_all_markets_mapped(self):
        for market in Market:
            assert market in MARKET_GEO, f"Missing geo mapping for {market}"

    def test_geo_codes_correct(self):
        assert MARKET_GEO[Market.US] == "US"
        assert MARKET_GEO[Market.UK] == "GB"
        assert MARKET_GEO[Market.JP] == "JP"
```
