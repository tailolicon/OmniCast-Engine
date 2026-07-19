"""Initial schema — all tables from orm.py

Revision ID: 001
Revises:
Create Date: 2026-05-23 11:00:00.000000

Tables created:
  channels, channel_metrics, videos, video_metrics,
  assets, alerts, lessons, prompt_versions, expenses, channel_strikes

All indexes from orm.py __table_args__ are included.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # channels
    op.create_table(
        "channels",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("niche", sa.String(length=30), nullable=False),
        sa.Column("channel_type", sa.String(length=10), nullable=False),
        sa.Column("language", sa.String(length=5), nullable=True, server_default="en"),
        sa.Column("target_market", sa.String(length=5), nullable=False),
        sa.Column("google_cloud_project", sa.String(length=100), nullable=False),
        sa.Column("api_key_ref", sa.String(length=200), nullable=False),
        sa.Column("adspower_profile", sa.String(length=100), nullable=True),
        sa.Column("brand_config_path", sa.String(length=300), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=True, server_default="setup"),
        sa.Column("monetized", sa.Boolean(), nullable=True, server_default=sa.false()),
        sa.Column("subscriber_count", sa.Integer(), nullable=True, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=True,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=True,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_channels_niche", "channels", ["niche"])
    op.create_index("ix_channels_status", "channels", ["status"])

    # channel_metrics
    op.create_table(
        "channel_metrics",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("channel_id", sa.Integer(), nullable=False),
        sa.Column("recorded_date", sa.Date(), nullable=False),
        sa.Column("views", sa.Integer(), nullable=True, server_default="0"),
        sa.Column("impressions", sa.Integer(), nullable=True, server_default="0"),
        sa.Column("ctr", sa.Float(), nullable=True, server_default="0.0"),
        sa.Column("avg_view_duration", sa.Float(), nullable=True, server_default="0.0"),
        sa.Column("avg_view_percentage", sa.Float(), nullable=True, server_default="0.0"),
        sa.Column("rpm", sa.Float(), nullable=True, server_default="0.0"),
        sa.Column("estimated_revenue", sa.Float(), nullable=True, server_default="0.0"),
        sa.Column("subscribers_gained", sa.Integer(), nullable=True, server_default="0"),
        sa.Column("subscribers_lost", sa.Integer(), nullable=True, server_default="0"),
        sa.Column("health_score", sa.Float(), nullable=True, server_default="0.0"),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=True,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["channel_id"], ["channels.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_channel_metrics_channel_date",
        "channel_metrics",
        ["channel_id", "recorded_date"],
    )

    # videos
    op.create_table(
        "videos",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("channel_id", sa.Integer(), nullable=False),
        sa.Column("youtube_video_id", sa.String(length=20), nullable=True),
        sa.Column("title", sa.String(length=100), nullable=False),
        sa.Column("niche", sa.String(length=30), nullable=False),
        sa.Column("target_market", sa.String(length=5), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=True, server_default="queued"),
        sa.Column(
            "priority", sa.String(length=15), nullable=True, server_default="normal"
        ),
        sa.Column("topic_source", sa.String(length=30), nullable=False),
        sa.Column("brief", sa.Text(), nullable=True),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column("critic_score", sa.Float(), nullable=True),
        sa.Column("cost_usd", sa.Float(), nullable=True, server_default="0.0"),
        sa.Column("revenue_usd", sa.Float(), nullable=True, server_default="0.0"),
        sa.Column("roi", sa.Float(), nullable=True),
        sa.Column("thumbnail_variant", sa.String(length=5), nullable=True),
        sa.Column("audit_trail", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=True,
            server_default=sa.func.now(),
        ),
        sa.Column("published_at", sa.DateTime(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=True,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["channel_id"], ["channels.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_videos_channel_status", "videos", ["channel_id", "status"])
    op.create_index("ix_videos_status", "videos", ["status"])
    op.create_index("ix_videos_niche", "videos", ["niche"])

    # video_metrics
    op.create_table(
        "video_metrics",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("video_id", sa.Integer(), nullable=False),
        sa.Column("channel_id", sa.Integer(), nullable=False),
        sa.Column("views", sa.Integer(), nullable=True, server_default="0"),
        sa.Column("ctr", sa.Float(), nullable=True, server_default="0.0"),
        sa.Column("avg_view_duration", sa.Float(), nullable=True, server_default="0.0"),
        sa.Column("avg_view_percentage", sa.Float(), nullable=True, server_default="0.0"),
        sa.Column("is_outlier", sa.Boolean(), nullable=True, server_default=sa.false()),
        sa.Column(
            "is_underperformer", sa.Boolean(), nullable=True, server_default=sa.false()
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=True,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["video_id"], ["videos.id"]),
        sa.ForeignKeyConstraint(["channel_id"], ["channels.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_video_metrics_video", "video_metrics", ["video_id"])

    # assets
    op.create_table(
        "assets",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("path", sa.String(length=500), nullable=False),
        sa.Column("asset_type", sa.String(length=30), nullable=False),
        sa.Column("mood", sa.String(length=20), nullable=True),
        sa.Column("bpm", sa.Integer(), nullable=True),
        sa.Column("duration_seconds", sa.Float(), nullable=True),
        sa.Column("license_info", sa.String(length=200), nullable=True),
        sa.Column("tags", sa.JSON(), nullable=True),
        sa.Column("md5_hash", sa.String(length=32), nullable=False),
        sa.Column("use_count", sa.Integer(), nullable=True, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=True,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("path"),
    )
    op.create_index("ix_assets_type_mood", "assets", ["asset_type", "mood"])
    op.create_index("ix_assets_md5", "assets", ["md5_hash"])

    # alerts
    op.create_table(
        "alerts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("severity", sa.String(length=10), nullable=False),
        sa.Column("source", sa.String(length=50), nullable=False),
        sa.Column("alert_type", sa.String(length=50), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("details", sa.JSON(), nullable=True),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("suppressed_count", sa.Integer(), nullable=True, server_default="0"),
        sa.Column("resolved", sa.Boolean(), nullable=True, server_default=sa.false()),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=True,
            server_default=sa.func.now(),
        ),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_alerts_fingerprint", "alerts", ["fingerprint"])
    op.create_index("ix_alerts_severity_resolved", "alerts", ["severity", "resolved"])

    # lessons
    op.create_table(
        "lessons",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("agent_name", sa.String(length=50), nullable=False),
        sa.Column("source", sa.String(length=30), nullable=False),
        sa.Column("lesson", sa.Text(), nullable=False),
        sa.Column("evidence", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True, server_default="0.5"),
        sa.Column("applied_count", sa.Integer(), nullable=True, server_default="0"),
        sa.Column("success_rate", sa.Float(), nullable=True, server_default="0.0"),
        sa.Column("active", sa.Boolean(), nullable=True, server_default=sa.true()),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=True,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=True,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_lessons_agent", "lessons", ["agent_name"])
    op.create_index("ix_lessons_active", "lessons", ["active"])

    # prompt_versions
    op.create_table(
        "prompt_versions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("agent_name", sa.String(length=50), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=True, server_default=sa.false()),
        sa.Column("is_canary", sa.Boolean(), nullable=True, server_default=sa.false()),
        sa.Column(
            "canary_traffic_pct", sa.Integer(), nullable=True, server_default="0"
        ),
        sa.Column("performance_score", sa.Float(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=True,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_prompt_versions_agent_active",
        "prompt_versions",
        ["agent_name", "is_active"],
    )

    # expenses
    op.create_table(
        "expenses",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("category", sa.String(length=30), nullable=False),
        sa.Column("amount", sa.Float(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=True, server_default="USD"),
        sa.Column("description", sa.String(length=300), nullable=False),
        sa.Column("receipt_path", sa.String(length=500), nullable=True),
        sa.Column("tax_deductible", sa.Boolean(), nullable=True, server_default=sa.true()),
        sa.Column("auto_tracked", sa.Boolean(), nullable=True, server_default=sa.false()),
        sa.Column("recorded_date", sa.Date(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=True,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    # channel_strikes
    op.create_table(
        "channel_strikes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("channel_id", sa.Integer(), nullable=False),
        sa.Column("strike_type", sa.String(length=30), nullable=False),
        sa.Column("video_id", sa.Integer(), nullable=True),
        sa.Column("details", sa.Text(), nullable=False),
        sa.Column("received_date", sa.Date(), nullable=False),
        sa.Column("expires_date", sa.Date(), nullable=True),
        sa.Column("dispute_status", sa.String(length=20), nullable=True),
        sa.Column("dispute_reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=True,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["channel_id"], ["channels.id"]),
        sa.ForeignKeyConstraint(["video_id"], ["videos.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_strikes_channel", "channel_strikes", ["channel_id"])


def downgrade() -> None:
    op.drop_table("channel_strikes")
    op.drop_table("expenses")
    op.drop_table("prompt_versions")
    op.drop_table("lessons")
    op.drop_table("alerts")
    op.drop_table("assets")
    op.drop_table("video_metrics")
    op.drop_table("videos")
    op.drop_table("channel_metrics")
    op.drop_table("channels")