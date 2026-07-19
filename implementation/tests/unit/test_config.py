"""Test configuration loading."""

from pathlib import Path

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
        monkeypatch.setenv("OMNICAST_MODE", "dry_run")  # explicit — .env may override
        reset_settings()
        settings = get_settings()
        assert settings.redis_url == "redis://localhost:6379/0"
        assert settings.omnicast_mode == "dry_run"
        assert settings.claude_model == "claude-sonnet-5"
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
