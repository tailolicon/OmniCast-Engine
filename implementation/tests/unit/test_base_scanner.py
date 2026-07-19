"""Tests for BaseScanner abstract class."""

import pytest

from omnicast.discovery.base import BaseScanner
from omnicast.discovery.models import DiscoveryConfig, TopicRawData, SourceResult
from omnicast.models.enums import Niche, Market, TopicSource


class MockScanner(BaseScanner):
    """Concrete scanner for testing."""
    source = TopicSource.MANUAL

    def __init__(self, config, topics=None, error=None):
        super().__init__(config)
        self._topics = topics or []
        self._error = error

    async def _scan(self) -> list[TopicRawData]:
        if self._error:
            raise RuntimeError(self._error)
        return self._topics


@pytest.fixture
def config():
    return DiscoveryConfig(
        niche=Niche.FINANCE,
        markets=[Market.US],
    )


@pytest.fixture
def sample_topics():
    return [
        TopicRawData(
            title=f"Topic {i}",
            source=TopicSource.MANUAL,
            niche=Niche.FINANCE,
            market=Market.US,
        )
        for i in range(3)
    ]


class TestBaseScanner:
    @pytest.mark.asyncio
    async def test_scan_success(self, config, sample_topics):
        scanner = MockScanner(config, topics=sample_topics)
        result = await scanner.scan()
        assert isinstance(result, SourceResult)
        assert result.success is True
        assert result.count == 3
        assert result.scan_duration_seconds >= 0

    @pytest.mark.asyncio
    async def test_scan_error_wrapped(self, config):
        scanner = MockScanner(config, error="Connection timeout")
        result = await scanner.scan()
        assert result.success is False
        assert result.error == "Connection timeout"
        assert result.count == 0

    @pytest.mark.asyncio
    async def test_scan_records_duration(self, config):
        scanner = MockScanner(config, topics=[])
        result = await scanner.scan()
        assert result.scan_duration_seconds >= 0

    @pytest.mark.asyncio
    async def test_scan_sets_source(self, config):
        scanner = MockScanner(config, topics=[])
        result = await scanner.scan()
        assert result.source == TopicSource.MANUAL

    def test_cannot_instantiate_abstract(self, config):
        with pytest.raises(TypeError):
            BaseScanner(config)

    def test_config_stored(self, config):
        scanner = MockScanner(config)
        assert scanner.config.niche == Niche.FINANCE
