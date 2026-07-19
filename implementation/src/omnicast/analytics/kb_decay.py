"""Knowledge Base Decay Manager - expire stale KB patterns."""

from __future__ import annotations
from datetime import datetime, timezone, timedelta
import structlog

logger = structlog.get_logger()


class KBDecayManager:
    """Expire stale KB patterns. Trend-based = shorter TTL, evergreen = longer."""

    def __init__(self, default_ttl_days: int = 30) -> None:
        self.default_ttl_days = default_ttl_days

    def should_expire(self, pattern_created: datetime, is_trend: bool,
                      last_used: datetime | None = None) -> bool:
        """Check if a pattern should expire based on creation time and type."""
        now = datetime.now(timezone.utc)
        age_days = (now - pattern_created).total_seconds() / 86400

        # Determine TTL based on pattern type
        if is_trend:
            ttl = self.default_ttl_days
        else:
            # Evergreen patterns get 3x default TTL
            ttl = self.default_ttl_days * 3

        # Extend TTL if recently used (+50%)
        if last_used:
            days_since_use = (now - last_used).total_seconds() / 86400
            if days_since_use < 7:  # Used within last 7 days
                ttl = ttl * 1.5

        return age_days > ttl

    def get_expired_patterns(self, patterns: list[dict]) -> list[str]:
        """Get list of expired pattern IDs."""
        expired = []
        for pattern in patterns:
            created = pattern.get("created")
            is_trend = pattern.get("is_trend", False)
            last_used = pattern.get("last_used")

            if created and self.should_expire(created, is_trend, last_used):
                expired.append(pattern["id"])

        return expired

    def get_decay_stats(self, patterns: list[dict]) -> dict[str, int]:
        """Get statistics about pattern decay."""
        total = len(patterns)
        expired = len(self.get_expired_patterns(patterns))
        active = total - expired

        return {
            "total": total,
            "expired": expired,
            "active": active,
        }
