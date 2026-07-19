"""SQLAlchemy 2.0 ORM models. Mapped columns style."""

from datetime import datetime, date

from sqlalchemy import (
    String,
    Integer,
    Float,
    Boolean,
    Text,
    DateTime,
    Date,
    ForeignKey,
    JSON,
    Index,
    func,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    relationship,
)


class Base(DeclarativeBase):
    pass


class ChannelORM(Base):
    __tablename__ = "channels"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    niche: Mapped[str] = mapped_column(String(30), nullable=False)
    sub_niche: Mapped[str] = mapped_column(String(30), default="")
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
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

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
    channel_id: Mapped[int] = mapped_column(
        ForeignKey("channels.id"), nullable=False
    )
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
    channel_id: Mapped[int] = mapped_column(
        ForeignKey("channels.id"), nullable=False
    )
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
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

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
    channel_id: Mapped[int] = mapped_column(
        ForeignKey("channels.id"), nullable=False
    )
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
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

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
    channel_id: Mapped[int] = mapped_column(
        ForeignKey("channels.id"), nullable=False
    )
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