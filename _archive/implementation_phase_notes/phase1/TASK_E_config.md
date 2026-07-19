# TASK E: Configuration System

> **Depends on:** TASK_A hoàn thành (models/schemas.py có BrandConfig, shared/errors.py có ConfigError)
> **Output:** src/omnicast/config/, .env.example, tests/unit/test_config.py
> **Parallel với:** TASK_B, C, D, F, G

## Context

Configuration hai tầng:
1. **Settings** — env vars: database URLs, API keys, feature flags. Dùng pydantic-settings.
2. **Brand Config** — per-channel JSON: voice, colors, templates. Load từ NAS.

## Files cần tạo

```
src/omnicast/config/
├── __init__.py
├── settings.py       # Global settings from env vars
└── brand.py          # Brand config loader (per channel)
```

## 1. settings.py

```python
"""Global application settings loaded from environment variables.

Usage:
    settings = get_settings()
    print(settings.database_url)
    print(settings.is_production)

Singleton pattern — load once, reuse everywhere.
"""

from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, field_validator

class Settings(BaseSettings):
    """All settings from .env file or environment variables."""
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )
    
    # === Database ===
    database_url: str = Field(description="PostgreSQL connection string")
    
    # === RabbitMQ ===
    rabbitmq_url: str = Field(description="AMQP connection string")
    
    # === Redis ===
    redis_url: str = Field(default="redis://localhost:6379/0")
    
    # === Telegram ===
    telegram_bot_token: str = Field(default="")
    telegram_chat_id: str = Field(default="")
    
    # === Claude API ===
    claude_api_key: str = Field(default="")
    claude_model: str = Field(default="claude-sonnet-4-6")
    claude_rpm_limit: int = Field(default=50, description="Requests per minute")
    
    # === YouTube ===
    youtube_quota_daily: int = Field(default=10000, description="Units per day per project")
    
    # === Mode ===
    omnicast_mode: str = Field(default="dry_run", description="production | dry_run | staging")
    
    # === NAS ===
    nas_mount_path: str = Field(default="/Volumes/NAS")
    nas_fallback_path: str = Field(default="/tmp/omnicast_local")
    
    # === Worker ===
    worker_id: str = Field(default="master", description="Unique worker identifier")
    heartbeat_interval: int = Field(default=30, description="Seconds between heartbeats")
    
    # === Alerts ===
    quiet_hours_start: str = Field(default="23:00")
    quiet_hours_end: str = Field(default="07:00")
    quiet_hours_timezone: str = Field(default="Asia/Ho_Chi_Minh")
    
    # === Budget ===
    daily_llm_budget_usd: float = Field(default=10.0, description="Max daily LLM spend")
    
    # === Computed properties ===
    @property
    def is_production(self) -> bool:
        return self.omnicast_mode == "production"
    
    @property
    def is_dry_run(self) -> bool:
        return self.omnicast_mode == "dry_run"
    
    # === Validators ===
    @field_validator("omnicast_mode")
    @classmethod
    def validate_mode(cls, v: str) -> str:
        allowed = {"production", "dry_run", "staging"}
        if v not in allowed:
            raise ValueError(f"omnicast_mode must be one of {allowed}, got '{v}'")
        return v
    
    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, v: str) -> str:
        if not v.startswith("postgresql"):
            raise ValueError("database_url must start with 'postgresql'")
        return v

@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached Settings singleton.
    
    First call loads from .env / environment.
    Subsequent calls return cached instance.
    """
    return Settings()

def reset_settings() -> None:
    """Clear settings cache. For testing only."""
    get_settings.cache_clear()
```

## 2. brand.py

```python
"""Brand configuration loader.

Each channel has a brand_config.json on NAS.
Loaded at production start, cached in memory.

Usage:
    loader = BrandConfigLoader(nas_path="/Volumes/NAS/assets/brand_configs")
    config = await loader.load("hub_finance_us")
    print(config.voice_profile)  # "kokoro_en_us_v1"
    
    # Reload (after editing JSON on NAS):
    config = await loader.reload("hub_finance_us")
"""

import orjson
from pathlib import Path
from omnicast.models.schemas import BrandConfig
from omnicast.shared.errors import ConfigError
import structlog

logger = structlog.get_logger()

class BrandConfigLoader:
    """Load and cache brand configs from JSON files.
    
    Args:
        config_dir: path to directory containing {channel_id}.json files
    """
    
    def __init__(self, config_dir: str | Path):
        self.config_dir = Path(config_dir)
        self._cache: dict[str, BrandConfig] = {}
    
    async def load(self, channel_id: str) -> BrandConfig:
        """Load brand config for channel. Return from cache if available.
        
        Steps:
        1. Check _cache → return if exists
        2. Build path: config_dir / f"{channel_id}.json"
        3. If file not exists → raise ConfigError(f"Brand config not found: {channel_id}")
        4. Read file with orjson.loads()
        5. Validate with BrandConfig.model_validate(data)
        6. Store in _cache
        7. Log: "Loaded brand config for {channel_id}"
        8. Return BrandConfig
        
        NOTE: File I/O should use asyncio.to_thread() or aiofiles
              to avoid blocking the event loop.
        """
    
    async def reload(self, channel_id: str) -> BrandConfig:
        """Force reload from disk (invalidate cache for this channel)."""
        if channel_id in self._cache:
            del self._cache[channel_id]
        return await self.load(channel_id)
    
    async def load_all(self) -> dict[str, BrandConfig]:
        """Load all brand configs from config_dir.
        
        Scan config_dir for *.json files.
        Load each one. Skip invalid files (log warning, continue).
        Return {channel_id: BrandConfig}.
        """
    
    def get_cached(self, channel_id: str) -> BrandConfig | None:
        """Get from cache without disk access. Return None if not cached."""
        return self._cache.get(channel_id)
    
    async def validate_config(self, channel_id: str) -> list[str]:
        """Validate a brand config and return list of warnings.
        
        Checks:
        - intro_template path exists
        - outro_template path exists
        - voice_profile is a known Kokoro voice
        - color_palette has exactly 3 colors
        - music_bpm_range[0] < music_bpm_range[1]
        
        Return empty list if all OK.
        """
    
    async def save(self, channel_id: str, config: BrandConfig) -> None:
        """Save brand config to JSON file.
        
        - Serialize with orjson.dumps(config.model_dump(), option=orjson.OPT_INDENT_2)
        - Write to config_dir / f"{channel_id}.json"
        - Update cache
        """
```

## 3. Tests

### tests/unit/test_config.py

```python
"""Test configuration loading.

=== Settings Tests ===

test_settings_from_env(monkeypatch):
    - Set env vars: DATABASE_URL, RABBITMQ_URL, OMNICAST_MODE
    - reset_settings()
    - settings = get_settings()
    - Verify values match env vars

test_settings_defaults():
    - Set only required env vars (DATABASE_URL, RABBITMQ_URL)
    - Verify defaults: redis_url="redis://localhost:6379/0", omnicast_mode="dry_run"

test_settings_invalid_mode(monkeypatch):
    - Set OMNICAST_MODE="invalid"
    - get_settings() → raises ValidationError

test_settings_is_production(monkeypatch):
    - Set OMNICAST_MODE="production"
    - settings.is_production → True
    - settings.is_dry_run → False

test_settings_singleton():
    - get_settings() twice → same object (lru_cache)

test_settings_invalid_database_url(monkeypatch):
    - Set DATABASE_URL="mysql://..."
    - get_settings() → raises ValidationError

=== BrandConfigLoader Tests ===

test_load_valid_config(tmp_path):
    - Create tmp_path / "test_channel.json" with valid JSON
    - loader = BrandConfigLoader(tmp_path)
    - config = await loader.load("test_channel")
    - Verify: config.channel_id == "test_channel"

test_load_not_found(tmp_path):
    - loader = BrandConfigLoader(tmp_path)
    - await loader.load("nonexistent") → raises ConfigError

test_load_invalid_json(tmp_path):
    - Create file with invalid JSON
    - await loader.load("bad") → raises ConfigError or ValidationError

test_cache_hit(tmp_path):
    - Load once → modify file on disk → load again
    - Second load returns cached version (not re-read)

test_reload_bypasses_cache(tmp_path):
    - Load once → modify file → reload
    - Returns new version from disk

test_load_all(tmp_path):
    - Create 3 JSON files
    - load_all() → dict with 3 entries

test_validate_config_missing_intro(tmp_path):
    - Config with intro_template pointing to nonexistent file
    - validate_config() → returns ["intro_template path not found"]

test_save_and_reload(tmp_path):
    - Create BrandConfig
    - save("new_channel", config)
    - File exists on disk
    - reload("new_channel") → matches saved config
"""
```

## 4. DO NOT

- ❌ Đừng hardcode settings — tất cả từ env vars
- ❌ Đừng dùng os.environ trực tiếp — dùng pydantic-settings
- ❌ Đừng load brand config synchronously — dùng asyncio.to_thread hoặc aiofiles
- ❌ Đừng store secrets trong brand config JSON — secrets ở .env, brand config chỉ có non-sensitive data
- ❌ Đừng mutate BrandConfig — frozen model, tạo mới nếu cần thay đổi
- ❌ Đừng catch generic exceptions khi load JSON — để ValidationError propagate

## 5. Acceptance Criteria

```bash
# Create .env from example
cp .env.example .env

# Tests pass
uv run pytest tests/unit/test_config.py -v

# Settings load correctly
uv run python -c "
from omnicast.config.settings import get_settings
s = get_settings()
print(f'Mode: {s.omnicast_mode}')
print(f'Production: {s.is_production}')
"

# Type check
uv run pyright src/omnicast/config/
```
