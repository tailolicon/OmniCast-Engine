"""Repository classes for CRUD operations.

Pattern: one Repository class per ORM model. Each class receives AsyncSession
via constructor. Methods do NOT commit — commit is handled by the session
context manager in engine.py.

Usage:
    async with get_session() as session:
        repo = ChannelRepository(session)
        channel = await repo.create(channel_data)
"""

from __future__ import annotations

from datetime import date

from datetime import date as date_type, datetime, timezone

from sqlalchemy import select, func, update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from omnicast.models.orm import (
    ChannelORM,
    ChannelMetricsORM,
    VideoORM,
    VideoMetricsORM,
    AssetORM,
    AlertORM,
    LessonORM,
    ExpenseORM,
    ChannelStrikeORM,
)
from omnicast.models.schemas import (
    ChannelCreate,
    ChannelUpdate,
    VideoCreate,
    VideoUpdate,
    AlertCreate,
    AssetCreate,
    LessonCreate,
    ExpenseCreate,
)
from omnicast.shared.errors import NotFoundError


# === ChannelRepository ===


class ChannelRepository:
    """CRUD for channels table."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, data: ChannelCreate) -> ChannelORM:
        """Insert new channel. Return ORM instance with generated id."""
        channel = ChannelORM(**data.model_dump())
        self.session.add(channel)
        await self.session.flush()
        return channel

    async def get_by_id(self, channel_id: int) -> ChannelORM:
        """Get channel by id. Raise NotFoundError if not exists."""
        channel = await self.session.get(ChannelORM, channel_id)
        if channel is None:
            raise NotFoundError(f"Channel with id={channel_id} not found")
        return channel

    async def get_all(
        self,
        status: str | None = None,
        niche: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ChannelORM]:
        """Get channels with optional filters. Order by created_at DESC."""
        stmt = select(ChannelORM)
        if status:
            stmt = stmt.where(ChannelORM.status == status)
        if niche:
            stmt = stmt.where(ChannelORM.niche == niche)
        stmt = stmt.order_by(ChannelORM.created_at.desc()).limit(limit).offset(offset)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def update(self, channel_id: int, data: ChannelUpdate) -> ChannelORM:
        """Update channel fields. Only update non-None fields from ChannelUpdate."""
        channel = await self.get_by_id(channel_id)
        update_data = data.model_dump(exclude_none=True)
        for key, value in update_data.items():
            setattr(channel, key, value)
        await self.session.flush()
        return channel

    async def count_by_status(self) -> dict[str, int]:
        """Return {status: count} for all statuses. Uses GROUP BY."""
        stmt = select(ChannelORM.status, func.count(ChannelORM.id)).group_by(
            ChannelORM.status
        )
        result = await self.session.execute(stmt)
        return {row[0]: row[1] for row in result.all()}


# === VideoRepository ===


class VideoRepository:
    """CRUD for videos table."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, data: VideoCreate) -> VideoORM:
        """Insert new video. Return ORM with id."""
        video = VideoORM(**data.model_dump())
        self.session.add(video)
        await self.session.flush()
        return video

    async def get_by_id(self, video_id: int) -> VideoORM:
        """Get video by id. Raise NotFoundError if not exists."""
        video = await self.session.get(VideoORM, video_id)
        if video is None:
            raise NotFoundError(f"Video with id={video_id} not found")
        return video

    async def get_by_channel(
        self,
        channel_id: int,
        status: str | None = None,
        limit: int = 50,
    ) -> list[VideoORM]:
        """Get videos for channel, optional status filter. Order by created_at DESC."""
        stmt = select(VideoORM).where(VideoORM.channel_id == channel_id)
        if status:
            stmt = stmt.where(VideoORM.status == status)
        stmt = stmt.order_by(VideoORM.created_at.desc()).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def update(self, video_id: int, data: VideoUpdate) -> VideoORM:
        """Partial update. Only non-None fields."""
        video = await self.get_by_id(video_id)
        update_data = data.model_dump(exclude_none=True)
        for key, value in update_data.items():
            setattr(video, key, value)
        await self.session.flush()
        return video

    async def update_status(self, video_id: int, new_status: str) -> VideoORM:
        """Shortcut: update only status field. Log state transition."""
        logger = structlog.get_logger()
        video = await self.get_by_id(video_id)
        old_status = video.status
        video.status = new_status
        await self.session.flush()
        logger.info(
            "Video status transition",
            video_id=video_id,
            from_status=old_status,
            to_status=new_status,
        )
        return video

    async def get_pipeline_counts(self) -> dict[str, int]:
        """Return {status: count} for pipeline overview dashboard."""
        stmt = select(VideoORM.status, func.count(VideoORM.id)).group_by(
            VideoORM.status
        )
        result = await self.session.execute(stmt)
        return {row[0]: row[1] for row in result.all()}

    async def get_recent(self, limit: int = 20) -> list[VideoORM]:
        """Get most recent videos across all channels."""
        stmt = (
            select(VideoORM)
            .order_by(VideoORM.created_at.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


# === AlertRepository ===


class AlertRepository:
    """CRUD for alerts table."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, data: AlertCreate, fingerprint: str) -> AlertORM:
        """Insert new alert with computed fingerprint."""
        alert = AlertORM(
            **data.model_dump(),
            fingerprint=fingerprint,
        )
        self.session.add(alert)
        await self.session.flush()
        return alert

    async def get_unresolved(
        self,
        severity: str | None = None,
        limit: int = 50,
    ) -> list[AlertORM]:
        """Get unresolved alerts. Order by severity DESC, created_at DESC."""
        stmt = select(AlertORM).where(AlertORM.resolved == False)  # noqa: E712
        if severity:
            stmt = stmt.where(AlertORM.severity == severity)
        stmt = stmt.order_by(AlertORM.severity.desc(), AlertORM.created_at.desc()).limit(
            limit
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def resolve(self, alert_id: int) -> AlertORM:
        """Mark alert as resolved. Set resolved_at = now()."""
        alert = await self.session.get(AlertORM, alert_id)
        if alert is None:
            raise NotFoundError(f"Alert with id={alert_id} not found")
        alert.resolved = True
        alert.resolved_at = datetime.now(timezone.utc)
        await self.session.flush()
        return alert

    async def increment_suppressed(self, fingerprint: str) -> None:
        """Increment suppressed_count for alert with given fingerprint."""
        stmt = (
            sa_update(AlertORM)
            .where(AlertORM.fingerprint == fingerprint)
            .values(suppressed_count=AlertORM.suppressed_count + 1)
        )
        await self.session.execute(stmt)

    async def get_by_fingerprint(self, fingerprint: str) -> AlertORM | None:
        """Find active (unresolved) alert by fingerprint. Return None if not found."""
        stmt = select(AlertORM).where(
            AlertORM.fingerprint == fingerprint,
            AlertORM.resolved == False,  # noqa: E712
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()


# === AssetRepository ===


class AssetRepository:
    """CRUD for assets table."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, data: AssetCreate) -> AssetORM:
        """Insert new asset."""
        asset = AssetORM(**data.model_dump())
        self.session.add(asset)
        await self.session.flush()
        return asset

    async def search(
        self,
        asset_type: str,
        mood: str | None = None,
        limit: int = 10,
    ) -> list[AssetORM]:
        """Search assets. ORDER BY use_count ASC (ít dùng ưu tiên)."""
        stmt = select(AssetORM).where(AssetORM.asset_type == asset_type)
        if mood:
            stmt = stmt.where(AssetORM.mood == mood)
        stmt = stmt.order_by(AssetORM.use_count.asc()).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def increment_use(self, asset_id: int) -> None:
        """Increment use_count by 1."""
        stmt = (
            sa_update(AssetORM)
            .where(AssetORM.id == asset_id)
            .values(use_count=AssetORM.use_count + 1)
        )
        await self.session.execute(stmt)

    async def get_by_md5(self, md5_hash: str) -> AssetORM | None:
        """Find asset by MD5 hash. For dedup check."""
        stmt = select(AssetORM).where(AssetORM.md5_hash == md5_hash)
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def count_by_type_mood(self) -> list[dict]:
        """Return [{asset_type, mood, count}] for stock level dashboard."""
        stmt = select(
            AssetORM.asset_type,
            AssetORM.mood,
            func.count(AssetORM.id).label("count"),
        ).group_by(AssetORM.asset_type, AssetORM.mood)
        result = await self.session.execute(stmt)
        return [
            {"asset_type": row[0], "mood": row[1], "count": row[2]}
            for row in result.all()
        ]


# === LessonRepository ===


class LessonRepository:
    """CRUD for lessons table."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, data: LessonCreate) -> LessonORM:
        """Insert new lesson."""
        lesson = LessonORM(**data.model_dump())
        self.session.add(lesson)
        await self.session.flush()
        return lesson

    async def get_by_id(self, lesson_id: int) -> LessonORM:
        """Get lesson by id. Raise NotFoundError if not exists."""
        lesson = await self.session.get(LessonORM, lesson_id)
        if lesson is None:
            raise NotFoundError(f"Lesson with id={lesson_id} not found")
        return lesson

    async def get_all(
        self,
        agent_name: str | None = None,
        active_only: bool = True,
        limit: int = 100,
    ) -> list[LessonORM]:
        """Get lessons with optional filters."""
        stmt = select(LessonORM)
        if agent_name:
            stmt = stmt.where(LessonORM.agent_name == agent_name)
        if active_only:
            stmt = stmt.where(LessonORM.active == True)  # noqa: E712
        stmt = stmt.order_by(LessonORM.created_at.desc()).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def update(self, lesson_id: int, data: dict) -> LessonORM:
        """Update lesson fields."""
        lesson = await self.get_by_id(lesson_id)
        for key, value in data.items():
            setattr(lesson, key, value)
        await self.session.flush()
        return lesson

    async def get_active_for_agent(self, agent_name: str) -> list[LessonORM]:
        """Get active lessons for a specific agent."""
        stmt = select(LessonORM).where(
            LessonORM.agent_name == agent_name,
            LessonORM.active == True,  # noqa: E712
        ).order_by(LessonORM.confidence.desc())
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def deactivate(self, lesson_id: int) -> None:
        """Mark lesson as inactive."""
        lesson = await self.get_by_id(lesson_id)
        lesson.active = False
        await self.session.flush()


# === ExpenseRepository ===


class ExpenseRepository:
    """CRUD for expenses table."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, data: ExpenseCreate) -> ExpenseORM:
        """Insert new expense."""
        expense = ExpenseORM(**data.model_dump())
        self.session.add(expense)
        await self.session.flush()
        return expense

    async def get_by_id(self, expense_id: int) -> ExpenseORM:
        """Get expense by id. Raise NotFoundError if not exists."""
        expense = await self.session.get(ExpenseORM, expense_id)
        if expense is None:
            raise NotFoundError(f"Expense with id={expense_id} not found")
        return expense

    async def get_all(
        self,
        category: str | None = None,
        limit: int = 100,
    ) -> list[ExpenseORM]:
        """Get expenses with optional category filter."""
        stmt = select(ExpenseORM)
        if category:
            stmt = stmt.where(ExpenseORM.category == category)
        stmt = stmt.order_by(ExpenseORM.recorded_date.desc()).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_period(self, start: date, end: date) -> list[ExpenseORM]:
        """Get expenses within a date range."""
        stmt = select(ExpenseORM).where(
            ExpenseORM.recorded_date >= start,
            ExpenseORM.recorded_date <= end,
        ).order_by(ExpenseORM.recorded_date.desc())
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def sum_by_category(self, start: date, end: date) -> dict[str, float]:
        """Return {category: total_amount} for expenses in period."""
        stmt = select(
            ExpenseORM.category,
            func.sum(ExpenseORM.amount).label("total"),
        ).where(
            ExpenseORM.recorded_date >= start,
            ExpenseORM.recorded_date <= end,
        ).group_by(ExpenseORM.category)
        result = await self.session.execute(stmt)
        return {row[0]: row[1] for row in result.all()}


# === ChannelStrikeRepository ===


class ChannelStrikeRepository:
    """CRUD for channel_strikes table."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, data: dict) -> ChannelStrikeORM:
        """Insert new strike."""
        strike = ChannelStrikeORM(**data)
        self.session.add(strike)
        await self.session.flush()
        return strike

    async def get_by_id(self, strike_id: int) -> ChannelStrikeORM:
        """Get strike by id. Raise NotFoundError if not exists."""
        strike = await self.session.get(ChannelStrikeORM, strike_id)
        if strike is None:
            raise NotFoundError(f"Strike with id={strike_id} not found")
        return strike

    async def get_all(
        self,
        channel_id: int | None = None,
        limit: int = 100,
    ) -> list[ChannelStrikeORM]:
        """Get strikes with optional channel filter."""
        stmt = select(ChannelStrikeORM)
        if channel_id:
            stmt = stmt.where(ChannelStrikeORM.channel_id == channel_id)
        stmt = stmt.order_by(ChannelStrikeORM.received_date.desc()).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_active_strikes(self, channel_id: int) -> list[ChannelStrikeORM]:
        """Get active strikes for a channel.
        Active = expires_date is None OR expires_date > today.
        """
        stmt = select(ChannelStrikeORM).where(
            ChannelStrikeORM.channel_id == channel_id,
            (ChannelStrikeORM.expires_date.is_(None))
            | (ChannelStrikeORM.expires_date > date_type.today()),
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def count_active(self, channel_id: int) -> int:
        """Count active strikes for a channel."""
        stmt = select(func.count(ChannelStrikeORM.id)).where(
            ChannelStrikeORM.channel_id == channel_id,
            (ChannelStrikeORM.expires_date.is_(None))
            | (ChannelStrikeORM.expires_date > date_type.today()),
        )
        result = await self.session.execute(stmt)
        return result.scalar() or 0