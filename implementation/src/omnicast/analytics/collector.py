"""Channel analytics collector — crawl real metrics, persist, score health.

Glue between AnalyticsCrawler (YouTube Analytics API), the vault time series
(channel_metrics_daily) and HealthScorer. One call per channel per day is
enough (APScheduler / Telegram / API can all call collect_and_store).

Degrades gracefully: no OAuth token or missing analytics scopes -> returns a
summary dict with linked=False + hint instead of raising, so the Channels tab
can show "connect analytics" instead of an error.
"""

from __future__ import annotations

from datetime import date

import structlog

from omnicast.analytics.crawler import AnalyticsCrawler
from omnicast.analytics.health import HealthScorer, TrendAnalyzer
from omnicast.analytics.models import ChannelMetrics
from omnicast.shared.errors import AnalyticsError
from omnicast.upload.oauth import ANALYTICS_SCOPES, OAuth2Manager

logger = structlog.get_logger()


def _metrics_to_rows(metrics: list[ChannelMetrics]) -> list[dict]:
    return [{
        "date": m.date.isoformat(),
        "views": m.views,
        "watch_time_hours": m.watch_time_hours,
        "avd_seconds": m.avd_seconds,
        "avd_percent": m.avd_percent,
        "subscriber_change": m.subscriber_change,
        "impressions": m.impressions,
        "ctr": m.ctr,
        "revenue": m.revenue,
        "rpm": m.rpm,
        "traffic_sources": m.top_traffic_sources,
    } for m in metrics]


def _rows_to_metrics(channel_id: str, rows: list[dict]) -> list[ChannelMetrics]:
    return [ChannelMetrics(
        channel_id=channel_id,
        date=date.fromisoformat(str(r["date"])),
        impressions=int(r.get("impressions", 0)),
        ctr=float(r.get("ctr", 0.0)),
        views=int(r.get("views", 0)),
        avd_seconds=float(r.get("avd_seconds", 0.0)),
        avd_percent=float(r.get("avd_percent", 0.0)),
        watch_time_hours=float(r.get("watch_time_hours", 0.0)),
        subscriber_change=int(r.get("subscriber_change", 0)),
        revenue=float(r.get("revenue", 0.0)),
        rpm=float(r.get("rpm", 0.0)),
        top_traffic_sources=r.get("traffic_sources") or {},
    ) for r in rows]


async def collect_and_store(channel_id: str, oauth: OAuth2Manager,
                            date_range: int = 28,
                            vault_db_path=None) -> dict:
    """Pull the last N days from the Analytics API, upsert into vault, and
    return a health summary dict for the API/UI."""
    from omnicast.vault import db as vault_db

    if not oauth.has_token(channel_id):
        return {"channel_id": channel_id, "linked": False,
                "hint": f"No OAuth token. Run scripts/youtube_authorize.py "
                        f"--channel {channel_id} --analytics"}
    if not set(oauth.stored_scopes(channel_id)).intersection(ANALYTICS_SCOPES):
        return {"channel_id": channel_id, "linked": False,
                "hint": f"Token lacks analytics scopes. Re-run "
                        f"scripts/youtube_authorize.py --channel {channel_id} "
                        f"--analytics to re-consent."}

    crawler = AnalyticsCrawler(oauth_manager=oauth)
    try:
        metrics = await crawler.collect_channel_metrics(channel_id, date_range)
    except AnalyticsError as exc:
        return {"channel_id": channel_id, "linked": False, "hint": str(exc)}

    written = vault_db.upsert_channel_metrics_daily(
        channel_id, _metrics_to_rows(metrics), vault_db_path)
    logger.info("Analytics stored", channel_id=channel_id, rows=written)
    return summarize(channel_id, vault_db_path=vault_db_path)


def summarize(channel_id: str, days: int = 28, vault_db_path=None) -> dict:
    """Health summary from the vault time series (no API call)."""
    from omnicast.vault import db as vault_db

    rows = vault_db.list_channel_metrics_daily(channel_id, days, vault_db_path)
    if not rows:
        return {"channel_id": channel_id, "linked": True, "days": 0,
                "hint": "No metrics stored yet — run collect_and_store first."}

    metrics = _rows_to_metrics(channel_id, rows)
    score_report = HealthScorer().score(metrics)
    report = TrendAnalyzer().analyze(metrics).model_copy(
        update={"health_score": score_report.health_score})

    last7 = metrics[-7:]
    return {
        "channel_id": channel_id,
        "linked": True,
        "days": len(metrics),
        "health_score": round(report.health_score, 1),
        "severity": report.severity.value,
        "views_7d": sum(m.views for m in last7),
        "watch_time_hours_7d": round(sum(m.watch_time_hours for m in last7), 1),
        "subscriber_change_7d": sum(m.subscriber_change for m in last7),
        "revenue_7d": round(sum(m.revenue for m in last7), 2),
        "avd_percent_avg": round(
            sum(m.avd_percent for m in last7) / max(len(last7), 1), 1),
        "ctr_available": any(m.ctr > 0 for m in metrics),
        "revenue_available": any(m.revenue > 0 for m in metrics),
        "trend_7d": report.trend_7d,
        "trend_30d": report.trend_30d,
        "anomalies": report.anomalies,
    }
