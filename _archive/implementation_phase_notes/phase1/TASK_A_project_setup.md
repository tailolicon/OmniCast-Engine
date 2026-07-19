# TASK A: Project Setup + Shared Models

> **Priority:** PHẢI HOÀN THÀNH TRƯỚC TẤT CẢ TASK KHÁC
> **Output:** pyproject.toml, docker-compose.yml, models/, shared/errors.py
> **Estimated:** 2-3 giờ

## 1. Tạo Project

### pyproject.toml

```toml
[project]
name = "omnicast-engine"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    # Core
    "pydantic>=2.7,<3",
    "pydantic-settings>=2.3,<3",
    "sqlalchemy>=2.0,<3",
    "alembic>=1.13,<2",
    "asyncpg>=0.29,<1",         # PostgreSQL async driver
    # Queue
    "aio-pika>=9.4,<10",        # RabbitMQ async
    # Cache
    "redis>=5.0,<6",            # Redis async
    # Telegram
    "python-telegram-bot>=21,<22",
    # Observability
    "structlog>=24.1,<25",
    # Utils
    "httpx>=0.27,<1",
    "orjson>=3.10,<4",          # Fast JSON
]

[project.optional-dependencies]
dev = [
    "pytest>=8.2,<9",
    "pytest-asyncio>=0.23,<1",
    "pytest-cov>=5,<6",
    "ruff>=0.4,<1",
    "pyright>=1.1,<2",
    "testcontainers[postgres,rabbitmq,redis]>=4,<5",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/omnicast"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]

[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "I", "N", "UP", "B", "SIM", "TCH"]

[tool.pyright]
pythonVersion = "3.12"
typeCheckingMode = "standard"
```

### docker-compose.yml (dev services only)

```yaml
services:
  postgres:
    image: postgres:16-alpine
    ports: ["5432:5432"]
    environment:
      POSTGRES_DB: omnicast
      POSTGRES_USER: omnicast
      POSTGRES_PASSWORD: dev_password
    volumes:
      - pgdata:/var/lib/postgresql/data

  rabbitmq:
    image: rabbitmq:3.13-management-alpine
    ports: ["5672:5672", "15672:15672"]
    environment:
      RABBITMQ_DEFAULT_USER: omnicast
      RABBITMQ_DEFAULT_PASS: dev_password

  redis:
    image: redis:7-alpine
    ports: ["6379:6379"]
    command: redis-server --maxmemory 256mb --maxmemory-policy allkeys-lru

volumes:
  pgdata:
```

### .env.example

```bash
# Database
DATABASE_URL=postgresql+asyncpg://omnicast:dev_password@localhost:5432/omnicast

# RabbitMQ
RABBITMQ_URL=amqp://omnicast:dev_password@localhost:5672/

# Redis
REDIS_URL=redis://localhost:6379/0

# Telegram
TELEGRAM_BOT_TOKEN=your_bot_token_here
TELEGRAM_CHAT_ID=your_chat_id_here

# Claude API
CLAUDE_API_KEY=your_key_here

# Mode
OMNICAST_MODE=dry_run  # production | dry_run | staging

# NAS
NAS_MOUNT_PATH=/Volumes/NAS
NAS_FALLBACK_PATH=/tmp/omnicast_local
```

## 2. Shared Error Types

### File: `src/omnicast/shared/__init__.py`
```python
```

### File: `src/omnicast/shared/errors.py`

```python
"""Custom exceptions cho OmniCast Engine.

Hierarchy:
  OmnicastError
  ├── ConfigError
  ├── DatabaseError
  │   └── NotFoundError
  ├── QueueError
  ├── CacheError
  ├── StorageError
  │   └── NASUnavailableError
  ├── RateLimitError
  ├── CircuitOpenError
  ├── UploadError
  ├── ComplianceError
  └── AgentError
"""

class OmnicastError(Exception):
    """Base exception. Tất cả custom exceptions kế thừa từ đây."""
    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}

class ConfigError(OmnicastError): ...
class DatabaseError(OmnicastError): ...
class NotFoundError(DatabaseError): ...
class QueueError(OmnicastError): ...
class CacheError(OmnicastError): ...
class StorageError(OmnicastError): ...
class NASUnavailableError(StorageError): ...
class RateLimitError(OmnicastError): ...
class CircuitOpenError(OmnicastError): ...
class UploadError(OmnicastError): ...
class ComplianceError(OmnicastError): ...
class AgentError(OmnicastError): ...
```

## 3. Enums

### File: `src/omnicast/models/__init__.py`
```python
```

### File: `src/omnicast/models/enums.py`

Tạo tất cả enum values dùng xuyên suốt hệ thống.

```python
from enum import StrEnum

class ChannelType(StrEnum):
    HUB = "hub"
    SPOKE = "spoke"

class ChannelStatus(StrEnum):
    SETUP = "setup"           # Đang cấu hình
    WARMING = "warming"       # Shadow warm-up
    ACTIVE = "active"         # Đang production
    PAUSED = "paused"         # Tạm dừng (manual hoặc auto)
    SHADOWBAN = "shadowban"   # Nghi bị shadowban
    TOKEN_EXPIRED = "token_expired"
    DEAD = "dead"             # Bị terminate hoặc bỏ

class VideoStatus(StrEnum):
    QUEUED = "queued"
    RESEARCHING = "researching"
    SCRIPTING = "scripting"
    DEBATING = "debating"       # Writer ↔ Critic loop
    RENDERING = "rendering"
    QUALITY_CHECK = "quality_check"
    COMPLIANCE_CHECK = "compliance_check"
    READY_TO_UPLOAD = "ready_to_upload"
    UPLOADING = "uploading"
    PUBLISHED = "published"
    FAILED = "failed"
    DLQ = "dlq"                 # Dead letter queue
    KILLED = "killed"           # Operator killed

class TaskPriority(StrEnum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"
    EMERGENCY = "emergency"

class Niche(StrEnum):
    FINANCE = "finance"
    HEALTH = "health"
    MYTHOLOGY = "mythology"
    PSYCHOLOGY = "psychology"
    TECH = "tech"
    JP_CULTURE = "jp_culture"
    KR_CULTURE = "kr_culture"

class Market(StrEnum):
    US = "US"
    UK = "UK"
    AU = "AU"
    CA = "CA"
    JP = "JP"
    KR = "KR"

class AlertSeverity(StrEnum):
    CRITICAL = "critical"
    WARNING = "warning"
    INFO = "info"

class AssetType(StrEnum):
    MUSIC_YT_LIBRARY = "music_yt_library"
    MUSIC_ROYALTY_FREE = "music_royalty_free"
    MUSIC_AI_GENERATED = "music_ai_generated"
    SFX = "sfx"
    BROLL = "broll"
    INTRO = "intro"
    OUTRO = "outro"
    OVERLAY = "overlay"
    FONT = "font"

class MusicMood(StrEnum):
    CINEMATIC = "cinematic"
    LOFI = "lofi"
    EPIC = "epic"
    CALM = "calm"
    DRAMATIC = "dramatic"
    UPBEAT = "upbeat"
    DARK = "dark"
    INSPIRATIONAL = "inspirational"

class TopicSource(StrEnum):
    YOUTUBE_COMPETITOR = "youtube_competitor"
    GOOGLE_TRENDS = "google_trends"
    REDDIT = "reddit"
    PODCAST = "podcast"
    NEWS_RSS = "news_rss"
    MANUAL = "manual"            # Operator tạo thủ công
    COMMUNITY_POLL = "community_poll"

class LearningPath(StrEnum):
    PATH_1_AUTO = "path_1_auto"      # Silent Skill Optimization
    PATH_2_HUMAN = "path_2_human"    # Structured Learning + Human Gate
    PATH_3_CONTEXT = "path_3_context" # Context Expansion
```

## 4. Pydantic Schemas

### File: `src/omnicast/models/schemas.py`

Pydantic models cho data validation + serialization. KHÔNG chứa business logic.

```python
"""Pydantic v2 schemas. Frozen (immutable). Dùng cho API, queue messages, validation."""

from datetime import datetime, date
from pydantic import BaseModel, Field, field_validator
from omnicast.models.enums import (
    ChannelType, ChannelStatus, VideoStatus, TaskPriority,
    Niche, Market, AlertSeverity, AssetType, MusicMood,
    TopicSource, LearningPath,
)

# === Base ===

class OmnicastSchema(BaseModel):
    """Base schema. Frozen + from_attributes cho ORM compatibility."""
    model_config = {"frozen": True, "from_attributes": True}

# === Channel ===

class ChannelCreate(OmnicastSchema):
    name: str = Field(max_length=100)
    niche: Niche
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
    source: str            # e.g. "worker_2", "channel_fin_us"
    alert_type: str        # e.g. "heartbeat_failed", "token_expired"
    message: str
    details: dict = Field(default_factory=dict)

class AlertRead(AlertCreate):
    id: int
    fingerprint: str       # hash(alert_type + source + severity)
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
    created_at: datetime = Field(default_factory=datetime.utcnow)

class AlertMessage(OmnicastSchema):
    """Message format cho RabbitMQ alert queue."""
    severity: AlertSeverity
    source: str
    alert_type: str
    message: str
    details: dict = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=datetime.utcnow)

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

# === Brand Config ===

class BrandConfig(OmnicastSchema):
    """Brand configuration per channel. Loaded from JSON file."""
    channel_id: str
    voice_profile: str = "kokoro_en_us_v1"
    voice_clone: str | None = None
    color_palette: list[str] = Field(default_factory=lambda: ["#1A1A2E", "#E94560", "#FFFFFF"])
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
```

## 5. SQLAlchemy ORM Models

### File: `src/omnicast/models/orm.py`

```python
"""SQLAlchemy 2.0 ORM models. Mapped columns style."""

from datetime import datetime, date
from sqlalchemy import (
    String, Integer, Float, Boolean, Text, DateTime, Date,
    ForeignKey, JSON, Index, func,
)
from sqlalchemy.orm import (
    DeclarativeBase, Mapped, mapped_column, relationship,
)

class Base(DeclarativeBase):
    pass

class ChannelORM(Base):
    __tablename__ = "channels"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    niche: Mapped[str] = mapped_column(String(30), nullable=False)
    channel_type: Mapped[str] = mapped_column(String(10), nullable=False)  # hub|spoke
    language: Mapped[str] = mapped_column(String(5), default="en")
    target_market: Mapped[str] = mapped_column(String(5), nullable=False)
    google_cloud_project: Mapped[str] = mapped_column(String(100), nullable=False)
    api_key_ref: Mapped[str] = mapped_column(String(200), nullable=False)
    adspower_profile: Mapped[str | None] = mapped_column(String(100))
    brand_config_path: Mapped[str | None] = mapped_column(String(300))
    status: Mapped[str] = mapped_column(String(20), default="setup")
    monetized: Mapped[bool] = mapped_column(Boolean, default=False)
    subscriber_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    # Relationships
    videos: Mapped[list["VideoORM"]] = relationship(back_populates="channel")
    metrics: Mapped[list["ChannelMetricsORM"]] = relationship(back_populates="channel")

    __table_args__ = (
        Index("ix_channels_niche", "niche"),
        Index("ix_channels_status", "status"),
    )

class ChannelMetricsORM(Base):
    __tablename__ = "channel_metrics"

    id: Mapped[int] = mapped_column(primary_key=True)
    channel_id: Mapped[int] = mapped_column(ForeignKey("channels.id"), nullable=False)
    recorded_date: Mapped[date] = mapped_column(Date, nullable=False)
    views: Mapped[int] = mapped_column(Integer, default=0)
    impressions: Mapped[int] = mapped_column(Integer, default=0)
    ctr: Mapped[float] = mapped_column(Float, default=0.0)
    avg_view_duration: Mapped[float] = mapped_column(Float, default=0.0)
    avg_view_percentage: Mapped[float] = mapped_column(Float, default=0.0)
    rpm: Mapped[float] = mapped_column(Float, default=0.0)
    estimated_revenue: Mapped[float] = mapped_column(Float, default=0.0)
    subscribers_gained: Mapped[int] = mapped_column(Integer, default=0)
    subscribers_lost: Mapped[int] = mapped_column(Integer, default=0)
    health_score: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    channel: Mapped["ChannelORM"] = relationship(back_populates="metrics")

    __table_args__ = (
        Index("ix_channel_metrics_channel_date", "channel_id", "recorded_date"),
    )

class VideoORM(Base):
    __tablename__ = "videos"

    id: Mapped[int] = mapped_column(primary_key=True)
    channel_id: Mapped[int] = mapped_column(ForeignKey("channels.id"), nullable=False)
    youtube_video_id: Mapped[str | None] = mapped_column(String(20))
    title: Mapped[str] = mapped_column(String(100), nullable=False)
    niche: Mapped[str] = mapped_column(String(30), nullable=False)
    target_market: Mapped[str] = mapped_column(String(5), nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="queued")
    priority: Mapped[str] = mapped_column(String(15), default="normal")
    topic_source: Mapped[str] = mapped_column(String(30), nullable=False)
    brief: Mapped[str | None] = mapped_column(Text)
    duration_seconds: Mapped[int | None] = mapped_column(Integer)
    critic_score: Mapped[float | None] = mapped_column(Float)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    revenue_usd: Mapped[float] = mapped_column(Float, default=0.0)
    roi: Mapped[float | None] = mapped_column(Float)
    thumbnail_variant: Mapped[str | None] = mapped_column(String(5))
    audit_trail: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    published_at: Mapped[datetime | None] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    channel: Mapped["ChannelORM"] = relationship(back_populates="videos")
    metrics: Mapped[list["VideoMetricsORM"]] = relationship(back_populates="video")

    __table_args__ = (
        Index("ix_videos_channel_status", "channel_id", "status"),
        Index("ix_videos_status", "status"),
        Index("ix_videos_niche", "niche"),
    )

class VideoMetricsORM(Base):
    __tablename__ = "video_metrics"

    id: Mapped[int] = mapped_column(primary_key=True)
    video_id: Mapped[int] = mapped_column(ForeignKey("videos.id"), nullable=False)
    channel_id: Mapped[int] = mapped_column(ForeignKey("channels.id"), nullable=False)
    views: Mapped[int] = mapped_column(Integer, default=0)
    ctr: Mapped[float] = mapped_column(Float, default=0.0)
    avg_view_duration: Mapped[float] = mapped_column(Float, default=0.0)
    avg_view_percentage: Mapped[float] = mapped_column(Float, default=0.0)
    is_outlier: Mapped[bool] = mapped_column(Boolean, default=False)
    is_underperformer: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    video: Mapped["VideoORM"] = relationship(back_populates="metrics")

    __table_args__ = (
        Index("ix_video_metrics_video", "video_id"),
    )

class AssetORM(Base):
    __tablename__ = "assets"

    id: Mapped[int] = mapped_column(primary_key=True)
    path: Mapped[str] = mapped_column(String(500), nullable=False, unique=True)
    asset_type: Mapped[str] = mapped_column(String(30), nullable=False)
    mood: Mapped[str | None] = mapped_column(String(20))
    bpm: Mapped[int | None] = mapped_column(Integer)
    duration_seconds: Mapped[float | None] = mapped_column(Float)
    license_info: Mapped[str | None] = mapped_column(String(200))
    tags: Mapped[list] = mapped_column(JSON, default=list)
    md5_hash: Mapped[str] = mapped_column(String(32), nullable=False)
    use_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (
        Index("ix_assets_type_mood", "asset_type", "mood"),
        Index("ix_assets_md5", "md5_hash"),
    )

class AlertORM(Base):
    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(primary_key=True)
    severity: Mapped[str] = mapped_column(String(10), nullable=False)
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    alert_type: Mapped[str] = mapped_column(String(50), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    suppressed_count: Mapped[int] = mapped_column(Integer, default=0)
    resolved: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime)

    __table_args__ = (
        Index("ix_alerts_fingerprint", "fingerprint"),
        Index("ix_alerts_severity_resolved", "severity", "resolved"),
    )

class LessonORM(Base):
    __tablename__ = "lessons"

    id: Mapped[int] = mapped_column(primary_key=True)
    agent_name: Mapped[str] = mapped_column(String(50), nullable=False)
    source: Mapped[str] = mapped_column(String(30), nullable=False)
    lesson: Mapped[str] = mapped_column(Text, nullable=False)
    evidence: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    applied_count: Mapped[int] = mapped_column(Integer, default=0)
    success_rate: Mapped[float] = mapped_column(Float, default=0.0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("ix_lessons_agent", "agent_name"),
        Index("ix_lessons_active", "active"),
    )

class PromptVersionORM(Base):
    __tablename__ = "prompt_versions"

    id: Mapped[int] = mapped_column(primary_key=True)
    agent_name: Mapped[str] = mapped_column(String(50), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    is_canary: Mapped[bool] = mapped_column(Boolean, default=False)
    canary_traffic_pct: Mapped[int] = mapped_column(Integer, default=0)
    performance_score: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (
        Index("ix_prompt_versions_agent_active", "agent_name", "is_active"),
    )

class ExpenseORM(Base):
    __tablename__ = "expenses"

    id: Mapped[int] = mapped_column(primary_key=True)
    category: Mapped[str] = mapped_column(String(30), nullable=False)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    description: Mapped[str] = mapped_column(String(300), nullable=False)
    receipt_path: Mapped[str | None] = mapped_column(String(500))
    tax_deductible: Mapped[bool] = mapped_column(Boolean, default=True)
    auto_tracked: Mapped[bool] = mapped_column(Boolean, default=False)
    recorded_date: Mapped[date] = mapped_column(Date, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

class ChannelStrikeORM(Base):
    __tablename__ = "channel_strikes"

    id: Mapped[int] = mapped_column(primary_key=True)
    channel_id: Mapped[int] = mapped_column(ForeignKey("channels.id"), nullable=False)
    strike_type: Mapped[str] = mapped_column(String(30), nullable=False)
    video_id: Mapped[int | None] = mapped_column(ForeignKey("videos.id"))
    details: Mapped[str] = mapped_column(Text, nullable=False)
    received_date: Mapped[date] = mapped_column(Date, nullable=False)
    expires_date: Mapped[date | None] = mapped_column(Date)
    dispute_status: Mapped[str | None] = mapped_column(String(20))
    dispute_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (
        Index("ix_strikes_channel", "channel_id"),
    )
```

## 6. Tests

### File: `tests/conftest.py`

```python
"""Shared test fixtures."""
import pytest
from omnicast.models.schemas import ChannelCreate, VideoCreate, BrandConfig
from omnicast.models.enums import Niche, Market, ChannelType, TopicSource

@pytest.fixture
def sample_channel_create() -> ChannelCreate:
    return ChannelCreate(
        name="Finance Hub US",
        niche=Niche.FINANCE,
        channel_type=ChannelType.HUB,
        target_market=Market.US,
        google_cloud_project="omnicast-fin-us",
        api_key_ref="sops://keys/fin_us.enc",
    )

@pytest.fixture
def sample_video_create() -> VideoCreate:
    return VideoCreate(
        channel_id=1,
        title="5 Investment Mistakes to Avoid in 2026",
        niche=Niche.FINANCE,
        target_market=Market.US,
        topic_source=TopicSource.GOOGLE_TRENDS,
    )

@pytest.fixture
def sample_brand_config() -> BrandConfig:
    return BrandConfig(
        channel_id="hub_finance_us",
        voice_profile="kokoro_en_us_v1",
        color_palette=["#1A1A2E", "#E94560", "#FFFFFF"],
        font="Montserrat Bold",
    )
```

### File: `tests/unit/test_models.py`

```python
"""Test Pydantic models validation."""
import pytest
from pydantic import ValidationError
from omnicast.models.schemas import (
    ChannelCreate, VideoCreate, TopicCandidate, AlertCreate, BrandConfig,
)
from omnicast.models.enums import (
    Niche, Market, ChannelType, TopicSource, AlertSeverity,
)

class TestChannelCreate:
    def test_valid(self, sample_channel_create):
        assert sample_channel_create.name == "Finance Hub US"
        assert sample_channel_create.niche == Niche.FINANCE

    def test_name_too_long(self):
        with pytest.raises(ValidationError):
            ChannelCreate(
                name="x" * 101,
                niche=Niche.FINANCE,
                channel_type=ChannelType.HUB,
                target_market=Market.US,
                google_cloud_project="proj",
                api_key_ref="ref",
            )

    def test_frozen(self, sample_channel_create):
        with pytest.raises(ValidationError):
            sample_channel_create.name = "new name"

class TestTopicCandidate:
    def test_score_bounds(self):
        with pytest.raises(ValidationError):
            TopicCandidate(
                title="Test",
                niche=Niche.FINANCE,
                market=Market.US,
                source=TopicSource.REDDIT,
                trend_momentum=50,  # max 30 → should fail
                gap_score=0,
                rpm_potential=0,
                novelty_score=0,
                total_score=50,
            )

    def test_valid_topic(self):
        topic = TopicCandidate(
            title="Bitcoin ETF Impact",
            niche=Niche.FINANCE,
            market=Market.US,
            source=TopicSource.GOOGLE_TRENDS,
            trend_momentum=25,
            gap_score=35,
            rpm_potential=15,
            novelty_score=8,
            total_score=83,
        )
        assert topic.total_score == 83

class TestAlertCreate:
    def test_valid(self):
        alert = AlertCreate(
            severity=AlertSeverity.CRITICAL,
            source="worker_2",
            alert_type="heartbeat_failed",
            message="Worker 2 heartbeat missed for 90s",
        )
        assert alert.severity == AlertSeverity.CRITICAL

class TestBrandConfig:
    def test_defaults(self):
        config = BrandConfig(channel_id="test")
        assert config.voice_profile == "kokoro_en_us_v1"
        assert config.max_segment_duration == 60
        assert config.use_video_gen is False
```

## 7. DO NOT

- ❌ Đừng thêm business logic vào models — chỉ data + validation
- ❌ Đừng dùng `dataclass` — dùng Pydantic v2
- ❌ Đừng dùng SQLAlchemy 1.x style (Column, declarative_base()) — dùng 2.0 mapped_column
- ❌ Đừng dùng mutable Pydantic models — luôn `frozen=True`
- ❌ Đừng hardcode enum values dạng string — dùng StrEnum
- ❌ Đừng import từ đường dẫn tương đối — luôn `from omnicast.xxx import yyy`

## 8. Acceptance Criteria

```bash
# Models validate đúng
uv run pytest tests/unit/test_models.py -v

# All imports work
uv run python -c "from omnicast.models.enums import *; from omnicast.models.schemas import *; from omnicast.models.orm import *; from omnicast.shared.errors import *; print('OK')"

# Type check passes
uv run pyright src/omnicast/models/ src/omnicast/shared/

# Docker compose starts
docker compose up -d && docker compose ps && docker compose down
```
