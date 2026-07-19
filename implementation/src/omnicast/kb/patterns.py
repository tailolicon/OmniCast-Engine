"""Pattern storage with decay for engagement patterns."""

from __future__ import annotations

from datetime import datetime, timezone

import structlog

from omnicast.kb.client import KBClient
from omnicast.models.script import EngagementPattern
from omnicast.models.enums import Niche

logger = structlog.get_logger()


class PatternStore:
    """Store and retrieve engagement patterns with automatic decay."""

    def __init__(self, kb: KBClient) -> None:
        self._kb = kb

    async def store_pattern(self, pattern: EngagementPattern) -> None:
        """Store pattern in KB. Raises AgentError on failure."""
        metadata = {
            "niche": pattern.niche.value,
            "market": pattern.market.value,
            "confidence": pattern.confidence,
            "sample_size": pattern.sample_size,
            "decay_date": pattern.decay_date.isoformat(),
            "pattern_id": pattern.pattern_id,
            "source": pattern.source,
        }
        await self._kb.add_document(
            collection="patterns",
            doc_id=pattern.pattern_id,
            text=pattern.finding,
            metadata=metadata,
        )
        logger.info("Pattern stored", pattern_id=pattern.pattern_id)

    async def get_patterns_for_niche(
        self,
        niche: Niche,
        limit: int = 10,
    ) -> list[EngagementPattern]:
        """Get active (non-expired) patterns for a niche, sorted by confidence."""
        results = await self._kb.query(
            collection="patterns",
            query_text=niche.value,
            n_results=limit * 2,  # Fetch more to filter expired
            where={"niche": niche.value},
        )

        patterns = []
        now = datetime.now(timezone.utc)

        for result in results:
            try:
                decay_date = datetime.fromisoformat(result["metadata"]["decay_date"])
                if decay_date > now:  # Not expired
                    pattern = EngagementPattern(
                        pattern_id=result["metadata"]["pattern_id"],
                        niche=Niche(result["metadata"]["niche"]),
                        market=result["metadata"]["market"],
                        finding=result["text"],
                        confidence=result["metadata"]["confidence"],
                        sample_size=result["metadata"]["sample_size"],
                        decay_date=decay_date,
                        source=result["metadata"]["source"],
                    )
                    patterns.append(pattern)
            except Exception:
                continue

        # Sort by confidence descending
        patterns.sort(key=lambda p: p.confidence, reverse=True)
        return patterns[:limit]

    async def get_patterns_for_brief(
        self,
        brief_text: str,
        niche: Niche,
        limit: int = 5,
    ) -> list[EngagementPattern]:
        """Semantic search: find patterns relevant to a specific brief."""
        results = await self._kb.query(
            collection="patterns",
            query_text=brief_text,
            n_results=limit * 2,
            where={"niche": niche.value},
        )

        patterns = []
        now = datetime.now(timezone.utc)

        for result in results:
            try:
                decay_date = datetime.fromisoformat(result["metadata"]["decay_date"])
                if decay_date > now:
                    pattern = EngagementPattern(
                        pattern_id=result["metadata"]["pattern_id"],
                        niche=Niche(result["metadata"]["niche"]),
                        market=result["metadata"]["market"],
                        finding=result["text"],
                        confidence=result["metadata"]["confidence"],
                        sample_size=result["metadata"]["sample_size"],
                        decay_date=decay_date,
                        source=result["metadata"]["source"],
                    )
                    patterns.append(pattern)
            except Exception:
                continue

        return patterns[:limit]

    async def expire_old_patterns(self) -> int:
        """Delete patterns past their decay_date. Returns count deleted."""
        results = await self._kb.query(
            collection="patterns",
            query_text="",
            n_results=1000,  # Large batch
        )

        now = datetime.now(timezone.utc)
        expired_ids = []

        for result in results:
            try:
                decay_date = datetime.fromisoformat(result["metadata"]["decay_date"])
                if decay_date <= now:
                    expired_ids.append(result["id"])
            except Exception:
                continue

        for doc_id in expired_ids:
            await self._kb.delete_document("patterns", doc_id)

        logger.info("Expired patterns deleted", count=len(expired_ids))
        return len(expired_ids)
