# Phase 1: Core Infrastructure — Implementation Guide

> **AI Workflow:** Đọc `E:\Project\OmniCast Engine\AI_WORKFLOW.md` trước khi bắt đầu.

## Mục tiêu
Xây dựng nền tảng Python cho OmniCast Engine: database, queue, cache, config, storage, alerts.
Tất cả Phase 2+ (agents, media pipeline, upload) sẽ import từ các module Phase 1.

## Dependency Graph

```
TASK_A (Project Setup + Models) ← PHẢI HOÀN THÀNH TRƯỚC
    ↓
TASK_B (Database)     ─┐
TASK_C (Queue)         │
TASK_D (Cache/Redis)   ├── TẤT CẢ CHẠY SONG SONG
TASK_E (Config)        │
TASK_F (Storage/NAS)   │
TASK_G (Telegram Bot) ─┘
```

**TASK_A xong trước → giao B-G cho 6 model chạy đồng thời.**

## Conventions (MỌI task đều tuân theo)

### Python
- Python 3.12+
- Package manager: `uv`
- Formatter: `ruff format`
- Linter: `ruff check`
- Type checker: `pyright`
- Test: `pytest` + `pytest-asyncio`

### Code Style
- Async-first: tất cả I/O operations dùng `async/await`
- Pydantic v2 cho validation + serialization
- SQLAlchemy 2.0 ORM (mapped_column style)
- Type hints bắt buộc trên MỌI function/method
- Immutable: dùng frozen Pydantic models, không mutate
- Errors: raise custom exceptions (từ `shared/errors.py`), KHÔNG return None
- Logging: `structlog` (structured JSON logs)

### Import Convention
```python
# Internal imports luôn absolute
from omnicast.models.enums import VideoStatus
from omnicast.models.schemas import VideoCreate
from omnicast.models.orm import VideoORM
from omnicast.shared.errors import OmnicastError
```

### File Size
- Max 400 dòng/file. Nếu quá → tách module.
- Max 50 dòng/function.

### Test Convention
- File test: `tests/unit/test_{module}.py`
- Mỗi public method có ít nhất 2 test cases (happy path + error case)
- Dùng `pytest.fixture` cho setup
- Integration tests dùng Docker containers (testcontainers-python)

## Project Structure (sau khi hoàn thành Phase 1)

```
omnicast-engine/
├── pyproject.toml
├── alembic.ini
├── alembic/
│   ├── env.py
│   └── versions/
│       └── 001_initial_schema.py
├── src/
│   └── omnicast/
│       ├── __init__.py
│       ├── models/                  ← TASK_A
│       │   ├── __init__.py
│       │   ├── enums.py
│       │   ├── schemas.py
│       │   └── orm.py
│       ├── shared/                  ← TASK_A
│       │   ├── __init__.py
│       │   └── errors.py
│       ├── db/                      ← TASK_B
│       │   ├── __init__.py
│       │   ├── engine.py
│       │   └── repositories.py
│       ├── queue/                   ← TASK_C
│       │   ├── __init__.py
│       │   ├── connection.py
│       │   ├── publisher.py
│       │   └── consumer.py
│       ├── cache/                   ← TASK_D
│       │   ├── __init__.py
│       │   ├── connection.py
│       │   ├── rate_limiter.py
│       │   ├── distributed_lock.py
│       │   └── circuit_breaker.py
│       ├── config/                  ← TASK_E
│       │   ├── __init__.py
│       │   ├── settings.py
│       │   └── brand.py
│       ├── storage/                 ← TASK_F
│       │   ├── __init__.py
│       │   └── manager.py
│       └── telegram/                ← TASK_G
│           ├── __init__.py
│           ├── bot.py
│           └── alert_manager.py
├── tests/
│   ├── conftest.py
│   ├── unit/
│   │   ├── test_models.py           ← TASK_A
│   │   ├── test_repositories.py     ← TASK_B
│   │   ├── test_queue.py            ← TASK_C
│   │   ├── test_cache.py            ← TASK_D
│   │   ├── test_config.py           ← TASK_E
│   │   ├── test_storage.py          ← TASK_F
│   │   └── test_telegram.py         ← TASK_G
│   └── integration/
│       ├── test_db_integration.py    ← TASK_B
│       └── test_queue_integration.py ← TASK_C
├── docker-compose.yml               ← TASK_A (chỉ dev services)
└── .env.example                      ← TASK_E
```

## Verification Checklist (sau khi tất cả task xong)

```bash
# 1. Lint + Type check
uv run ruff check src/
uv run pyright src/

# 2. Unit tests
uv run pytest tests/unit/ -v

# 3. Integration tests (cần Docker)
docker compose up -d
uv run pytest tests/integration/ -v
docker compose down

# 4. Import verification (tất cả module import được)
uv run python -c "
from omnicast.models.enums import *
from omnicast.models.schemas import *
from omnicast.models.orm import *
from omnicast.db.engine import *
from omnicast.db.repositories import *
from omnicast.queue.connection import *
from omnicast.queue.publisher import *
from omnicast.queue.consumer import *
from omnicast.cache.connection import *
from omnicast.cache.rate_limiter import *
from omnicast.cache.distributed_lock import *
from omnicast.cache.circuit_breaker import *
from omnicast.config.settings import *
from omnicast.config.brand import *
from omnicast.storage.manager import *
from omnicast.telegram.bot import *
from omnicast.telegram.alert_manager import *
print('ALL IMPORTS OK')
"
```
