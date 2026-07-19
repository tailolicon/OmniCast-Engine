# TASK B: Database Layer (PostgreSQL + Alembic)

> **Depends on:** TASK_A hoàn thành (models/, shared/ đã tồn tại)
> **Output:** src/omnicast/db/, alembic/, tests/unit/test_repositories.py, tests/integration/test_db_integration.py
> **Parallel với:** TASK_C, D, E, F, G

## Context

OmniCast Engine dùng PostgreSQL 16 làm SQL database chính. Module này cung cấp:
1. Async connection pool (asyncpg)
2. Alembic migrations
3. Repository pattern cho CRUD operations

Module KHÔNG chứa business logic. Chỉ data access.

## Files cần tạo

```
src/omnicast/db/
├── __init__.py          # Export public API
├── engine.py            # AsyncEngine + session factory
└── repositories.py      # Repository classes (CRUD)

alembic/
├── env.py               # Alembic config
└── versions/
    └── 001_initial_schema.py

alembic.ini              # Alembic settings

tests/
├── unit/test_repositories.py
└── integration/test_db_integration.py
```

## 1. engine.py — Connection Management

```python
"""Async PostgreSQL engine + session factory.

Usage:
    engine = create_engine("postgresql+asyncpg://...")
    async with get_session() as session:
        result = await session.execute(select(ChannelORM))
"""

from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator
from sqlalchemy.ext.asyncio import (
    AsyncSession, AsyncEngine,
    create_async_engine, async_sessionmaker,
)
import structlog

logger = structlog.get_logger()

# Singleton engine — initialized once via init_db()
_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None
```

### Functions to implement

```python
def init_db(database_url: str, pool_size: int = 5, max_overflow: int = 10) -> None:
    """Initialize global engine + session factory. Call once at startup.
    
    Args:
        database_url: PostgreSQL connection string (postgresql+asyncpg://...)
        pool_size: Base connection pool size
        max_overflow: Max additional connections
    
    Raises:
        ConfigError: if database_url is empty or invalid format
    
    Implementation notes:
        - Store in module-level _engine, _session_factory
        - Set echo=False (production), pool_pre_ping=True (detect stale connections)
        - Log: "Database engine initialized" with pool_size
    """

def get_engine() -> AsyncEngine:
    """Return initialized engine. Raises ConfigError if init_db() not called."""

@asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield an async session. Auto-commit on success, rollback on exception.
    
    Usage:
        async with get_session() as session:
            channel = await session.get(ChannelORM, 1)
    
    Implementation notes:
        - Use _session_factory() to create session
        - try/yield/commit on success
        - except → rollback → re-raise
        - finally → close
        - Raises ConfigError if _session_factory is None
    """

async def close_db() -> None:
    """Dispose engine. Call at shutdown."""
```

## 2. repositories.py — CRUD Operations

Pattern: một Repository class per ORM model. Mỗi class nhận `AsyncSession` qua constructor.

### ChannelRepository

```python
class ChannelRepository:
    """CRUD for channels table."""
    
    def __init__(self, session: AsyncSession):
        self.session = session
    
    async def create(self, data: ChannelCreate) -> ChannelORM:
        """Insert new channel. Return ORM instance with generated id.
        
        - Chuyển ChannelCreate → ChannelORM bằng data.model_dump()
        - session.add() + session.flush() (để có id ngay, commit ở session context)
        - Return ORM object
        """
    
    async def get_by_id(self, channel_id: int) -> ChannelORM:
        """Get channel by id. Raise NotFoundError if not exists."""
    
    async def get_all(
        self,
        status: str | None = None,
        niche: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ChannelORM]:
        """Get channels with optional filters. Order by created_at DESC."""
    
    async def update(self, channel_id: int, data: ChannelUpdate) -> ChannelORM:
        """Update channel fields. Only update non-None fields from ChannelUpdate.
        
        - Lấy channel bằng get_by_id (raise NotFoundError nếu không có)
        - Loop qua data.model_dump(exclude_none=True)
        - setattr(channel, key, value)
        - flush + return updated ORM
        """
    
    async def count_by_status(self) -> dict[str, int]:
        """Return {status: count} for all statuses. Dùng GROUP BY."""
```

### VideoRepository

```python
class VideoRepository:
    """CRUD for videos table."""
    
    def __init__(self, session: AsyncSession):
        self.session = session
    
    async def create(self, data: VideoCreate) -> VideoORM:
        """Insert new video. Return ORM with id."""
    
    async def get_by_id(self, video_id: int) -> VideoORM:
        """Get video by id. Raise NotFoundError if not exists."""
    
    async def get_by_channel(
        self,
        channel_id: int,
        status: str | None = None,
        limit: int = 50,
    ) -> list[VideoORM]:
        """Get videos for channel, optional status filter. Order by created_at DESC."""
    
    async def update(self, video_id: int, data: VideoUpdate) -> VideoORM:
        """Partial update. Only non-None fields."""
    
    async def update_status(self, video_id: int, new_status: str) -> VideoORM:
        """Shortcut: update only status field. Log state transition."""
    
    async def get_pipeline_counts(self) -> dict[str, int]:
        """Return {status: count} for pipeline overview dashboard."""
    
    async def get_recent(self, limit: int = 20) -> list[VideoORM]:
        """Get most recent videos across all channels."""
```

### AlertRepository

```python
class AlertRepository:
    def __init__(self, session: AsyncSession):
        self.session = session
    
    async def create(self, data: AlertCreate, fingerprint: str) -> AlertORM:
        """Insert new alert with computed fingerprint."""
    
    async def get_unresolved(
        self,
        severity: str | None = None,
        limit: int = 50,
    ) -> list[AlertORM]:
        """Get unresolved alerts. Order by severity DESC, created_at DESC."""
    
    async def resolve(self, alert_id: int) -> AlertORM:
        """Mark alert as resolved. Set resolved_at = now()."""
    
    async def increment_suppressed(self, fingerprint: str) -> None:
        """Increment suppressed_count for alert with given fingerprint.
        Dùng khi alert trùng lặp bị deduplicate."""
    
    async def get_by_fingerprint(self, fingerprint: str) -> AlertORM | None:
        """Find active (unresolved) alert by fingerprint. Return None if not found."""
```

### AssetRepository

```python
class AssetRepository:
    def __init__(self, session: AsyncSession):
        self.session = session
    
    async def create(self, data: AssetCreate) -> AssetORM:
        """Insert new asset."""
    
    async def search(
        self,
        asset_type: str,
        mood: str | None = None,
        limit: int = 10,
    ) -> list[AssetORM]:
        """Search assets. ORDER BY use_count ASC (ít dùng ưu tiên)."""
    
    async def increment_use(self, asset_id: int) -> None:
        """Increment use_count by 1."""
    
    async def get_by_md5(self, md5_hash: str) -> AssetORM | None:
        """Find asset by MD5 hash. For dedup check."""
    
    async def count_by_type_mood(self) -> list[dict]:
        """Return [{asset_type, mood, count}] for stock level dashboard."""
```

### LessonRepository, ExpenseRepository, ChannelStrikeRepository

```python
# Implement tương tự pattern trên:
# - create(data) → ORM
# - get_by_id(id) → ORM | raise NotFoundError
# - get_all(filters) → list[ORM]
# - update(id, data) → ORM

# LessonRepository thêm:
#   async def get_active_for_agent(agent_name: str) → list[LessonORM]
#   async def deactivate(lesson_id: int) → None

# ExpenseRepository thêm:
#   async def get_by_period(start: date, end: date) → list[ExpenseORM]
#   async def sum_by_category(start: date, end: date) → dict[str, float]

# ChannelStrikeRepository thêm:
#   async def get_active_strikes(channel_id: int) → list[ChannelStrikeORM]
#     (active = expires_date is None OR expires_date > today)
#   async def count_active(channel_id: int) → int
```

## 3. Alembic Setup

### alembic.ini

```ini
[alembic]
script_location = alembic
sqlalchemy.url = postgresql+asyncpg://omnicast:dev_password@localhost:5432/omnicast

[loggers]
keys = root,sqlalchemy,alembic

[handlers]
keys = console

[formatters]
keys = generic

[logger_root]
level = WARN
handlers = console

[logger_sqlalchemy]
level = WARN
handlers =
qualname = sqlalchemy.engine

[logger_alembic]
level = INFO
handlers =
qualname = alembic

[handler_console]
class = StreamHandler
args = (sys.stderr,)
level = NOTSET
formatter = generic

[formatter_generic]
format = %(levelname)-5.5s [%(name)s] %(message)s
```

### alembic/env.py

```python
"""Alembic migration environment.

Key points:
- Import Base from omnicast.models.orm (target_metadata = Base.metadata)
- Use async engine (run_async_migrations)
- Read DATABASE_URL from environment variable
"""
# Implement standard async Alembic env.py
# Reference: https://alembic.sqlalchemy.org/en/latest/cookbook.html#using-asyncio-with-alembic
```

### alembic/versions/001_initial_schema.py

```python
"""Initial schema — all tables from orm.py

Auto-generate via: alembic revision --autogenerate -m "initial schema"
Verify tables created:
  channels, channel_metrics, videos, video_metrics,
  assets, alerts, lessons, prompt_versions, expenses, channel_strikes

CHECK: all indexes from orm.py __table_args__ are included.
"""
```

## 4. Tests

### tests/unit/test_repositories.py

```python
"""Unit tests for repositories using mock sessions.

Test mỗi repository method:
- Happy path: create → get → update → verify
- Error: get non-existent id → NotFoundError
- Filters: get_all with status filter → correct subset

Dùng AsyncMock cho session.
"""

# Test cases bắt buộc:
# test_channel_create_and_get
# test_channel_not_found_raises
# test_channel_update_partial
# test_channel_count_by_status
# test_video_create_and_get
# test_video_update_status
# test_video_pipeline_counts
# test_alert_create_and_resolve
# test_alert_dedup_fingerprint
# test_asset_search_order_by_use_count
# test_asset_increment_use
# test_lesson_get_active_for_agent
```

### tests/integration/test_db_integration.py

```python
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
```

## 5. DO NOT

- ❌ Đừng dùng synchronous SQLAlchemy — tất cả async
- ❌ Đừng commit trong repository methods — commit ở session context manager (engine.py)
- ❌ Đừng return None khi không tìm thấy — raise NotFoundError
- ❌ Đừng viết raw SQL — dùng SQLAlchemy ORM queries
- ❌ Đừng tạo engine mới mỗi request — dùng singleton via init_db()
- ❌ Đừng import models từ đường dẫn khác — dùng `from omnicast.models.orm import ...`

## 6. Acceptance Criteria

```bash
# Unit tests pass
uv run pytest tests/unit/test_repositories.py -v

# Integration tests pass (cần Docker)
docker compose up -d postgres
uv run pytest tests/integration/test_db_integration.py -v

# Alembic migration works
uv run alembic upgrade head
uv run alembic downgrade base
uv run alembic upgrade head

# Type check
uv run pyright src/omnicast/db/
```
