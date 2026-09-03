"""Integration tests with real PostgreSQL via testcontainers.

Setup:
    @pytest.fixture(scope="module")
    async def pg_container():
        # Start PostgreSQL container
        # Run Alembic migrations
        # Yield container
        # Cleanup

Test cases:
- test_full_channel_lifecycle: create → update → get → count
- test_full_video_lifecycle: create → update_status through pipeline → get
- test_concurrent_sessions: 2 sessions writing simultaneously → no conflict
"""

import pytest
import pytest_asyncio

pytestmark = pytest.mark.asyncio(loop_scope="module")
from datetime import date

from testcontainers.postgres import PostgresContainer

from omnicast.db.engine import init_db, get_session, close_db
from omnicast.db.repositories import ChannelRepository, VideoRepository
from omnicast.models.schemas import ChannelCreate, ChannelUpdate, VideoCreate, VideoUpdate
from omnicast.models.enums import (
    Niche,
    Market,
    ChannelType,
    TopicSource,
    VideoStatus,
)


@pytest.fixture(scope="module")
def postgres_container():
    """Start PostgreSQL container for testing."""
    with PostgresContainer("postgres:16") as postgres:
        yield postgres


@pytest_asyncio.fixture(loop_scope="module", scope="module")
async def db_setup(postgres_container: PostgresContainer):
    """Initialize database and run migrations."""
    # Get the connection URL from testcontainers
    # Note: testcontainers returns a sync URL, we need to convert to async
    sync_url = postgres_container.get_connection_url()
    # Replace the sync driver (testcontainers 4.x returns postgresql+psycopg2://)
    # with the async one the engine expects.
    async_url = sync_url.replace(
        "postgresql+psycopg2://", "postgresql+asyncpg://"
    ).replace("postgresql://", "postgresql+asyncpg://")

    init_db(async_url, pool_size=2, max_overflow=0)

    # Run migrations programmatically
    import asyncio
    from alembic import command
    from alembic.config import Config
    from pathlib import Path

    alembic_cfg = Config(str(Path(__file__).parent.parent.parent / "alembic.ini"))
    alembic_cfg.set_main_option("sqlalchemy.url", async_url)

    def run_upgrade():
        command.upgrade(alembic_cfg, "head")

    await asyncio.to_thread(run_upgrade)

    yield async_url

    await close_db()


@pytest.mark.skipif(
    not PostgresContainer, reason="testcontainers not available"
)
class TestDatabaseIntegration:
    """Integration tests requiring real PostgreSQL."""

    async def test_full_channel_lifecycle(self, db_setup):
        """Test create → update → get → count for channels."""
        async with get_session() as session:
            repo = ChannelRepository(session)

            # Create
            channel_data = ChannelCreate(
                name="Integration Test Channel",
                niche=Niche.TECH,
                channel_type=ChannelType.SPOKE,
                target_market=Market.US,
                google_cloud_project="test-project",
                api_key_ref="test-key",
            )
            channel = await repo.create(channel_data)
            assert channel.id is not None
            assert channel.name == "Integration Test Channel"

            # Get
            retrieved = await repo.get_by_id(channel.id)
            assert retrieved.name == "Integration Test Channel"

            # Update
            update_data = ChannelUpdate(status="active")
            updated = await repo.update(channel.id, update_data)
            assert updated.status == "active"

            # Count
            counts = await repo.count_by_status()
            assert "active" in counts
            assert counts["active"] >= 1

    async def test_full_video_lifecycle(self, db_setup):
        """Test create → update_status through pipeline → get for videos."""
        async with get_session() as session:
            # First create a channel
            channel_repo = ChannelRepository(session)
            channel_data = ChannelCreate(
                name="Video Test Channel",
                niche=Niche.PSYCHOLOGY,
                channel_type=ChannelType.HUB,
                target_market=Market.US,
                google_cloud_project="test-project",
                api_key_ref="test-key",
            )
            channel = await channel_repo.create(channel_data)

            # Create video
            video_repo = VideoRepository(session)
            video_data = VideoCreate(
                channel_id=channel.id,
                title="Test Video for Lifecycle",
                niche=Niche.PSYCHOLOGY,
                target_market=Market.US,
                topic_source=TopicSource.GOOGLE_TRENDS,
            )
            video = await video_repo.create(video_data)
            assert video.id is not None
            assert video.status == "queued"

            # Update status through pipeline
            video = await video_repo.update_status(video.id, "scripting")
            assert video.status == "scripting"

            video = await video_repo.update_status(video.id, "producing")
            assert video.status == "producing"

            # Get by channel
            videos = await video_repo.get_by_channel(channel.id)
            assert len(videos) >= 1
            assert videos[0].id == video.id

    async def test_concurrent_sessions(self, db_setup):
        """Test 2 sessions writing simultaneously → no conflict."""
        import asyncio

        async def create_channel(name: str):
            async with get_session() as session:
                repo = ChannelRepository(session)
                data = ChannelCreate(
                    name=name,
                    niche=Niche.FINANCE,
                    channel_type=ChannelType.SPOKE,
                    target_market=Market.US,
                    google_cloud_project="test-project",
                    api_key_ref="test-key",
                )
                return await repo.create(data)

        # Run two concurrent channel creations
        results = await asyncio.gather(
            create_channel("Concurrent Channel 1"),
            create_channel("Concurrent Channel 2"),
        )

        assert results[0].id != results[1].id
        assert results[0].name == "Concurrent Channel 1"
        assert results[1].name == "Concurrent Channel 2"