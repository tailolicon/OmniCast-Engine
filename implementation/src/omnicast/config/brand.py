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