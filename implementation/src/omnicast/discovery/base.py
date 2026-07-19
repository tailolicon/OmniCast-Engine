"""Abstract base class for topic source scanners."""

from __future__ import annotations

from abc import ABC, abstractmethod
import time

import structlog

from omnicast.discovery.models import SourceResult, TopicRawData, DiscoveryConfig
from omnicast.models.enums import TopicSource

logger = structlog.get_logger()


class BaseScanner(ABC):
    """Abstract scanner. All 5 sources inherit this.

    Subclasses implement _scan(). Base handles timing + error wrapping.
    """

    source: TopicSource  # Must be set by subclass

    def __init__(self, config: DiscoveryConfig) -> None:
        self.config = config

    async def scan(self) -> SourceResult:
        """Run scan with timing and error handling.

        Calls _scan() → wraps result in SourceResult.
        On exception: returns SourceResult with error message, empty topics.
        Always logs scan duration.
        """
        start = time.time()
        try:
            topics = await self._scan()
            duration = time.time() - start
            logger.info(
                "Scan complete",
                source=self.source,
                niche=self.config.niche,
                topics_found=len(topics),
                duration_s=round(duration, 2),
            )
            return SourceResult(
                source=self.source,
                topics=topics,
                scan_duration_seconds=round(duration, 2),
            )
        except Exception as exc:
            duration = time.time() - start
            logger.error(
                "Scan failed",
                source=self.source,
                niche=self.config.niche,
                error=str(exc),
                duration_s=round(duration, 2),
            )
            return SourceResult(
                source=self.source,
                error=str(exc),
                scan_duration_seconds=round(duration, 2),
            )

    @abstractmethod
    async def _scan(self) -> list[TopicRawData]:
        """Implement source-specific scanning logic.

        Return list of raw topics. Raise on failure (base wraps in SourceResult).
        """
        ...
