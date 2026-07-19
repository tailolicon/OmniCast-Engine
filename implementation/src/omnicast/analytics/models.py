"""Analytics models for metrics, health scoring, diagnostics, video intelligence."""

from __future__ import annotations
from datetime import datetime, date, timezone
from enum import Enum
from pydantic import Field
from omnicast.models.schemas import OmnicastSchema


class ChannelMetrics(OmnicastSchema):
    channel_id: str
    date: date
    impressions: int
    ctr: float
    views: int
    avd_seconds: float
    avd_percent: float
    watch_time_hours: float
    subscriber_change: int
    revenue: float
    rpm: float
    top_traffic_sources: dict[str, float]


class VideoMetrics(OmnicastSchema):
    video_id: str
    channel_id: str
    published_at: datetime
    views_24h: int
    views_48h: int
    views_7d: int
    ctr: float
    avd_seconds: float
    avd_percent: float
    retention_curve: list[float]  # % at each 10s interval
    likes: int
    comments: int
    shares: int
    traffic_sources: dict[str, float]


class HealthSeverity(str, Enum):
    HEALTHY = "healthy"
    WARNING = "warning"
    CRITICAL = "critical"
    DEAD = "dead"


class HealthReport(OmnicastSchema):
    channel_id: str
    severity: HealthSeverity
    health_score: float  # 0-100
    trend_7d: float  # % change
    trend_30d: float
    trend_90d: float
    anomalies: list[str]
    generated_at: datetime


class Anomaly(OmnicastSchema):
    metric_name: str
    value: float
    z_score: float
    direction: str  # "up" | "down"
    detected_at: datetime


class ScriptScore(OmnicastSchema):
    hook_strength: float  # 0-10
    structure: float
    uniqueness: float
    readability: float
    estimated_avd: float


class ThumbnailScore(OmnicastSchema):
    contrast: float  # 0-10
    emotion: float
    curiosity_gap: float
    brand_consistency: float
    predicted_ctr: float


class AudioScore(OmnicastSchema):
    voice_naturalness: float  # 0-10
    pacing: float
    music_balance: float
    clipping_detected: bool


class VideoScore(OmnicastSchema):
    visual_variety: float  # 0-10
    transition_quality: float
    text_readability: float
    technical_quality: float


class VideoScorecard(OmnicastSchema):
    video_id: str
    channel_id: str
    script_score: ScriptScore | None = None
    thumbnail_score: ThumbnailScore | None = None
    audio_score: AudioScore | None = None
    video_score: VideoScore | None = None
    performance_tier: str = "pending"  # "top" | "average" | "poor" | "dead" | "pending"


class DiagnosisItem(OmnicastSchema):
    cause: str
    confidence: float  # 0-1
    evidence: list[str]
    suggested_action: str


class Diagnosis(OmnicastSchema):
    channel_id: str
    funnel_bottleneck: str  # "impressions" | "ctr" | "avd" | "engagement"
    items: list[DiagnosisItem]
    generated_at: datetime


class CorrectionAction(OmnicastSchema):
    action_type: str  # "auto" | "manual" | "ab_test"
    target: str
    description: str
    applied: bool = False


class ABTestResult(OmnicastSchema):
    variable: str
    variants: list[str]
    sample_sizes: list[int]
    metrics: dict[str, list[float]]  # metric_name → values per variant
    winner: str | None
    p_value: float | None
    significant: bool


class ROIRecord(OmnicastSchema):
    video_id: str
    channel_id: str
    niche: str
    cost_breakdown: dict[str, float]  # "claude_api", "gpu_hours", "bandwidth"
    total_cost: float
    revenue: float
    roi: float  # (revenue - cost) / cost


class ProductionBlueprint(OmnicastSchema):
    """Output of Video Intelligence — competitor production style analysis."""
    niche: str
    video_format: str  # listicle, documentary, story, explainer, comparison
    art_style: str  # photorealistic, cinematic, anime, minimal, dark_gothic
    pacing_scene_duration: tuple[float, float]
    crossfade_seconds: float
    music_energy: str  # low, medium, high
    text_overlay_freq: float
    b_roll_ratio: float
    hook_type: str  # question, shock_stat, cold_open, preview
    intro_duration: float
    target_duration_minutes: int
    color_mood: str  # warm, cold, neutral, high_contrast
    confidence: float  # 0-1, how much data backs this
    sample_size: int
    generated_at: datetime


class StrategistDecision(OmnicastSchema):
    channel_id: str
    decision_type: str  # "pause" | "boost" | "clone" | "canary" | "reallocate"
    reason: str
    confidence: float
    auto_execute: bool
    created_at: datetime
