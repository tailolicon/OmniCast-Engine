"""Dashboard-specific models for monitoring UI."""

from __future__ import annotations
from datetime import datetime, timezone
from pydantic import Field
from omnicast.models.schemas import OmnicastSchema


class SystemKPI(OmnicastSchema):
    """Top-level KPIs for dashboard home."""
    videos_today: int
    active_channels: int
    system_health: float  # 0-100
    queue_depth: int
    dlq_count: int


class WorkerStatus(OmnicastSchema):
    """Single worker health snapshot."""
    worker_id: str
    hostname: str
    cpu_percent: float
    ram_percent: float
    gpu_temp: float | None
    last_heartbeat: datetime
    status: str  # "healthy" | "degraded" | "offline"
    current_task: str | None


class DLQItem(OmnicastSchema):
    """Dead letter queue item for viewer."""
    item_id: str
    queue_name: str
    error_message: str
    payload_summary: str
    failed_at: datetime
    retry_count: int


class PipelineItem(OmnicastSchema):
    """Single video in production pipeline."""
    video_id: str
    channel_id: str
    niche: str
    status: str
    started_at: datetime
    updated_at: datetime
    progress_pct: float  # 0-100
    # Extended fields
    title: str = ""
    cost_usd: float = 0.0
    critic_score: float | None = None


class ChannelHealth(OmnicastSchema):
    """Channel health summary for dashboard."""
    channel_id: str
    channel_name: str
    channel_type: str
    health_score: float  # 0-100
    videos_published: int
    last_upload: datetime | None
    ctr_avg: float | None
    retention_avg: float | None


class ComplianceLogEntry(OmnicastSchema):
    """Compliance check result for audit trail."""
    video_id: str
    channel_id: str
    checked_at: datetime
    passed: bool
    violations: list[str]
    checks: dict[str, bool]


class TokenStatusView(OmnicastSchema):
    """OAuth token status for dashboard display."""
    channel_id: str
    channel_name: str
    status: str  # "healthy" | "warning" | "expired" | "unknown"
    expires_at: datetime | None
    last_refresh: datetime | None
    scopes: list[str]


class DashboardFilter(OmnicastSchema):
    """Common filter for dashboard queries."""
    model_config = {"frozen": False}
    channel_id: str | None = None
    date_from: datetime | None = None
    date_to: datetime | None = None
    status: str | None = None
    limit: int = 50


# ── New models ────────────────────────────────────────────────────────────────

class ChannelProfileView(OmnicastSchema):
    """JSON channel profile + DB metrics merged. Source of truth for Channels tab."""
    channel_id: str
    name: str
    niche: str
    sub_niche: str
    channel_type: str
    status: str              # from DB or "config_only" if not in DB yet
    monetized: bool = False
    subscriber_count: int = 0
    # Brand identity (from channels/*.json — LLM-generated)
    brand_voice: str = ""
    tone: str = ""
    hook_format: str = ""
    voice_persona: str = ""
    brand_color_hex: str = "#1A1A2E"
    font_vibe: str = "sans_modern"
    rpm_floor: float = 7.0
    target_duration_min: int = 10
    channel_created_at: str | None = None
    competitor_count: int = 0
    subreddit_count: int = 0
    # DB metrics (0/None if channel not yet in DB)
    health_score: float = 0.0
    videos_published: int = 0
    ctr_avg: float | None = None
    rpm_avg: float | None = None
    revenue_total: float = 0.0
    cost_total: float = 0.0
    last_upload: datetime | None = None
    active_strikes: int = 0


class RevenueRow(OmnicastSchema):
    """Per-channel revenue for Revenue tab."""
    channel_id: str
    channel_name: str
    revenue_usd: float
    cost_usd: float
    profit_usd: float
    roi_pct: float | None
    videos_count: int
    rpm_avg: float | None = None


class CostSummary(OmnicastSchema):
    """Cost breakdown by category for Revenue tab."""
    total_usd: float
    by_category: dict[str, float]
    cost_per_video: float | None
    period_days: int


class ActivityItem(OmnicastSchema):
    """Single event for Home tab activity feed."""
    timestamp: datetime
    event_type: str   # "published" | "failed" | "alert" | "dlq"
    channel_id: str | None = None
    message: str
    severity: str = "info"   # "info" | "warning" | "error"


class VelocityStatus(OmnicastSchema):
    """ChannelGuard upload velocity for Schedule tab."""
    channel_id: str
    channel_name: str
    is_young: bool            # < 90 days since channel_created_at
    age_days: int | None = None
    uploads_this_week: int
    max_weekly: int           # 3 if young, 7 if mature
    remaining: int            # max_weekly - uploads_this_week
    at_limit: bool
    rpm_floor: float = 7.0
