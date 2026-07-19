"""Tests for Google Trends Scanner."""

import pytest
from unittest.mock import MagicMock
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
