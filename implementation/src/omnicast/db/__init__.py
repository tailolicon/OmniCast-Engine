"""OmniCast Database Layer.

Public API for database initialization, session management, and repositories.

Usage:
    from omnicast.db import init_db, get_session, ChannelRepository

    init_db("postgresql+asyncpg://...")
    async with get_session() as session:
        repo = ChannelRepository(session)
        channels = await repo.get_all()
"""

from omnicast.db.engine import init_db, get_engine, get_session, close_db
from omnicast.db.repositories import (
    ChannelRepository,
    VideoRepository,
    AlertRepository,
    AssetRepository,
    LessonRepository,
    ExpenseRepository,
    ChannelStrikeRepository,
)

__all__ = [
    # Engine
    "init_db",
    "get_engine",
    "get_session",
    "close_db",
    # Repositories
    "ChannelRepository",
    "VideoRepository",
    "AlertRepository",
    "AssetRepository",
    "LessonRepository",
    "ExpenseRepository",
    "ChannelStrikeRepository",
]