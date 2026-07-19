"""Vault-backed analytics ingestion for all platforms."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from omnicast.platforms.models import PlatformId, PostStats
from omnicast.vault import db as vault_db
from omnicast.vault.models import PostMetricRecord


class PlatformAnalyticsStore:
    """Stores official or manually ingested post metrics in vault.db."""

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path
        vault_db.init_db(db_path)

    def record(self, stats: PostStats) -> None:
        vault_db.insert_post_metric(
            PostMetricRecord(
                platform_id=stats.platform_id.value if isinstance(stats.platform_id, PlatformId) else str(stats.platform_id),
                account_id=stats.account_id,
                post_id=stats.post_id,
                channel_id=stats.channel_id,
                fetched_at=stats.fetched_at.isoformat(),
                views=stats.views,
                likes=stats.likes,
                comments=stats.comments,
                shares=stats.shares,
                watch_time_seconds=stats.watch_time_seconds,
                revenue=stats.revenue,
                raw=stats.raw,
            ),
            self.db_path,
        )

    def latest(self, platform_id: str, post_id: str) -> PostStats | None:
        metric = vault_db.latest_post_metric(platform_id, post_id, self.db_path)
        if not metric:
            return None
        return PostStats(
            platform_id=PlatformId(metric.platform_id),
            account_id=metric.account_id,
            post_id=metric.post_id,
            channel_id=metric.channel_id,
            fetched_at=datetime.fromisoformat(metric.fetched_at),
            views=metric.views,
            likes=metric.likes,
            comments=metric.comments,
            shares=metric.shares,
            watch_time_seconds=metric.watch_time_seconds,
            revenue=metric.revenue,
            raw=metric.raw,
        )

    def list_channel(self, channel_id: str) -> list[PostStats]:
        return [
            PostStats(
                platform_id=PlatformId(metric.platform_id),
                account_id=metric.account_id,
                post_id=metric.post_id,
                channel_id=metric.channel_id,
                fetched_at=datetime.fromisoformat(metric.fetched_at),
                views=metric.views,
                likes=metric.likes,
                comments=metric.comments,
                shares=metric.shares,
                watch_time_seconds=metric.watch_time_seconds,
                revenue=metric.revenue,
                raw=metric.raw,
            )
            for metric in vault_db.list_post_metrics(channel_id, self.db_path)
        ]
