# TASK_A: Topic Discovery Models + BaseScanner

## Model: sonnet | Dependencies: Phase 1+2 complete

Add `DiscoveryError(OmnicastError)` to `shared/errors.py`. Create `src/omnicast/discovery/` package.

## Interface

### src/omnicast/discovery/models.py

```python
"""Pydantic models for Topic Discovery. All frozen, inherit OmnicastSchema."""

from __future__ import annotations
from datetime import datetime, timezone
from pydantic import Field
from omnicast.models.schemas import OmnicastSchema
from omnicast.models.enums import Niche, Market, TopicSource


class TopicRawData(OmnicastSchema):
    """Raw topic from a source before scoring."""
    title: str
    description: str = ""
    source: TopicSource
    niche: Niche
    market: Market
    source_url: str = ""
    raw_metrics: dict = Field(default_factory=dict)
    # raw_metrics keys by source:
    #   YouTube: views, channel_median, outlier_ratio
    #   Trends: growth_pct, interest_score
    #   Reddit: score, comments, upvote_ratio
    #   Podcast: listen_score
    #   News: mention_count, hours_since_first
    extracted_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class SourceResult(OmnicastSchema):
    """Result from one scanner run."""
    source: TopicSource
    topics: list[TopicRawData] = Field(default_factory=list)
    scan_duration_seconds: float = 0.0
    error: str | None = None
    scanned_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def success(self) -> bool:
        return self.error is None

    @property
    def count(self) -> int:
        return len(self.topics)


class ScoredTopic(OmnicastSchema):
    """Topic after scoring (0-100)."""
    raw: TopicRawData
    trend_momentum: float = Field(ge=0, le=30)
    gap_score: float = Field(ge=0, le=40)
    rpm_potential: float = Field(ge=0, le=20)
    novelty_score: float = Field(ge=0, le=10)
    total_score: float = Field(ge=0, le=100)
    auto_approved: bool = False
    needs_review: bool = False

    @property
    def action(self) -> str:
        if self.total_score >= 70:
            return "approve"
        if self.total_score >= 50:
            return "review"
        return "discard"


class DiscoveryConfig(OmnicastSchema):
    """Per-niche discovery configuration."""
    niche: Niche
    markets: list[Market] = Field(default_factory=list)
    competitor_channel_ids: list[str] = Field(default_factory=list)
    subreddits: list[str] = Field(default_factory=list)
    rss_feeds: list[str] = Field(default_factory=list)
    podcast_keywords: list[str] = Field(default_factory=list)
    trends_keywords: list[str] = Field(default_factory=list)
    rpm_floor: float = 7.0
```

### src/omnicast/discovery/base.py

```python
"""Abstract base scanner. Subclasses implement _scan(), base handles timing + error wrapping."""

from __future__ import annotations
from abc import ABC, abstractmethod
import time
import structlog
from omnicast.discovery.models import SourceResult, TopicRawData, DiscoveryConfig
from omnicast.models.enums import TopicSource

logger = structlog.get_logger()


class BaseScanner(ABC):
    source: TopicSource  # set by subclass

    def __init__(self, config: DiscoveryConfig) -> None:
        self.config = config

    async def scan(self) -> SourceResult:
        """Call _scan(), wrap in SourceResult with timing. On error: SourceResult with error str."""
        start = time.time()
        try:
            topics = await self._scan()
            duration = time.time() - start
            logger.info("Scan complete", source=self.source, niche=self.config.niche,
                        topics_found=len(topics), duration_s=round(duration, 2))
            return SourceResult(source=self.source, topics=topics,
                                scan_duration_seconds=round(duration, 2))
        except Exception as exc:
            duration = time.time() - start
            logger.error("Scan failed", source=self.source, error=str(exc),
                         duration_s=round(duration, 2))
            return SourceResult(source=self.source, error=str(exc),
                                scan_duration_seconds=round(duration, 2))

    @abstractmethod
    async def _scan(self) -> list[TopicRawData]: ...
```

## DO NOT

- No ORM/database models — pure Pydantic only
- No scanner logic — that's TASK_B-E
- No imports FROM discovery in existing modules

## Tests

### tests/unit/test_discovery_models.py

```python
import pytest
from datetime import datetime
from pydantic import ValidationError
from omnicast.discovery.models import TopicRawData, SourceResult, ScoredTopic, DiscoveryConfig
from omnicast.models.enums import Niche, Market, TopicSource


class TestTopicRawData:
    def test_create_minimal(self):
        t = TopicRawData(title="Test", source=TopicSource.GOOGLE_TRENDS, niche=Niche.FINANCE, market=Market.US)
        assert t.title == "Test"
        assert t.description == ""
        assert t.raw_metrics == {}
        assert isinstance(t.extracted_at, datetime)

    def test_create_full(self):
        t = TopicRawData(title="Bitcoin ETF", description="ETFs surge", source=TopicSource.NEWS_RSS,
                         niche=Niche.FINANCE, market=Market.US, source_url="https://x.com/btc",
                         raw_metrics={"mention_count": 15})
        assert t.raw_metrics["mention_count"] == 15

    def test_frozen(self):
        t = TopicRawData(title="X", source=TopicSource.REDDIT, niche=Niche.TECH, market=Market.US)
        with pytest.raises(ValidationError):
            t.title = "Y"

    def test_extracted_at_has_tz(self):
        t = TopicRawData(title="X", source=TopicSource.REDDIT, niche=Niche.TECH, market=Market.US)
        assert t.extracted_at.tzinfo is not None


class TestSourceResult:
    def test_success(self):
        topics = [TopicRawData(title=f"T{i}", source=TopicSource.GOOGLE_TRENDS, niche=Niche.FINANCE, market=Market.US) for i in range(3)]
        r = SourceResult(source=TopicSource.GOOGLE_TRENDS, topics=topics)
        assert r.success and r.count == 3

    def test_error(self):
        r = SourceResult(source=TopicSource.REDDIT, error="Rate limited")
        assert not r.success and r.count == 0

    def test_duration(self):
        r = SourceResult(source=TopicSource.NEWS_RSS, scan_duration_seconds=2.35)
        assert r.scan_duration_seconds == 2.35


class TestScoredTopic:
    def _raw(self):
        return TopicRawData(title="Test", source=TopicSource.GOOGLE_TRENDS, niche=Niche.FINANCE, market=Market.US)

    def test_approve(self):
        s = ScoredTopic(raw=self._raw(), trend_momentum=25, gap_score=30, rpm_potential=15, novelty_score=5, total_score=75, auto_approved=True)
        assert s.action == "approve"

    def test_review(self):
        s = ScoredTopic(raw=self._raw(), trend_momentum=15, gap_score=20, rpm_potential=10, novelty_score=5, total_score=55, needs_review=True)
        assert s.action == "review"

    def test_discard(self):
        s = ScoredTopic(raw=self._raw(), trend_momentum=10, gap_score=10, rpm_potential=5, novelty_score=3, total_score=28)
        assert s.action == "discard"

    def test_bounds_zero(self):
        s = ScoredTopic(raw=self._raw(), trend_momentum=0, gap_score=0, rpm_potential=0, novelty_score=0, total_score=0)
        assert s.total_score == 0

    def test_bounds_max(self):
        s = ScoredTopic(raw=self._raw(), trend_momentum=30, gap_score=40, rpm_potential=20, novelty_score=10, total_score=100)
        assert s.total_score == 100

    def test_trend_over_max_rejected(self):
        with pytest.raises(ValidationError):
            ScoredTopic(raw=self._raw(), trend_momentum=31, gap_score=0, rpm_potential=0, novelty_score=0, total_score=31)

    def test_gap_over_max_rejected(self):
        with pytest.raises(ValidationError):
            ScoredTopic(raw=self._raw(), trend_momentum=0, gap_score=41, rpm_potential=0, novelty_score=0, total_score=41)

    def test_boundary_70(self):
        s = ScoredTopic(raw=self._raw(), trend_momentum=20, gap_score=30, rpm_potential=15, novelty_score=5, total_score=70)
        assert s.action == "approve"

    def test_boundary_50(self):
        s = ScoredTopic(raw=self._raw(), trend_momentum=15, gap_score=20, rpm_potential=10, novelty_score=5, total_score=50)
        assert s.action == "review"

    def test_boundary_49(self):
        s = ScoredTopic(raw=self._raw(), trend_momentum=14, gap_score=20, rpm_potential=10, novelty_score=5, total_score=49)
        assert s.action == "discard"


class TestDiscoveryConfig:
    def test_minimal(self):
        c = DiscoveryConfig(niche=Niche.FINANCE)
        assert c.markets == [] and c.rpm_floor == 7.0

    def test_full(self):
        c = DiscoveryConfig(niche=Niche.MYTHOLOGY, markets=[Market.US, Market.UK],
                            competitor_channel_ids=["UC123", "UC456"], subreddits=["mythology"],
                            rpm_floor=12.0)
        assert len(c.competitor_channel_ids) == 2

    def test_frozen(self):
        c = DiscoveryConfig(niche=Niche.TECH)
        with pytest.raises(ValidationError):
            c.niche = Niche.HEALTH
```

### tests/unit/test_base_scanner.py

```python
import pytest
from omnicast.discovery.base import BaseScanner
from omnicast.discovery.models import DiscoveryConfig, TopicRawData, SourceResult
from omnicast.models.enums import Niche, Market, TopicSource


class MockScanner(BaseScanner):
    source = TopicSource.MANUAL
    def __init__(self, config, topics=None, error=None):
        super().__init__(config)
        self._topics = topics or []
        self._error = error
    async def _scan(self):
        if self._error: raise RuntimeError(self._error)
        return self._topics


@pytest.fixture
def config():
    return DiscoveryConfig(niche=Niche.FINANCE, markets=[Market.US])


@pytest.fixture
def sample_topics():
    return [TopicRawData(title=f"T{i}", source=TopicSource.MANUAL, niche=Niche.FINANCE, market=Market.US) for i in range(3)]


class TestBaseScanner:
    @pytest.mark.asyncio
    async def test_scan_success(self, config, sample_topics):
        result = await MockScanner(config, topics=sample_topics).scan()
        assert isinstance(result, SourceResult) and result.success and result.count == 3

    @pytest.mark.asyncio
    async def test_scan_error_wrapped(self, config):
        result = await MockScanner(config, error="Connection timeout").scan()
        assert not result.success and result.error == "Connection timeout" and result.count == 0

    @pytest.mark.asyncio
    async def test_records_duration(self, config):
        result = await MockScanner(config, topics=[]).scan()
        assert result.scan_duration_seconds >= 0

    @pytest.mark.asyncio
    async def test_sets_source(self, config):
        result = await MockScanner(config, topics=[]).scan()
        assert result.source == TopicSource.MANUAL

    def test_cannot_instantiate_abstract(self, config):
        with pytest.raises(TypeError):
            BaseScanner(config)

    def test_config_stored(self, config):
        assert MockScanner(config).config.niche == Niche.FINANCE
```
