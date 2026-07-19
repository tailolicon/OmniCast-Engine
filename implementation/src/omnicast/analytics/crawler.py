"""YouTube Analytics Crawler - pull channel + video metrics from YouTube Analytics API v2.

Real implementation (was a placeholder stub returning []): reports.query via
google-api-python-client against https://youtubeanalytics.googleapis.com/v2.
Requires a per-channel OAuth token that includes ANALYTICS_SCOPES (see
omnicast.upload.oauth) — the upload-only tokens issued before those scopes were
added must be re-authorized.

API limitations (documented, not bugs):
  - Thumbnail impressions / impressions CTR are NOT exposed by the public
    Analytics API (Studio-only). ChannelMetrics.impressions/ctr are 0 and the
    HealthScorer renormalizes its weights around missing components.
  - estimatedRevenue needs the monetary scope AND an actively monetized (YPP)
    channel; on 403/no-data the crawler degrades to revenue=0 instead of failing.
"""

from __future__ import annotations
from datetime import datetime, date, timezone, timedelta
import asyncio
import structlog
from omnicast.analytics.models import ChannelMetrics, VideoMetrics
from omnicast.upload.oauth import ANALYTICS_SCOPES, OAuth2Manager
from omnicast.config.settings import get_settings
from omnicast.shared.errors import AnalyticsError

logger = structlog.get_logger()

_CORE_METRICS = ("views,estimatedMinutesWatched,averageViewDuration,"
                 "averageViewPercentage,subscribersGained,subscribersLost,"
                 "likes,comments,shares")


class AnalyticsCrawler:
    """Pull YouTube Analytics data. Daily channel metrics + per-video metrics."""

    def __init__(self, oauth_manager: OAuth2Manager) -> None:
        self.oauth = oauth_manager

    # ── service plumbing ──────────────────────────────────────────────────────

    async def _service(self, channel_id: str):
        """Build a youtubeAnalytics v2 client with analytics-scoped credentials."""
        stored = set(self.oauth.stored_scopes(channel_id))
        if not stored.intersection(ANALYTICS_SCOPES):
            raise AnalyticsError(
                f"Token for '{channel_id}' lacks analytics scopes. Re-run "
                f"scripts/youtube_authorize.py --channel {channel_id} --analytics"
            )
        scopes = [s for s in ANALYTICS_SCOPES if s in stored]
        creds = await self.oauth.get_credentials(channel_id, scopes=scopes)
        from googleapiclient.discovery import build
        return build("youtubeAnalytics", "v2", credentials=creds,
                     cache_discovery=False)

    @staticmethod
    def _query(service, **params) -> dict:
        return service.reports().query(ids="channel==MINE", **params).execute()

    @staticmethod
    def _rows_by_day(resp: dict) -> dict[str, list]:
        """{'2026-07-01': [row values...]} keyed by the day dimension column."""
        return {row[0]: row[1:] for row in (resp.get("rows") or [])}

    # ── channel metrics ───────────────────────────────────────────────────────

    async def collect_channel_metrics(self, channel_id: str, date_range: int = 7) -> list[ChannelMetrics]:
        """Collect daily channel metrics for the last N days (oldest first)."""
        settings = get_settings()
        if settings.is_dry_run:
            return self._dry_run_channel_metrics(channel_id, date_range)

        service = await self._service(channel_id)
        end = date.today()
        start = end - timedelta(days=date_range)
        common = {"startDate": start.isoformat(), "endDate": end.isoformat(),
                  "dimensions": "day", "sort": "day"}

        core = await asyncio.to_thread(
            self._query, service, metrics=_CORE_METRICS, **common)
        by_day = self._rows_by_day(core)

        # Revenue is a separate, permission-gated query — degrade to zeros.
        rev_by_day: dict[str, list] = {}
        try:
            rev = await asyncio.to_thread(
                self._query, service, metrics="estimatedRevenue,cpm", **common)
            rev_by_day = self._rows_by_day(rev)
        except Exception as exc:
            logger.info("Revenue metrics unavailable (not monetized or no "
                        "monetary scope)", channel_id=channel_id, error=str(exc))

        # Traffic sources for the whole window (share of views per source).
        traffic: dict[str, float] = {}
        try:
            tr = await asyncio.to_thread(
                self._query, service, metrics="views",
                dimensions="insightTrafficSourceType",
                startDate=common["startDate"], endDate=common["endDate"],
                sort="-views")
            rows = tr.get("rows") or []
            total = sum(r[1] for r in rows) or 1
            traffic = {str(r[0]).lower(): round(r[1] / total, 3) for r in rows[:6]}
        except Exception as exc:
            logger.info("Traffic source query failed", channel_id=channel_id,
                        error=str(exc))

        metrics: list[ChannelMetrics] = []
        for day_str in sorted(by_day):
            (views, minutes, avd_sec, avd_pct,
             subs_gained, subs_lost, _likes, _comments, _shares) = by_day[day_str]
            revenue, rpm = 0.0, 0.0
            if day_str in rev_by_day:
                revenue = float(rev_by_day[day_str][0] or 0.0)
                if views:
                    rpm = round(revenue / views * 1000.0, 2)
            metrics.append(ChannelMetrics(
                channel_id=channel_id,
                date=date.fromisoformat(day_str),
                impressions=0,  # not exposed by the public Analytics API
                ctr=0.0,        # ditto — HealthScorer renormalizes
                views=int(views or 0),
                avd_seconds=float(avd_sec or 0.0),
                avd_percent=float(avd_pct or 0.0),
                watch_time_hours=round(float(minutes or 0.0) / 60.0, 2),
                subscriber_change=int(subs_gained or 0) - int(subs_lost or 0),
                revenue=revenue,
                rpm=rpm,
                top_traffic_sources=traffic,
            ))
        logger.info("Channel metrics collected", channel_id=channel_id,
                    days=len(metrics))
        return metrics

    # ── per-video metrics ─────────────────────────────────────────────────────

    async def collect_video_metrics(self, video_id: str, channel_id: str = "") -> VideoMetrics:
        """Collect lifetime + windowed metrics for a single video."""
        settings = get_settings()
        if settings.is_dry_run:
            return self._dry_run_video_metrics(video_id)

        service = await self._service(channel_id or video_id)
        today = date.today()

        def _views_between(d0: date, d1: date) -> int:
            resp = self._query(
                service, metrics="views", filters=f"video=={video_id}",
                startDate=d0.isoformat(), endDate=d1.isoformat())
            rows = resp.get("rows") or []
            return int(rows[0][0]) if rows else 0

        life = await asyncio.to_thread(
            self._query, service,
            metrics="views,averageViewDuration,averageViewPercentage,"
                    "likes,comments,shares",
            filters=f"video=={video_id}",
            startDate="2015-01-01", endDate=today.isoformat())
        row = (life.get("rows") or [[0, 0, 0, 0, 0, 0]])[0]
        views_7d = await asyncio.to_thread(
            _views_between, today - timedelta(days=7), today)
        retention = await self.collect_retention_curve(
            video_id, channel_id=channel_id, _service=service)

        return VideoMetrics(
            video_id=video_id,
            channel_id=channel_id,
            published_at=datetime.now(timezone.utc),
            views_24h=0, views_48h=0,  # day-granular API; windows below 7d are noisy
            views_7d=views_7d,
            ctr=0.0,  # not exposed by the public Analytics API
            avd_seconds=float(row[1] or 0.0),
            avd_percent=float(row[2] or 0.0),
            retention_curve=retention,
            likes=int(row[3] or 0),
            comments=int(row[4] or 0),
            shares=int(row[5] or 0),
            traffic_sources={},
        )

    async def collect_retention_curve(self, video_id: str, channel_id: str = "",
                                      _service=None) -> list[float]:
        """Audience retention: % of viewers still watching per elapsed-time bucket."""
        settings = get_settings()
        if settings.is_dry_run:
            return [100, 85, 72, 60, 55, 50, 48, 45, 42, 40]

        try:
            service = _service or await self._service(channel_id or video_id)
            resp = await asyncio.to_thread(
                self._query, service, metrics="audienceWatchRatio",
                dimensions="elapsedVideoTimeRatio",
                filters=f"video=={video_id}",
                startDate="2015-01-01", endDate=date.today().isoformat())
            return [round(float(r[1]) * 100.0, 1) for r in (resp.get("rows") or [])]
        except Exception as exc:
            logger.info("Retention curve unavailable", video_id=video_id,
                        error=str(exc))
            return []

    async def batch_collect(self, channel_ids: list[str]) -> dict[str, list[ChannelMetrics]]:
        """Collect metrics for multiple channels concurrently (max 5 concurrent)."""
        semaphore = asyncio.Semaphore(5)
        results = {}

        async def collect_with_limit(ch_id: str) -> tuple[str, list[ChannelMetrics]]:
            async with semaphore:
                metrics = await self.collect_channel_metrics(ch_id)
                return ch_id, metrics

        tasks = [collect_with_limit(ch_id) for ch_id in channel_ids]
        completed = await asyncio.gather(*tasks, return_exceptions=True)

        for result in completed:
            if isinstance(result, Exception):
                logger.error("Batch collect failed", error=str(result))
            else:
                ch_id, metrics = result
                results[ch_id] = metrics

        return results

    def _dry_run_channel_metrics(self, channel_id: str, date_range: int) -> list[ChannelMetrics]:
        """Generate mock channel metrics for dry-run mode."""
        metrics = []
        today = date.today()
        for i in range(date_range):
            d = today - timedelta(days=i)
            metrics.append(ChannelMetrics(
                channel_id=channel_id,
                date=d,
                impressions=10000 + i * 100,
                ctr=4.5 + i * 0.1,
                views=450 + i * 10,
                avd_seconds=180.0,
                avd_percent=42.0,
                watch_time_hours=22.5,
                subscriber_change=10,
                revenue=5.0,
                rpm=11.1,
                top_traffic_sources={"browse": 0.5, "search": 0.3},
            ))
        return metrics

    def _dry_run_video_metrics(self, video_id: str) -> VideoMetrics:
        """Generate mock video metrics for dry-run mode."""
        return VideoMetrics(
            video_id=video_id,
            channel_id="ch1",
            published_at=datetime.now(timezone.utc) - timedelta(days=1),
            views_24h=500,
            views_48h=800,
            views_7d=2000,
            ctr=5.0,
            avd_seconds=200.0,
            avd_percent=45.0,
            retention_curve=[100, 85, 72, 60, 55, 50, 48, 45, 42, 40],
            likes=50,
            comments=10,
            shares=5,
            traffic_sources={"browse": 0.5, "search": 0.3},
        )
