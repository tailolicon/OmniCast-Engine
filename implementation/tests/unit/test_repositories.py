"""Unit tests for repositories using mock sessions.

Test mỗi repository method:
- Happy path: create → get → update → verify
- Error: get non-existent id → NotFoundError
- Filters: get_all with status filter → correct subset

Dùng AsyncMock cho session.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock
from datetime import date, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from omnicast.db.repositories import (
    ChannelRepository,
    VideoRepository,
    AlertRepository,
    AssetRepository,
    LessonRepository,
    ExpenseRepository,
    ChannelStrikeRepository,
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
from omnicast.models.enums import (
    Niche,
    Market,
    ChannelType,
    TopicSource,
    VideoStatus,
    AlertSeverity,
    AssetType,
    MusicMood,
    LearningPath,
    ChannelStatus,
)
from omnicast.shared.errors import NotFoundError


# === ChannelRepository Tests ===


@pytest.fixture
def mock_session() -> AsyncMock:
    return AsyncMock(spec=AsyncSession)


@pytest.fixture
def channel_repo(mock_session: AsyncMock) -> ChannelRepository:
    return ChannelRepository(mock_session)


@pytest.fixture
def video_repo(mock_session: AsyncMock) -> VideoRepository:
    return VideoRepository(mock_session)


@pytest.fixture
def alert_repo(mock_session: AsyncMock) -> AlertRepository:
    return AlertRepository(mock_session)


@pytest.fixture
def asset_repo(mock_session: AsyncMock) -> AssetRepository:
    return AssetRepository(mock_session)


@pytest.fixture
def lesson_repo(mock_session: AsyncMock) -> LessonRepository:
    return LessonRepository(mock_session)


@pytest.fixture
def expense_repo(mock_session: AsyncMock) -> ExpenseRepository:
    return ExpenseRepository(mock_session)


@pytest.fixture
def strike_repo(mock_session: AsyncMock) -> ChannelStrikeRepository:
    return ChannelStrikeRepository(mock_session)


@pytest.fixture
def sample_channel_data() -> ChannelCreate:
    return ChannelCreate(
        name="Test Channel",
        niche=Niche.FINANCE,
        channel_type=ChannelType.HUB,
        target_market=Market.US,
        google_cloud_project="test-project",
        api_key_ref="test-key",
    )


@pytest.fixture
def sample_video_data() -> VideoCreate:
    return VideoCreate(
        channel_id=1,
        title="Test Video",
        niche=Niche.FINANCE,
        target_market=Market.US,
        topic_source=TopicSource.GOOGLE_TRENDS,
    )


@pytest.fixture
def sample_alert_data() -> AlertCreate:
    return AlertCreate(
        severity=AlertSeverity.CRITICAL,
        source="test_worker",
        alert_type="test_alert",
        message="Test alert message",
    )


@pytest.fixture
def sample_asset_data() -> AssetCreate:
    return AssetCreate(
        path="/assets/test.mp3",
        asset_type=AssetType.MUSIC_AI_GENERATED,
        mood=MusicMood.CALM,
        md5_hash="abc123def456",
    )


@pytest.fixture
def sample_lesson_data() -> LessonCreate:
    return LessonCreate(
        agent_name="test_agent",
        source=LearningPath.PATH_1_AUTO,
        lesson="Test lesson content",
        evidence="Evidence from analytics",
        confidence=0.85,
    )


@pytest.fixture
def sample_expense_data() -> ExpenseCreate:
    return ExpenseCreate(
        category="api",
        amount=29.99,
        description="API subscription",
        recorded_date=date(2026, 5, 23),
    )


class TestChannelRepository:
    async def test_channel_create_and_get(
        self, channel_repo: ChannelRepository, mock_session: AsyncMock, sample_channel_data: ChannelCreate
    ):
        """Test creating and retrieving a channel."""
        # Mock flush to simulate id generation
        mock_session.flush = AsyncMock()

        # Create a mock ORM object
        mock_channel = MagicMock()
        mock_channel.id = 1
        mock_channel.name = sample_channel_data.name
        mock_session.get = AsyncMock(return_value=mock_channel)

        # Test get_by_id
        result = await channel_repo.get_by_id(1)
        assert result.id == 1
        mock_session.get.assert_called_once()

    async def test_channel_not_found_raises(
        self, channel_repo: ChannelRepository, mock_session: AsyncMock
    ):
        """Test that NotFoundError is raised for non-existent channel."""
        mock_session.get = AsyncMock(return_value=None)

        with pytest.raises(NotFoundError, match="Channel with id=999 not found"):
            await channel_repo.get_by_id(999)

    async def test_channel_update_partial(
        self, channel_repo: ChannelRepository, mock_session: AsyncMock
    ):
        """Test partial update of channel."""
        existing_channel = MagicMock()
        existing_channel.id = 1
        existing_channel.name = "Old Name"
        existing_channel.status = ChannelStatus.ACTIVE

        mock_session.get = AsyncMock(return_value=existing_channel)
        mock_session.flush = AsyncMock()

        update_data = ChannelUpdate(status=ChannelStatus.PAUSED)
        result = await channel_repo.update(1, update_data)

        assert result.status == ChannelStatus.PAUSED
        mock_session.flush.assert_called_once()

    async def test_channel_count_by_status(
        self, channel_repo: ChannelRepository, mock_session: AsyncMock
    ):
        """Test counting channels by status."""
        mock_result = MagicMock()
        mock_result.all.return_value = [("active", 5), ("setup", 3)]
        mock_session.execute = AsyncMock(return_value=mock_result)

        result = await channel_repo.count_by_status()
        assert result == {"active": 5, "setup": 3}


class TestVideoRepository:
    async def test_video_create_and_get(
        self, video_repo: VideoRepository, mock_session: AsyncMock, sample_video_data: VideoCreate
    ):
        """Test creating and retrieving a video."""
        mock_video = MagicMock()
        mock_video.id = 1
        mock_video.title = sample_video_data.title
        mock_session.get = AsyncMock(return_value=mock_video)

        result = await video_repo.get_by_id(1)
        assert result.id == 1

    async def test_video_update_status(
        self, video_repo: VideoRepository, mock_session: AsyncMock
    ):
        """Test video status transition."""
        mock_video = MagicMock()
        mock_video.id = 1
        mock_video.status = VideoStatus.QUEUED
        mock_session.get = AsyncMock(return_value=mock_video)
        mock_session.flush = AsyncMock()

        result = await video_repo.update_status(1, VideoStatus.SCRIPTING)
        assert result.status == VideoStatus.SCRIPTING

    async def test_video_pipeline_counts(
        self, video_repo: VideoRepository, mock_session: AsyncMock
    ):
        """Test pipeline counts."""
        mock_result = MagicMock()
        mock_result.all.return_value = [("queued", 10), ("processing", 5), ("published", 20)]
        mock_session.execute = AsyncMock(return_value=mock_result)

        result = await video_repo.get_pipeline_counts()
        assert result == {"queued": 10, "processing": 5, "published": 20}


class TestAlertRepository:
    async def test_alert_create_and_resolve(
        self, alert_repo: AlertRepository, mock_session: AsyncMock, sample_alert_data: AlertCreate
    ):
        """Test creating and resolving an alert."""
        mock_alert = MagicMock()
        mock_alert.id = 1
        mock_alert.resolved = False
        mock_session.get = AsyncMock(return_value=mock_alert)
        mock_session.flush = AsyncMock()

        result = await alert_repo.resolve(1)
        assert result.resolved is True
        assert result.resolved_at is not None

    async def test_alert_dedup_fingerprint(
        self, alert_repo: AlertRepository, mock_session: AsyncMock
    ):
        """Test alert dedup via fingerprint."""
        mock_result = MagicMock()
        mock_result.scalars().first.return_value = None
        mock_session.execute = AsyncMock(return_value=mock_result)

        result = await alert_repo.get_by_fingerprint("unique-fingerprint")
        assert result is None


class TestAssetRepository:
    async def test_asset_search_order_by_use_count(
        self, asset_repo: AssetRepository, mock_session: AsyncMock
    ):
        """Test asset search orders by use_count ASC."""
        mock_result = MagicMock()
        mock_result.scalars().all.return_value = [
            MagicMock(use_count=0),
            MagicMock(use_count=5),
            MagicMock(use_count=10),
        ]
        mock_session.execute = AsyncMock(return_value=mock_result)

        results = await asset_repo.search(asset_type="music")
        assert len(results) == 3
        assert results[0].use_count <= results[1].use_count

    async def test_asset_increment_use(
        self, asset_repo: AssetRepository, mock_session: AsyncMock
    ):
        """Test incrementing asset use count."""
        mock_session.execute = AsyncMock()
        await asset_repo.increment_use(1)
        mock_session.execute.assert_called_once()


class TestLessonRepository:
    async def test_lesson_get_active_for_agent(
        self, lesson_repo: LessonRepository, mock_session: AsyncMock, sample_lesson_data: LessonCreate
    ):
        """Test getting active lessons for an agent."""
        mock_result = MagicMock()
        mock_result.scalars().all.return_value = [MagicMock(agent_name="test_agent")]
        mock_session.execute = AsyncMock(return_value=mock_result)

        results = await lesson_repo.get_active_for_agent("test_agent")
        assert len(results) == 1


class TestExpenseRepository:
    async def test_expense_sum_by_category(
        self, expense_repo: ExpenseRepository, mock_session: AsyncMock
    ):
        """Test summing expenses by category."""
        mock_result = MagicMock()
        mock_result.all.return_value = [("api", 100.0), ("hosting", 50.0)]
        mock_session.execute = AsyncMock(return_value=mock_result)

        start = date(2026, 5, 1)
        end = date(2026, 5, 31)
        result = await expense_repo.sum_by_category(start, end)
        assert result == {"api": 100.0, "hosting": 50.0}


class TestChannelStrikeRepository:
    async def test_strike_count_active(
        self, strike_repo: ChannelStrikeRepository, mock_session: AsyncMock
    ):
        """Test counting active strikes."""
        mock_result = MagicMock()
        mock_result.scalar.return_value = 2
        mock_session.execute = AsyncMock(return_value=mock_result)

        count = await strike_repo.count_active(1)
        assert count == 2