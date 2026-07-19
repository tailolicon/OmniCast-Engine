"""Read-only sync data service for Streamlit dashboard.

Sync SQLAlchemy (psycopg2) — NOT async. Required for Streamlit compatibility.
Channel identity: channels/*.json files (always available).
Worker status: Redis heartbeat keys worker:{id}.
Metrics: PostgreSQL via sync engine (graceful empty if DB unreachable).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta, date
from pathlib import Path

import structlog
from sqlalchemy import create_engine, select, func, and_, desc
from sqlalchemy.orm import Session

from omnicast.dashboard.models import (
    SystemKPI, WorkerStatus, DLQItem, PipelineItem,
    ChannelHealth, ComplianceLogEntry, TokenStatusView,
    DashboardFilter, ChannelProfileView, RevenueRow,
    CostSummary, ActivityItem, VelocityStatus,
)
from omnicast.models.orm import (
    ChannelORM, ChannelMetricsORM, VideoORM,
    AlertORM, ExpenseORM, ChannelStrikeORM,
)

logger = structlog.get_logger()

_STATUS_PROGRESS: dict[str, int] = {
    "queued": 5, "researching": 10, "debating": 30,
    "rendering": 60, "uploading": 85, "published": 100, "failed": 0,
}
YOUNG_CHANNEL_DAYS = 90
YOUNG_MAX_WEEKLY = 3
MATURE_MAX_WEEKLY = 7


class DashboardDataService:
    """Sync data service for all dashboard tabs.

    Init once in app.py; Streamlit re-uses instance across reruns via st.session_state.
    All methods fail gracefully — never raise, always return empty default.
    """

    def __init__(
        self,
        db_url: str,
        redis_url: str,
        channels_dir: Path,
        vault_path: Path,
    ) -> None:
        # asyncpg → psycopg2 for sync SQLAlchemy
        self._db_url = db_url.replace("postgresql+asyncpg://", "postgresql+psycopg2://")
        self._redis_url = redis_url
        self._channels_dir = Path(channels_dir)
        self._vault_path = Path(vault_path)
        self._engine = None
        self._redis = None
        self._profiles: dict[str, dict] | None = None  # JSON file cache

    # ── Internals ─────────────────────────────────────────────────────────

    def _get_engine(self):
        if self._engine is None:
            try:
                self._engine = create_engine(
                    self._db_url,
                    pool_pre_ping=True,
                    pool_size=2,
                    max_overflow=3,
                    connect_args={"connect_timeout": 5},
                )
            except Exception as e:
                logger.warning("DB engine init failed", error=str(e))
        return self._engine

    def _sess(self) -> Session | None:
        eng = self._get_engine()
        return Session(eng) if eng else None

    def _get_redis(self):
        if self._redis is None:
            try:
                import redis as redis_lib
                self._redis = redis_lib.from_url(
                    self._redis_url,
                    decode_responses=True,
                    socket_timeout=2,
                    socket_connect_timeout=2,
                )
            except Exception as e:
                logger.warning("Redis init failed", error=str(e))
        return self._redis

    def _load_profiles(self) -> dict[str, dict]:
        """Load and cache all channels/*.json files. Returns {} if dir missing."""
        if self._profiles is not None:
            return self._profiles
        result: dict[str, dict] = {}
        if self._channels_dir.exists():
            for f in self._channels_dir.glob("*.json"):
                try:
                    data = json.loads(f.read_text(encoding="utf-8"))
                    result[f.stem] = data
                except Exception:
                    pass
        self._profiles = result
        return result

    @staticmethod
    def _utc(dt: datetime | None) -> datetime | None:
        if dt is None:
            return None
        return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt

    def _week_start(self) -> date:
        today = date.today()
        return today - timedelta(days=today.weekday())

    # ── Public API ────────────────────────────────────────────────────────

    def get_kpis(self) -> SystemKPI:
        videos_today = active_channels = queue_depth = dlq_count = 0
        system_health = 100.0

        sess = self._sess()
        if sess:
            try:
                with sess:
                    today = date.today()
                    videos_today = sess.scalar(
                        select(func.count(VideoORM.id)).where(
                            VideoORM.status == "published",
                            func.date(VideoORM.published_at) == today,
                        )
                    ) or 0
                    active_channels = sess.scalar(
                        select(func.count(ChannelORM.id)).where(
                            ChannelORM.status.in_(["active", "setup"])
                        )
                    ) or 0
                    queue_depth = sess.scalar(
                        select(func.count(VideoORM.id)).where(
                            VideoORM.status.in_(["queued", "researching", "debating", "rendering", "uploading"])
                        )
                    ) or 0
                    dlq_count = sess.scalar(
                        select(func.count(AlertORM.id)).where(
                            AlertORM.resolved == False,
                            AlertORM.alert_type.like("dlq%"),
                        )
                    ) or 0
            except Exception as e:
                logger.warning("KPI query failed", error=str(e))

        # Fallback: count JSON channel files if DB returned 0
        if active_channels == 0:
            active_channels = len(self._load_profiles())

        # System health from worker heartbeats
        workers = self.get_worker_statuses()
        if workers:
            healthy = sum(1 for w in workers if w.status == "healthy")
            system_health = (healthy / len(workers)) * 100.0

        return SystemKPI(
            videos_today=videos_today,
            active_channels=active_channels,
            system_health=system_health,
            queue_depth=queue_depth,
            dlq_count=dlq_count,
        )

    def get_pipeline_items(self, filter: DashboardFilter | None = None) -> list[PipelineItem]:
        sess = self._sess()
        if not sess:
            return []
        try:
            with sess:
                limit = filter.limit if filter else 50
                in_progress = ["queued", "researching", "debating", "rendering", "uploading", "failed"]

                if filter and filter.status:
                    stmt = (
                        select(VideoORM)
                        .where(VideoORM.status == filter.status)
                        .order_by(desc(VideoORM.updated_at))
                        .limit(limit)
                    )
                else:
                    stmt = (
                        select(VideoORM)
                        .where(VideoORM.status.in_(in_progress))
                        .order_by(desc(VideoORM.updated_at))
                        .limit(limit)
                    )

                videos = sess.execute(stmt).scalars().all()
                return [
                    PipelineItem(
                        video_id=v.youtube_video_id or str(v.id),
                        channel_id=str(v.channel_id),
                        niche=v.niche,
                        status=v.status,
                        title=v.title,
                        cost_usd=float(v.cost_usd or 0),
                        critic_score=v.critic_score,
                        started_at=self._utc(v.created_at),
                        updated_at=self._utc(v.updated_at),
                        progress_pct=float(_STATUS_PROGRESS.get(v.status, 0)),
                    )
                    for v in videos
                ]
        except Exception as e:
            logger.warning("Pipeline items failed", error=str(e))
            return []

    def get_worker_statuses(self) -> list[WorkerStatus]:
        r = self._get_redis()
        if not r:
            return []
        try:
            keys = r.keys("worker:*")
            workers = []
            for key in keys:
                raw = r.get(key)
                if not raw:
                    continue
                data = json.loads(raw)
                ts_raw = data.get("timestamp", "")
                try:
                    ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
                except Exception:
                    ts = datetime.now(timezone.utc)

                age_s = (datetime.now(timezone.utc) - ts).total_seconds()
                if age_s > 120:
                    status = "offline"
                elif data.get("cpu_percent", 0) > 90 or data.get("ram_percent", 0) > 90:
                    status = "degraded"
                else:
                    status = "healthy"

                workers.append(WorkerStatus(
                    worker_id=key.replace("worker:", ""),
                    hostname=data.get("hostname", key),
                    cpu_percent=float(data.get("cpu_percent", 0)),
                    ram_percent=float(data.get("ram_percent", 0)),
                    gpu_temp=data.get("gpu_temp"),
                    last_heartbeat=ts,
                    status=status,
                    current_task=data.get("current_task"),
                ))
            return workers
        except Exception as e:
            logger.warning("Worker status failed", error=str(e))
            return []

    def get_channel_health(self, channel_id: str | None = None) -> list[ChannelHealth]:
        sess = self._sess()
        if not sess:
            return []
        try:
            with sess:
                subq = (
                    select(
                        ChannelMetricsORM.channel_id,
                        func.max(ChannelMetricsORM.recorded_date).label("max_date"),
                    )
                    .group_by(ChannelMetricsORM.channel_id)
                    .subquery()
                )
                stmt = (
                    select(ChannelORM, ChannelMetricsORM)
                    .join(subq, ChannelORM.id == subq.c.channel_id, isouter=True)
                    .join(
                        ChannelMetricsORM,
                        and_(
                            ChannelMetricsORM.channel_id == subq.c.channel_id,
                            ChannelMetricsORM.recorded_date == subq.c.max_date,
                        ),
                        isouter=True,
                    )
                )
                rows = sess.execute(stmt).all()
                results = []
                for ch, m in rows:
                    pub_count = sess.scalar(
                        select(func.count(VideoORM.id)).where(
                            VideoORM.channel_id == ch.id,
                            VideoORM.status == "published",
                        )
                    ) or 0
                    last_pub = sess.scalar(
                        select(func.max(VideoORM.published_at)).where(
                            VideoORM.channel_id == ch.id,
                            VideoORM.status == "published",
                        )
                    )
                    results.append(ChannelHealth(
                        channel_id=str(ch.id),
                        channel_name=ch.name,
                        channel_type=ch.channel_type,
                        health_score=m.health_score if m else 0.0,
                        videos_published=pub_count,
                        last_upload=self._utc(last_pub),
                        ctr_avg=m.ctr if m else None,
                        retention_avg=m.avg_view_percentage if m else None,
                    ))
                return results
        except Exception as e:
            logger.warning("Channel health failed", error=str(e))
            return []

    def get_channel_profiles(self) -> list[ChannelProfileView]:
        """JSON files primary + DB metrics merged by channel name."""
        profiles = self._load_profiles()
        if not profiles:
            return []

        db_metrics: dict[str, dict] = {}
        sess = self._sess()
        if sess:
            try:
                with sess:
                    channels = sess.execute(select(ChannelORM)).scalars().all()
                    for ch in channels:
                        m = sess.execute(
                            select(ChannelMetricsORM)
                            .where(ChannelMetricsORM.channel_id == ch.id)
                            .order_by(desc(ChannelMetricsORM.recorded_date))
                            .limit(1)
                        ).scalar_one_or_none()

                        pub_count = sess.scalar(
                            select(func.count(VideoORM.id)).where(
                                VideoORM.channel_id == ch.id,
                                VideoORM.status == "published",
                            )
                        ) or 0

                        rev = float(sess.scalar(
                            select(func.coalesce(func.sum(VideoORM.revenue_usd), 0))
                            .where(VideoORM.channel_id == ch.id)
                        ) or 0)

                        cost = float(sess.scalar(
                            select(func.coalesce(func.sum(VideoORM.cost_usd), 0))
                            .where(VideoORM.channel_id == ch.id)
                        ) or 0)

                        last_pub = sess.scalar(
                            select(func.max(VideoORM.published_at)).where(
                                VideoORM.channel_id == ch.id,
                                VideoORM.status == "published",
                            )
                        )

                        strikes = sess.scalar(
                            select(func.count(ChannelStrikeORM.id)).where(
                                ChannelStrikeORM.channel_id == ch.id,
                                (ChannelStrikeORM.expires_date.is_(None))
                                | (ChannelStrikeORM.expires_date > date.today()),
                            )
                        ) or 0

                        db_metrics[ch.name.lower().strip()] = {
                            "status": ch.status,
                            "monetized": ch.monetized,
                            "subscriber_count": ch.subscriber_count,
                            "health_score": m.health_score if m else 0.0,
                            "ctr_avg": m.ctr if m else None,
                            "rpm_avg": m.rpm if m else None,
                            "videos_published": pub_count,
                            "revenue_total": rev,
                            "cost_total": cost,
                            "last_upload": self._utc(last_pub),
                            "active_strikes": strikes,
                        }
            except Exception as e:
                logger.warning("Channel profiles DB enrichment failed", error=str(e))

        results = []
        for channel_id, p in profiles.items():
            m = db_metrics.get(p.get("name", "").lower().strip(), {})
            results.append(ChannelProfileView(
                channel_id=channel_id,
                name=p.get("name", channel_id),
                niche=p.get("niche", ""),
                sub_niche=p.get("sub_niche", ""),
                channel_type=p.get("channel_type", "hub"),
                status=m.get("status", "config_only"),
                monetized=m.get("monetized", False),
                subscriber_count=m.get("subscriber_count", 0),
                brand_voice=p.get("brand_voice", ""),
                tone=p.get("tone", ""),
                hook_format=p.get("hook_format", ""),
                voice_persona=p.get("voice_persona", ""),
                brand_color_hex=p.get("brand_color_hex", "#1A1A2E"),
                font_vibe=p.get("font_vibe", "sans_modern"),
                rpm_floor=float(p.get("rpm_floor", 7.0)),
                target_duration_min=int(p.get("target_duration_min", 10)),
                channel_created_at=p.get("channel_created_at"),
                competitor_count=len(p.get("competitor_handles", [])),
                subreddit_count=len(p.get("subreddits", [])),
                health_score=m.get("health_score", 0.0),
                videos_published=m.get("videos_published", 0),
                ctr_avg=m.get("ctr_avg"),
                rpm_avg=m.get("rpm_avg"),
                revenue_total=m.get("revenue_total", 0.0),
                cost_total=m.get("cost_total", 0.0),
                last_upload=m.get("last_upload"),
                active_strikes=m.get("active_strikes", 0),
            ))
        return sorted(results, key=lambda x: x.revenue_total, reverse=True)

    def get_compliance_log(self, filter: DashboardFilter | None = None) -> list[ComplianceLogEntry]:
        sess = self._sess()
        if not sess:
            return []
        try:
            with sess:
                limit = filter.limit if filter else 50
                stmt = (
                    select(AlertORM)
                    .where(AlertORM.source == "compliance")
                    .order_by(desc(AlertORM.created_at))
                    .limit(limit)
                )
                if filter and filter.channel_id:
                    stmt = stmt.where(
                        AlertORM.details["channel_id"].as_string() == filter.channel_id
                    )
                if filter and filter.status == "failed":
                    stmt = stmt.where(AlertORM.resolved == False)
                elif filter and filter.status == "passed":
                    stmt = stmt.where(AlertORM.resolved == True)

                alerts = sess.execute(stmt).scalars().all()
                return [
                    ComplianceLogEntry(
                        video_id=(a.details or {}).get("video_id", str(a.id)),
                        channel_id=(a.details or {}).get("channel_id", ""),
                        checked_at=self._utc(a.created_at),
                        passed=a.resolved,
                        violations=(a.details or {}).get("violations", [a.message]),
                        checks=(a.details or {}).get("checks", {}),
                    )
                    for a in alerts
                ]
        except Exception as e:
            logger.warning("Compliance log failed", error=str(e))
            return []

    def get_token_statuses(self) -> list[TokenStatusView]:
        """Token health from Redis key token:{channel_id} per JSON channel."""
        profiles = self._load_profiles()
        r = self._get_redis()
        results = []
        for channel_id, p in profiles.items():
            token_data: dict = {}
            if r:
                try:
                    raw = r.get(f"token:{channel_id}")
                    if raw:
                        token_data = json.loads(raw)
                except Exception:
                    pass

            expires_at = None
            if token_data.get("expires_at"):
                try:
                    expires_at = datetime.fromisoformat(
                        token_data["expires_at"].replace("Z", "+00:00")
                    )
                except Exception:
                    pass

            last_refresh = None
            if token_data.get("last_refresh"):
                try:
                    last_refresh = datetime.fromisoformat(
                        token_data["last_refresh"].replace("Z", "+00:00")
                    )
                except Exception:
                    pass

            now = datetime.now(timezone.utc)
            if not token_data:
                status = "unknown"
            elif expires_at and expires_at < now:
                status = "expired"
            elif expires_at and (expires_at - now).total_seconds() < 86400 * 7:
                status = "warning"
            else:
                status = "healthy"

            results.append(TokenStatusView(
                channel_id=channel_id,
                channel_name=p.get("name", channel_id),
                status=status,
                expires_at=expires_at,
                last_refresh=last_refresh,
                scopes=token_data.get("scopes", []),
            ))
        return results

    def get_dlq_items(self, limit: int = 50) -> list[DLQItem]:
        sess = self._sess()
        if sess:
            try:
                with sess:
                    alerts = sess.execute(
                        select(AlertORM)
                        .where(AlertORM.resolved == False, AlertORM.alert_type.like("dlq%"))
                        .order_by(desc(AlertORM.created_at))
                        .limit(limit)
                    ).scalars().all()
                    if alerts:
                        return [
                            DLQItem(
                                item_id=str(a.id),
                                queue_name=(a.details or {}).get("queue_name", "unknown"),
                                error_message=a.message[:200],
                                payload_summary=json.dumps(a.details or {})[:300],
                                failed_at=self._utc(a.created_at),
                                retry_count=a.suppressed_count,
                            )
                            for a in alerts
                        ]
            except Exception as e:
                logger.warning("DLQ DB query failed", error=str(e))
        return self._dlq_from_rabbitmq(limit)

    def _dlq_from_rabbitmq(self, limit: int = 50) -> list[DLQItem]:
        """RabbitMQ management API fallback for DLQ counts."""
        try:
            import httpx
            resp = httpx.get(
                "http://localhost:15672/api/queues/%2F",
                auth=("omnicast", "dev_password"),
                timeout=3.0,
            )
            if resp.status_code != 200:
                return []
            items = []
            for q in resp.json():
                if "dlq" in q.get("name", "").lower() and q.get("messages", 0) > 0:
                    items.append(DLQItem(
                        item_id=q["name"],
                        queue_name=q["name"],
                        error_message=f"{q.get('messages', 0)} messages pending in DLQ",
                        payload_summary=json.dumps({"messages": q.get("messages", 0)}),
                        failed_at=datetime.now(timezone.utc),
                        retry_count=0,
                    ))
            return items[:limit]
        except Exception:
            return []

    def get_activity_feed(self, limit: int = 20) -> list[ActivityItem]:
        """Recent events: published, failed videos + unresolved alerts."""
        items: list[ActivityItem] = []
        sess = self._sess()
        if sess:
            try:
                with sess:
                    # Published videos
                    for v in sess.execute(
                        select(VideoORM)
                        .where(VideoORM.status == "published")
                        .order_by(desc(VideoORM.published_at))
                        .limit(10)
                    ).scalars().all():
                        if v.published_at:
                            items.append(ActivityItem(
                                timestamp=self._utc(v.published_at),
                                event_type="published",
                                channel_id=str(v.channel_id),
                                message=f"✅ Published: {v.title}",
                                severity="info",
                            ))

                    # Failed videos
                    for v in sess.execute(
                        select(VideoORM)
                        .where(VideoORM.status == "failed")
                        .order_by(desc(VideoORM.updated_at))
                        .limit(5)
                    ).scalars().all():
                        items.append(ActivityItem(
                            timestamp=self._utc(v.updated_at),
                            event_type="failed",
                            channel_id=str(v.channel_id),
                            message=f"❌ Failed: {v.title}",
                            severity="error",
                        ))

                    # Unresolved alerts
                    for a in sess.execute(
                        select(AlertORM)
                        .where(AlertORM.resolved == False)
                        .order_by(desc(AlertORM.created_at))
                        .limit(10)
                    ).scalars().all():
                        sev = "error" if a.severity in ("critical", "high") else "warning"
                        items.append(ActivityItem(
                            timestamp=self._utc(a.created_at),
                            event_type="alert",
                            message=f"⚠️ {a.alert_type}: {a.message[:100]}",
                            severity=sev,
                        ))
            except Exception as e:
                logger.warning("Activity feed failed", error=str(e))

        items.sort(key=lambda x: x.timestamp, reverse=True)
        return items[:limit]

    def get_revenue_summary(self) -> list[RevenueRow]:
        sess = self._sess()
        if not sess:
            return []
        try:
            with sess:
                rows = sess.execute(
                    select(
                        ChannelORM.id,
                        ChannelORM.name,
                        func.coalesce(func.sum(VideoORM.revenue_usd), 0).label("revenue"),
                        func.coalesce(func.sum(VideoORM.cost_usd), 0).label("cost"),
                        func.count(VideoORM.id).label("count"),
                    )
                    .join(VideoORM, VideoORM.channel_id == ChannelORM.id, isouter=True)
                    .group_by(ChannelORM.id, ChannelORM.name)
                ).all()

                results = []
                for row in rows:
                    revenue = float(row.revenue)
                    cost = float(row.cost)
                    profit = revenue - cost
                    roi_pct = (profit / cost * 100) if cost > 0 else None
                    results.append(RevenueRow(
                        channel_id=str(row.id),
                        channel_name=row.name,
                        revenue_usd=revenue,
                        cost_usd=cost,
                        profit_usd=profit,
                        roi_pct=roi_pct,
                        videos_count=row.count or 0,
                    ))
                return sorted(results, key=lambda x: x.profit_usd, reverse=True)
        except Exception as e:
            logger.warning("Revenue summary failed", error=str(e))
            return []

    def get_cost_summary(self, days: int = 7) -> CostSummary:
        sess = self._sess()
        if not sess:
            return CostSummary(total_usd=0.0, by_category={}, cost_per_video=None, period_days=days)
        try:
            with sess:
                start = date.today() - timedelta(days=days)

                # Expenses by category
                rows = sess.execute(
                    select(
                        ExpenseORM.category,
                        func.sum(ExpenseORM.amount).label("total"),
                    )
                    .where(ExpenseORM.recorded_date >= start)
                    .group_by(ExpenseORM.category)
                ).all()
                by_cat = {r.category: float(r.total) for r in rows}

                # LLM costs from VideoORM.cost_usd
                llm_cost = float(sess.scalar(
                    select(func.coalesce(func.sum(VideoORM.cost_usd), 0))
                    .where(func.date(VideoORM.created_at) >= start)
                ) or 0)
                if llm_cost > 0:
                    by_cat["llm"] = by_cat.get("llm", 0.0) + llm_cost

                total = sum(by_cat.values())

                video_count = sess.scalar(
                    select(func.count(VideoORM.id)).where(
                        func.date(VideoORM.created_at) >= start,
                        VideoORM.status == "published",
                    )
                ) or 0

                return CostSummary(
                    total_usd=total,
                    by_category=by_cat,
                    cost_per_video=total / video_count if video_count > 0 else None,
                    period_days=days,
                )
        except Exception as e:
            logger.warning("Cost summary failed", error=str(e))
            return CostSummary(total_usd=0.0, by_category={}, cost_per_video=None, period_days=days)

    def get_velocity_statuses(self) -> list[VelocityStatus]:
        """ChannelGuard: uploads this week vs limit per channel (from JSON profiles)."""
        profiles = self._load_profiles()
        if not profiles:
            return []

        week_start = self._week_start()
        results = []

        for channel_id, p in profiles.items():
            channel_created_at = p.get("channel_created_at")
            age_days = None
            is_young = True  # safe default

            if channel_created_at:
                try:
                    created = datetime.fromisoformat(channel_created_at).date()
                    age_days = (date.today() - created).days
                    is_young = age_days < YOUNG_CHANNEL_DAYS
                except Exception:
                    pass

            max_weekly = YOUNG_MAX_WEEKLY if is_young else MATURE_MAX_WEEKLY
            uploads_this_week = 0

            sess = self._sess()
            if sess:
                try:
                    with sess:
                        uploads_this_week = sess.scalar(
                            select(func.count(VideoORM.id)).where(
                                VideoORM.status == "published",
                                func.date(VideoORM.published_at) >= week_start,
                            )
                        ) or 0
                except Exception:
                    pass

            remaining = max(0, max_weekly - uploads_this_week)
            results.append(VelocityStatus(
                channel_id=channel_id,
                channel_name=p.get("name", channel_id),
                is_young=is_young,
                age_days=age_days,
                uploads_this_week=uploads_this_week,
                max_weekly=max_weekly,
                remaining=remaining,
                at_limit=remaining == 0,
                rpm_floor=float(p.get("rpm_floor", 7.0)),
            ))

        # At-limit channels first
        return sorted(results, key=lambda x: x.remaining)

    def retry_dlq_item(self, item_id: str) -> bool:
        sess = self._sess()
        if not sess:
            return False
        try:
            with sess:
                alert = sess.get(AlertORM, int(item_id))
                if alert:
                    alert.resolved = True
                    alert.resolved_at = datetime.now(timezone.utc)
                    sess.commit()
                    logger.info("DLQ item retried", item_id=item_id)
                    return True
        except Exception as e:
            logger.warning("DLQ retry failed", item_id=item_id, error=str(e))
        return False

    def discard_dlq_item(self, item_id: str) -> bool:
        return self.retry_dlq_item(item_id)

    def update_dlq_payload(self, item_id: str, new_payload_json: str) -> bool:
        """Overwrite AlertORM.details with edited JSON payload. Returns False if parse fails."""
        try:
            new_details = json.loads(new_payload_json)
        except json.JSONDecodeError as e:
            logger.warning("DLQ payload parse failed", item_id=item_id, error=str(e))
            return False

        sess = self._sess()
        if not sess:
            return False
        try:
            with sess:
                alert = sess.get(AlertORM, int(item_id))
                if alert:
                    alert.details = new_details
                    sess.commit()
                    logger.info("DLQ payload updated", item_id=item_id)
                    return True
        except Exception as e:
            logger.warning("DLQ payload update failed", item_id=item_id, error=str(e))
        return False

    # ── Kill-Switch (Std 2.A) ─────────────────────────────────────────────
    # Redis key `system:pipeline_paused` — workers MUST check this before pulling jobs.
    # Existence of the key ⇒ paused. Value is ISO timestamp of when it was set.
    _PAUSE_KEY = "system:pipeline_paused"

    # Kill-switch SSOT = vault.db `system_state` table (SQLite, always available on
    # this single-machine desktop app). Redis is an OPTIONAL fast-path cache on top —
    # if Redis is down/not configured the kill-switch still works correctly via SQLite.
    _PAUSE_STATE_KEY = "pipeline_paused_since"

    def is_pipeline_paused(self) -> bool:
        """Return True iff the kill-switch is engaged. SQLite-backed, Redis optional."""
        try:
            from omnicast.vault import db as vault_db
            vault_db.init_db(self._vault_path)
            return vault_db.get_system_state(self._PAUSE_STATE_KEY, self._vault_path) is not None
        except Exception as e:
            logger.warning("Pause-state check failed (vault)", error=str(e))
            return False

    def get_pipeline_paused_since(self) -> str | None:
        """ISO timestamp of when pipeline was paused, or None if running."""
        try:
            from omnicast.vault import db as vault_db
            vault_db.init_db(self._vault_path)
            return vault_db.get_system_state(self._PAUSE_STATE_KEY, self._vault_path)
        except Exception as e:
            logger.warning("Pause-since read failed (vault)", error=str(e))
            return None

    def pause_pipeline(self, operator: str = "dashboard") -> bool:
        """Engage kill-switch. Durable write to vault.db; Redis updated best-effort."""
        ts = datetime.now(timezone.utc).isoformat()
        try:
            from omnicast.vault import db as vault_db
            vault_db.init_db(self._vault_path)
            vault_db.set_system_state(self._PAUSE_STATE_KEY, ts, updated_by=operator, path=self._vault_path)
            logger.warning("PIPELINE PAUSED (kill-switch engaged)", operator=operator, since=ts)
        except Exception as e:
            logger.error("Pause failed (vault) — kill-switch NOT engaged", error=str(e))
            return False
        # Best-effort mirror to Redis so other processes with a hot Redis cache see it
        # immediately too. Failure here must NOT fail the pause — vault write already succeeded.
        try:
            r = self._get_redis()
            if r:
                r.set(self._PAUSE_KEY, ts)
        except Exception as e:
            logger.info("Redis mirror for pause skipped (non-fatal)", error=str(e))
        return True

    def resume_pipeline(self, operator: str = "dashboard") -> bool:
        """Disengage kill-switch. Durable write to vault.db; Redis updated best-effort."""
        try:
            from omnicast.vault import db as vault_db
            vault_db.init_db(self._vault_path)
            vault_db.delete_system_state(self._PAUSE_STATE_KEY, self._vault_path)
            logger.warning("PIPELINE RESUMED", operator=operator)
        except Exception as e:
            logger.error("Resume failed (vault)", error=str(e))
            return False
        try:
            r = self._get_redis()
            if r:
                r.delete(self._PAUSE_KEY)
        except Exception as e:
            logger.info("Redis mirror for resume skipped (non-fatal)", error=str(e))
        return True

    # ── Triage / HITL Queue (Std 2.C) ─────────────────────────────────────
    # Reuses AlertORM with alert_type='triage'. details JSON:
    #   {"kind": "channel_name|script|rule_update", "payload": {...}, "submitted_by": "<agent>"}

    def get_triage_items(self, limit: int = 100) -> list[dict]:
        """Return pending (unresolved) triage items. Each dict carries id/kind/title/payload/created_at."""
        sess = self._sess()
        if not sess:
            return []
        try:
            with sess:
                alerts = sess.execute(
                    select(AlertORM)
                    .where(
                        AlertORM.alert_type == "triage",
                        AlertORM.resolved == False,  # noqa: E712
                    )
                    .order_by(desc(AlertORM.created_at))
                    .limit(limit)
                ).scalars().all()
                results = []
                for a in alerts:
                    d = a.details or {}
                    results.append({
                        "item_id":     str(a.id),
                        "kind":        d.get("kind", "unknown"),
                        "title":       a.message,
                        "payload":     d.get("payload", {}),
                        "submitted_by": d.get("submitted_by", "system"),
                        "created_at":  self._utc(a.created_at),
                        "severity":    a.severity,
                    })
                return results
        except Exception as e:
            logger.warning("Triage queue load failed", error=str(e))
            return []

    def _resolve_triage(self, item_id: str, decision: str, operator: str, note: str) -> bool:
        sess = self._sess()
        if not sess:
            return False
        try:
            with sess:
                alert = sess.get(AlertORM, int(item_id))
                if not alert or alert.alert_type != "triage":
                    return False
                merged = dict(alert.details or {})
                merged["decision"]    = decision
                merged["decided_by"]  = operator
                merged["decided_at"]  = datetime.now(timezone.utc).isoformat()
                if note:
                    merged["operator_note"] = note
                alert.details     = merged
                alert.resolved    = True
                alert.resolved_at = datetime.now(timezone.utc)
                sess.commit()
                logger.info("Triage resolved", item_id=item_id, decision=decision, operator=operator)
                return True
        except Exception as e:
            logger.warning("Triage resolve failed", item_id=item_id, error=str(e))
            return False

    def approve_triage(self, item_id: str, operator: str = "dashboard", note: str = "") -> bool:
        return self._resolve_triage(item_id, "approved", operator, note)

    def reject_triage(self, item_id: str, operator: str = "dashboard", note: str = "") -> bool:
        return self._resolve_triage(item_id, "rejected", operator, note)
