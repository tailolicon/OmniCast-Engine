"""Pydantic v2 schemas. Frozen (immutable). Dùng cho API, queue messages, validation."""

from datetime import datetime, date, timezone

from pydantic import BaseModel, Field

from omnicast.models.enums import (
    ChannelType,
    ChannelStatus,
    VideoStatus,
    TaskPriority,
    Niche,
    Market,
    AlertSeverity,
    AssetType,
    MusicMood,
    TopicSource,
    LearningPath,
)


# === Base ===


class OmnicastSchema(BaseModel):
    """Base schema. Frozen + from_attributes cho ORM compatibility."""

    model_config = {"frozen": True, "from_attributes": True}


# === Channel ===


class ChannelCreate(OmnicastSchema):
    name: str = Field(max_length=100)
    niche: Niche
    sub_niche: str = Field(default="", max_length=30)
    channel_type: ChannelType
    language: str = Field(default="en", max_length=5)
    target_market: Market
    google_cloud_project: str = Field(max_length=100)
    api_key_ref: str = Field(max_length=200)
    adspower_profile: str | None = None
    brand_config_path: str | None = None


class ChannelRead(OmnicastSchema):
    id: int
    name: str
    niche: Niche
    sub_niche: str
    channel_type: ChannelType
    language: str
    target_market: Market
    google_cloud_project: str
    status: ChannelStatus
    monetized: bool
    subscriber_count: int
    created_at: datetime


class ChannelUpdate(OmnicastSchema):
    name: str | None = None
    status: ChannelStatus | None = None
    monetized: bool | None = None
    subscriber_count: int | None = None


# === Channel Metrics ===


class ChannelMetricsCreate(OmnicastSchema):
    channel_id: int
    recorded_date: date
    views: int = 0
    impressions: int = 0
    ctr: float = 0.0
    avg_view_duration: float = 0.0
    avg_view_percentage: float = 0.0
    rpm: float = 0.0
    estimated_revenue: float = 0.0
    subscribers_gained: int = 0
    subscribers_lost: int = 0
    health_score: float = 0.0


class ChannelMetricsRead(ChannelMetricsCreate):
    id: int
    created_at: datetime


# === Video ===


class VideoCreate(OmnicastSchema):
    channel_id: int
    title: str = Field(max_length=100)
    niche: Niche
    target_market: Market
    topic_source: TopicSource
    priority: TaskPriority = TaskPriority.NORMAL
    brief: str | None = None


class VideoRead(OmnicastSchema):
    id: int
    channel_id: int
    youtube_video_id: str | None
    title: str
    niche: Niche
    target_market: Market
    status: VideoStatus
    priority: TaskPriority
    topic_source: TopicSource
    duration_seconds: int | None
    critic_score: float | None
    cost_usd: float
    revenue_usd: float
    roi: float | None
    thumbnail_variant: str | None
    audit_trail: dict | None
    created_at: datetime
    published_at: datetime | None


class VideoUpdate(OmnicastSchema):
    status: VideoStatus | None = None
    youtube_video_id: str | None = None
    title: str | None = None
    duration_seconds: int | None = None
    critic_score: float | None = None
    cost_usd: float | None = None
    revenue_usd: float | None = None
    thumbnail_variant: str | None = None
    audit_trail: dict | None = None
    published_at: datetime | None = None


# === Video Metrics ===


class VideoMetricsCreate(OmnicastSchema):
    video_id: int
    channel_id: int
    views: int = 0
    ctr: float = 0.0
    avg_view_duration: float = 0.0
    avg_view_percentage: float = 0.0
    is_outlier: bool = False
    is_underperformer: bool = False


class VideoMetricsRead(VideoMetricsCreate):
    id: int
    created_at: datetime


# === Topic ===


class TopicCandidate(OmnicastSchema):
    title: str
    niche: Niche
    market: Market
    source: TopicSource
    trend_momentum: float = Field(ge=0, le=30)
    gap_score: float = Field(ge=0, le=40)
    rpm_potential: float = Field(ge=0, le=20)
    novelty_score: float = Field(ge=0, le=10)
    total_score: float = Field(ge=0, le=100)
    source_urls: list[str] = Field(default_factory=list)
    raw_data: dict = Field(default_factory=dict)


# === Asset ===


class AssetCreate(OmnicastSchema):
    path: str
    asset_type: AssetType
    mood: MusicMood | None = None
    bpm: int | None = None
    duration_seconds: float | None = None
    license_info: str | None = None
    tags: list[str] = Field(default_factory=list)
    md5_hash: str


class AssetRead(OmnicastSchema):
    id: int
    path: str
    asset_type: AssetType
    mood: MusicMood | None
    use_count: int
    md5_hash: str
    created_at: datetime


# === Alert ===


class AlertCreate(OmnicastSchema):
    severity: AlertSeverity
    source: str  # e.g. "worker_2", "channel_fin_us"
    alert_type: str  # e.g. "heartbeat_failed", "token_expired"
    message: str
    details: dict = Field(default_factory=dict)


class AlertRead(AlertCreate):
    id: int
    fingerprint: str  # hash(alert_type + source + severity)
    suppressed_count: int
    resolved: bool
    created_at: datetime
    resolved_at: datetime | None


# === Queue Messages ===


class VideoTaskMessage(OmnicastSchema):
    """Message format cho RabbitMQ video production queue."""

    video_id: int
    channel_id: int
    status: VideoStatus
    priority: TaskPriority
    retry_count: int = 0
    max_retries: int = 5
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class AlertMessage(OmnicastSchema):
    """Message format cho RabbitMQ alert queue."""

    severity: AlertSeverity
    source: str
    alert_type: str
    message: str
    details: dict = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# === Learning ===


class LessonCreate(OmnicastSchema):
    agent_name: str
    source: LearningPath
    lesson: str
    evidence: str
    confidence: float = Field(ge=0, le=1)


class LessonRead(OmnicastSchema):
    id: int
    agent_name: str
    source: LearningPath
    lesson: str
    evidence: str
    confidence: float
    applied_count: int
    success_rate: float
    created_at: datetime


# === Expense ===


class ExpenseCreate(OmnicastSchema):
    category: str = Field(max_length=30)
    amount: float
    currency: str = Field(default="USD", max_length=3)
    description: str = Field(max_length=300)
    receipt_path: str | None = None
    tax_deductible: bool = True
    auto_tracked: bool = False
    recorded_date: date


class ExpenseRead(ExpenseCreate):
    id: int
    created_at: datetime


# === Brand Config ===


class BrandConfig(OmnicastSchema):
    """Brand configuration per channel. Loaded from JSON file."""

    channel_id: str
    voice_profile: str = "kokoro_en_us_v1"
    voice_clone: str | None = None
    color_palette: list[str] = Field(
        default_factory=lambda: ["#1A1A2E", "#E94560", "#FFFFFF"]
    )
    font: str = "Montserrat Bold"
    transition_style: str = "zoom_in_0.3s"
    intro_template: str | None = None
    outro_template: str | None = None
    music_bpm_range: tuple[int, int] = (120, 140)
    script_template: str = "standard"
    max_segment_duration: int = 60
    target_duration_min: int = 10
    thumbnail_style: str = "dark_contrast"
    image_gen_mode: str = "sdxl"
    use_video_gen: bool = False