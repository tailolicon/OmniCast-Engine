# TASK E FIX: Configuration System — Rewrite Both Files

> **Severity:** CRITICAL — wrong fields, missing loader, duplicate BrandConfig
> **Files to rewrite:** `settings.py`, `brand.py`, `__init__.py`
> **File to update:** `tests/unit/test_config.py`
> **Estimated time:** 30 min

## Problem Summary

| File | Issue |
|------|-------|
| `settings.py` | Missing 15+ spec fields, wrong field names, missing validators, missing properties |
| `brand.py` | Completely wrong — has `BrandConfig` model instead of `BrandConfigLoader` class |
| `__init__.py` | Exports wrong things |
| `tests/unit/test_config.py` | Tests wrong interfaces |

**CRITICAL**: `brand.py` defines its own `BrandConfig` Pydantic model that conflicts with `schemas.py:BrandConfig`. The correct `BrandConfig` is already in `src/omnicast/models/schemas.py`. brand.py should ONLY contain `BrandConfigLoader`.

---

## 1. Rewrite `settings.py`

Delete current content. Replace with:

```python
"""Global application settings loaded from environment variables.

Usage:
    settings = get_settings()
    print(settings.database_url)
    print(settings.is_production)

Singleton pattern — load once, reuse everywhere.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


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

**Key differences from current:**
- `database_url` has NO default (required field)
- `rabbitmq_url` NOT `queue_url` (required field)
- Added: `claude_api_key`, `claude_model`, `claude_rpm_limit`, `youtube_quota_daily`
- Added: `omnicast_mode` with validator + `is_production`/`is_dry_run` properties
- Added: `nas_mount_path`, `nas_fallback_path`, `worker_id`, `heartbeat_interval`
- Added: `quiet_hours_start/end/timezone`, `daily_llm_budget_usd`
- Added: `reset_settings()` function
- Removed: `app_name`, `debug`, `log_level`, `log_format`, `db_pool_size`, `db_max_overflow`, `db_echo`, etc.

---

## 2. Rewrite `brand.py`

Delete EVERYTHING. Replace with `BrandConfigLoader` class. DO NOT define a new `BrandConfig` model — import from `omnicast.models.schemas`.

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

from __future__ import annotations

import asyncio
from pathlib import Path

import orjson
import structlog

from omnicast.models.schemas import BrandConfig
from omnicast.shared.errors import ConfigError

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
        3. If file not exists → raise ConfigError
        4. Read file with orjson.loads()
        5. Validate with BrandConfig.model_validate(data)
        6. Store in _cache
        7. Log and return
        """
        if channel_id in self._cache:
            return self._cache[channel_id]

        config_path = self.config_dir / f"{channel_id}.json"

        if not await asyncio.to_thread(config_path.exists):
            raise ConfigError(f"Brand config not found: {channel_id}")

        try:
            raw = await asyncio.to_thread(config_path.read_bytes)
            data = orjson.loads(raw)
        except Exception as exc:
            raise ConfigError(f"Failed to read brand config {channel_id}: {exc}") from exc

        config = BrandConfig.model_validate(data)
        self._cache[channel_id] = config
        logger.info("Loaded brand config", channel_id=channel_id)
        return config

    async def reload(self, channel_id: str) -> BrandConfig:
        """Force reload from disk (invalidate cache for this channel)."""
        if channel_id in self._cache:
            del self._cache[channel_id]
        return await self.load(channel_id)

    async def load_all(self) -> dict[str, BrandConfig]:
        """Load all brand configs from config_dir.

        Scan config_dir for *.json files.
        Load each one. Skip invalid files (log warning, continue).
        """
        result: dict[str, BrandConfig] = {}
        if not await asyncio.to_thread(self.config_dir.exists):
            logger.warning("Config directory not found", path=str(self.config_dir))
            return result

        json_files = await asyncio.to_thread(
            lambda: list(self.config_dir.glob("*.json"))
        )
        for path in json_files:
            channel_id = path.stem
            try:
                config = await self.load(channel_id)
                result[channel_id] = config
            except Exception as exc:
                logger.warning(
                    "Skipping invalid brand config",
                    channel_id=channel_id,
                    error=str(exc),
                )
        return result

    def get_cached(self, channel_id: str) -> BrandConfig | None:
        """Get from cache without disk access. Return None if not cached."""
        return self._cache.get(channel_id)

    async def validate_config(self, channel_id: str) -> list[str]:
        """Validate a brand config and return list of warnings.

        Checks:
        - intro_template path exists
        - outro_template path exists
        - color_palette has exactly 3 colors
        - music_bpm_range[0] < music_bpm_range[1]
        """
        config = await self.load(channel_id)
        warnings: list[str] = []

        if config.intro_template:
            intro_path = Path(config.intro_template)
            if not await asyncio.to_thread(intro_path.exists):
                warnings.append("intro_template path not found")

        if config.outro_template:
            outro_path = Path(config.outro_template)
            if not await asyncio.to_thread(outro_path.exists):
                warnings.append("outro_template path not found")

        if len(config.color_palette) != 3:
            warnings.append(f"color_palette has {len(config.color_palette)} colors, expected 3")

        if config.music_bpm_range[0] >= config.music_bpm_range[1]:
            warnings.append("music_bpm_range[0] must be < music_bpm_range[1]")

        return warnings

    async def save(self, channel_id: str, config: BrandConfig) -> None:
        """Save brand config to JSON file."""
        config_path = self.config_dir / f"{channel_id}.json"
        data = orjson.dumps(
            config.model_dump(), option=orjson.OPT_INDENT_2
        )
        await asyncio.to_thread(config_path.write_bytes, data)
        self._cache[channel_id] = config
        logger.info("Saved brand config", channel_id=channel_id)
```

---

## 3. Update `__init__.py`

```python
"""Configuration module for OmniCast Engine."""

from omnicast.config.settings import Settings, get_settings, reset_settings
from omnicast.config.brand import BrandConfigLoader

__all__ = [
    "Settings",
    "get_settings",
    "reset_settings",
    "BrandConfigLoader",
]
```

**DO NOT export `BrandConfig` from here** — it lives in `omnicast.models.schemas`.

---

## 4. Rewrite `tests/unit/test_config.py`

### Settings Tests

```python
"""Test configuration loading."""

import pytest
from pydantic import ValidationError

from omnicast.config.settings import Settings, get_settings, reset_settings


class TestSettings:
    def setup_method(self):
        reset_settings()

    def test_settings_from_env(self, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/testdb")
        monkeypatch.setenv("RABBITMQ_URL", "amqp://guest:guest@localhost/")
        monkeypatch.setenv("OMNICAST_MODE", "staging")
        reset_settings()
        settings = get_settings()
        assert settings.database_url == "postgresql+asyncpg://test:test@localhost/testdb"
        assert settings.rabbitmq_url == "amqp://guest:guest@localhost/"
        assert settings.omnicast_mode == "staging"

    def test_settings_defaults(self, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://x@localhost/db")
        monkeypatch.setenv("RABBITMQ_URL", "amqp://localhost/")
        reset_settings()
        settings = get_settings()
        assert settings.redis_url == "redis://localhost:6379/0"
        assert settings.omnicast_mode == "dry_run"
        assert settings.claude_model == "claude-sonnet-4-6"
        assert settings.daily_llm_budget_usd == 10.0

    def test_settings_invalid_mode(self, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://x@localhost/db")
        monkeypatch.setenv("RABBITMQ_URL", "amqp://localhost/")
        monkeypatch.setenv("OMNICAST_MODE", "invalid")
        reset_settings()
        with pytest.raises(ValidationError):
            get_settings()

    def test_settings_is_production(self, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://x@localhost/db")
        monkeypatch.setenv("RABBITMQ_URL", "amqp://localhost/")
        monkeypatch.setenv("OMNICAST_MODE", "production")
        reset_settings()
        settings = get_settings()
        assert settings.is_production is True
        assert settings.is_dry_run is False

    def test_settings_singleton(self, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://x@localhost/db")
        monkeypatch.setenv("RABBITMQ_URL", "amqp://localhost/")
        reset_settings()
        s1 = get_settings()
        s2 = get_settings()
        assert s1 is s2

    def test_settings_invalid_database_url(self, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", "mysql://x@localhost/db")
        monkeypatch.setenv("RABBITMQ_URL", "amqp://localhost/")
        reset_settings()
        with pytest.raises(ValidationError):
            get_settings()
```

### BrandConfigLoader Tests

```python
import orjson
from omnicast.config.brand import BrandConfigLoader
from omnicast.shared.errors import ConfigError


class TestBrandConfigLoader:
    @pytest.fixture
    def sample_brand_data(self) -> dict:
        """Valid BrandConfig data matching schemas.py:BrandConfig."""
        return {
            "channel_id": "hub_finance_us",
            "voice_profile": "kokoro_en_us_v1",
            "color_palette": ["#1A1A2E", "#E94560", "#FFFFFF"],
            "font": "Montserrat Bold",
            "transition_style": "zoom_in_0.3s",
            "music_bpm_range": [120, 140],
            "script_template": "standard",
            "max_segment_duration": 60,
            "target_duration_min": 10,
            "thumbnail_style": "dark_contrast",
            "image_gen_mode": "sdxl",
            "use_video_gen": False,
        }

    @pytest.fixture
    def brand_dir(self, tmp_path, sample_brand_data) -> Path:
        """Create temp dir with one valid brand config."""
        path = tmp_path / "brand_configs"
        path.mkdir()
        (path / "hub_finance_us.json").write_bytes(
            orjson.dumps(sample_brand_data)
        )
        return path

    async def test_load_valid_config(self, brand_dir):
        loader = BrandConfigLoader(brand_dir)
        config = await loader.load("hub_finance_us")
        assert config.channel_id == "hub_finance_us"
        assert config.voice_profile == "kokoro_en_us_v1"

    async def test_load_not_found(self, brand_dir):
        loader = BrandConfigLoader(brand_dir)
        with pytest.raises(ConfigError, match="not found"):
            await loader.load("nonexistent")

    async def test_load_invalid_json(self, tmp_path):
        config_dir = tmp_path / "configs"
        config_dir.mkdir()
        (config_dir / "bad.json").write_text("not json {{{")
        loader = BrandConfigLoader(config_dir)
        with pytest.raises(ConfigError):
            await loader.load("bad")

    async def test_cache_hit(self, brand_dir, sample_brand_data):
        loader = BrandConfigLoader(brand_dir)
        config1 = await loader.load("hub_finance_us")
        # Modify file on disk
        sample_brand_data["voice_profile"] = "changed_voice"
        (brand_dir / "hub_finance_us.json").write_bytes(
            orjson.dumps(sample_brand_data)
        )
        config2 = await loader.load("hub_finance_us")
        # Should return cached version (not re-read)
        assert config2.voice_profile == "kokoro_en_us_v1"

    async def test_reload_bypasses_cache(self, brand_dir, sample_brand_data):
        loader = BrandConfigLoader(brand_dir)
        await loader.load("hub_finance_us")
        # Modify file
        sample_brand_data["voice_profile"] = "new_voice"
        (brand_dir / "hub_finance_us.json").write_bytes(
            orjson.dumps(sample_brand_data)
        )
        config = await loader.reload("hub_finance_us")
        assert config.voice_profile == "new_voice"

    async def test_load_all(self, brand_dir, sample_brand_data):
        # Add second config
        data2 = {**sample_brand_data, "channel_id": "hub_tech_uk"}
        (brand_dir / "hub_tech_uk.json").write_bytes(orjson.dumps(data2))
        loader = BrandConfigLoader(brand_dir)
        all_configs = await loader.load_all()
        assert len(all_configs) == 2
        assert "hub_finance_us" in all_configs
        assert "hub_tech_uk" in all_configs

    async def test_get_cached_returns_none_if_not_loaded(self, brand_dir):
        loader = BrandConfigLoader(brand_dir)
        assert loader.get_cached("hub_finance_us") is None

    async def test_save_and_reload(self, brand_dir):
        from omnicast.models.schemas import BrandConfig
        loader = BrandConfigLoader(brand_dir)
        config = BrandConfig(
            channel_id="new_channel",
            voice_profile="test_voice",
        )
        await loader.save("new_channel", config)
        reloaded = await loader.reload("new_channel")
        assert reloaded.channel_id == "new_channel"
        assert reloaded.voice_profile == "test_voice"

    async def test_validate_config_missing_intro(self, brand_dir, sample_brand_data):
        sample_brand_data["intro_template"] = "/nonexistent/path/intro.mp4"
        (brand_dir / "hub_finance_us.json").write_bytes(
            orjson.dumps(sample_brand_data)
        )
        loader = BrandConfigLoader(brand_dir)
        loader._cache.clear()
        warnings = await loader.validate_config("hub_finance_us")
        assert any("intro_template" in w for w in warnings)
```

---

## Verify

```bash
uv run pytest tests/unit/test_config.py -v
uv run pyright src/omnicast/config/
```

## DO NOT

- Do NOT create a new `BrandConfig` model — use existing one from `omnicast.models.schemas`
- Do NOT add `extra="ignore"` to Settings — let unknown env vars cause validation errors
- Do NOT use sync file I/O in brand.py — use `asyncio.to_thread()` for all Path operations
- Do NOT hardcode settings — all from env vars
- Do NOT keep old fields (app_name, debug, log_level, etc.) unless adding them to spec
- Do NOT touch `omnicast/models/schemas.py`
