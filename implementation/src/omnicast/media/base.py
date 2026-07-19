"""Abstract base for all media modules. Subclasses implement _process()."""

from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Any
import time
import structlog
from omnicast.config.settings import get_settings

logger = structlog.get_logger()


class BaseMediaModule(ABC):
    name: str = "base"

    def __init__(self) -> None:
        self.settings = get_settings()

    @property
    def is_dry_run(self) -> bool:
        return self.settings.is_dry_run

    async def process(self, request: Any) -> Any:
        """Call _process() with timing + error logging. Dry-run returns _dry_run_result()."""
        start = time.time()
        try:
            if self.is_dry_run:
                result = self._dry_run_result(request)
                logger.info("Dry-run complete", module=self.name,
                            duration_s=round(time.time() - start, 2))
                return result
            result = await self._process(request)
            logger.info("Process complete", module=self.name,
                        duration_s=round(time.time() - start, 2))
            return result
        except Exception as exc:
            logger.error("Process failed", module=self.name, error=str(exc),
                         duration_s=round(time.time() - start, 2))
            raise

    @abstractmethod
    async def _process(self, request: Any) -> Any: ...

    @abstractmethod
    def _dry_run_result(self, request: Any) -> Any: ...
