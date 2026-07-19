# TASK_H: Asset Manager + Character Registry

## Model: sonnet | Dependencies: TASK_A complete, Phase 1 AssetRepository

Service layer over Phase 1 AssetRepository. Handles search-with-rotation, registration, dedup, character persistence, and stock monitoring.

## Interface

### src/omnicast/media/asset_manager.py

```python
"""Asset Manager. Query/register/rotate assets. Character registry for face consistency."""

from __future__ import annotations
import hashlib
from pathlib import Path
from datetime import datetime, timezone
import structlog
from omnicast.models.schemas import AssetCreate, AssetRead, OmnicastSchema, BrandConfig
from omnicast.models.enums import AssetType, MusicMood
from omnicast.shared.errors import MediaError
from pydantic import Field

logger = structlog.get_logger()


class CharacterProfile(OmnicastSchema):
    """Persistent character identity for face consistency across videos."""
    name: str
    reference_image: str
    lora_path: str | None = None
    ip_adapter_weight: float = Field(default=0.6, ge=0.0, le=1.0)
    description: str = ""
    tags: list[str] = Field(default_factory=list)


class CharacterRegistry(OmnicastSchema):
    """Per-channel character registry. Loaded from JSON file."""
    channel_id: str
    characters: dict[str, CharacterProfile] = Field(default_factory=dict)

    def get(self, name: str) -> CharacterProfile | None:
        return self.characters.get(name)

    def add(self, profile: CharacterProfile) -> None:
        """Add character. Raises if name exists."""
        if profile.name in self.characters:
            raise MediaError(f"Character already exists: {profile.name}")
        # model_copy to maintain immutability pattern
        ...

    def list_names(self) -> list[str]:
        return list(self.characters.keys())


class StockLevel(OmnicastSchema):
    """Stock status for one asset type + mood combination."""
    asset_type: AssetType
    mood: MusicMood | None = None
    count: int = 0
    avg_use_count: float = 0.0
    needs_replenish: bool = False


class AssetManager:
    """Service layer over AssetRepository. Adds rotation, dedup, character registry."""

    def __init__(self, session_factory, nas_base_path: str = "/Volumes/NAS") -> None:
        self.session_factory = session_factory
        self.nas_base_path = nas_base_path

    async def search_music(
        self,
        mood: MusicMood | None = None,
        bpm_range: tuple[int, int] | None = None,
        duration_min: float | None = None,
        limit: int = 5,
    ) -> list[AssetRead]:
        """Search music assets. ORDER BY use_count ASC (rotation).
        Filter by mood, bpm_range, minimum duration."""
        ...

    async def search_broll(
        self,
        tags: list[str],
        duration_needed: float | None = None,
        limit: int = 10,
    ) -> list[AssetRead]:
        """Semantic search B-roll by tags. ORDER BY use_count ASC."""
        ...

    async def search_template(
        self,
        template_type: str,  # "intro" | "outro" | "overlay"
        channel_id: str | None = None,
        limit: int = 3,
    ) -> list[AssetRead]:
        """Search intro/outro/overlay templates. Channel-specific first, then global."""
        ...

    async def register_asset(
        self,
        path: str,
        asset_type: AssetType,
        mood: MusicMood | None = None,
        bpm: int | None = None,
        duration_seconds: float | None = None,
        license_info: str | None = None,
        tags: list[str] | None = None,
    ) -> AssetRead:
        """Register new asset. MD5 dedup check — skip if already exists.
        Steps:
        1. Compute MD5 of file
        2. Check existing by MD5 → return existing if found
        3. Create new AssetCreate → insert via repository
        """
        ...

    async def mark_used(self, asset_id: int) -> None:
        """Increment use_count. Call after asset used in production."""
        ...

    async def get_stock_levels(self) -> list[StockLevel]:
        """Check stock per asset_type + mood. Flag needs_replenish when:
        - count < 10 per mood
        - avg_use_count > 20 (overused)
        """
        ...

    async def get_replenish_list(self) -> list[StockLevel]:
        """Return only StockLevels where needs_replenish=True."""
        levels = await self.get_stock_levels()
        return [l for l in levels if l.needs_replenish]

    def compute_md5(self, file_path: str) -> str:
        """MD5 hash of file content."""
        h = hashlib.md5()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()

    # === Character Registry ===

    async def load_character_registry(self, channel_id: str) -> CharacterRegistry:
        """Load from NAS/{channel_id}/characters.json. Create empty if not exists."""
        ...

    async def save_character_registry(self, registry: CharacterRegistry) -> None:
        """Save to NAS/{channel_id}/characters.json."""
        ...

    async def get_character(self, channel_id: str, name: str) -> CharacterProfile | None:
        """Shortcut: load registry → get character."""
        registry = await self.load_character_registry(channel_id)
        return registry.get(name)
```

## DO NOT

- No actual DB session in tests — mock session_factory and repository
- No actual file I/O for MD5 in tests — mock compute_md5
- No music generation — that's MusicModule. AssetManager only searches/registers
- No modifying Phase 1 AssetRepository — use it as-is
- Character registry stored as JSON on NAS, not in PostgreSQL
- Redis lock for concurrent register not in this task — note as TODO for Phase 5+

## Tests

### tests/unit/test_asset_manager.py

```python
import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from pydantic import ValidationError
from omnicast.media.asset_manager import (
    AssetManager, CharacterProfile, CharacterRegistry, StockLevel,
)
from omnicast.models.enums import AssetType, MusicMood
from omnicast.shared.errors import MediaError


class TestCharacterProfile:
    def test_create(self):
        c = CharacterProfile(name="narrator", reference_image="/nas/ref.png")
        assert c.name == "narrator"
        assert c.ip_adapter_weight == 0.6
        assert c.lora_path is None

    def test_with_lora(self):
        c = CharacterProfile(name="hero", reference_image="/ref.png",
                              lora_path="/loras/hero_v1.safetensors", ip_adapter_weight=0.8)
        assert c.lora_path is not None

    def test_ip_weight_bounds(self):
        CharacterProfile(name="x", reference_image="/x.png", ip_adapter_weight=0.0)
        CharacterProfile(name="x", reference_image="/x.png", ip_adapter_weight=1.0)
        with pytest.raises(ValidationError):
            CharacterProfile(name="x", reference_image="/x.png", ip_adapter_weight=1.1)

    def test_frozen(self):
        c = CharacterProfile(name="x", reference_image="/x.png")
        with pytest.raises(ValidationError):
            c.name = "y"


class TestCharacterRegistry:
    def test_empty(self):
        r = CharacterRegistry(channel_id="ch1")
        assert r.list_names() == []
        assert r.get("nobody") is None

    def test_get_existing(self):
        c = CharacterProfile(name="narrator", reference_image="/ref.png")
        r = CharacterRegistry(channel_id="ch1", characters={"narrator": c})
        assert r.get("narrator") is not None
        assert r.get("narrator").reference_image == "/ref.png"

    def test_list_names(self):
        chars = {
            "narrator": CharacterProfile(name="narrator", reference_image="/a.png"),
            "villain": CharacterProfile(name="villain", reference_image="/b.png"),
        }
        r = CharacterRegistry(channel_id="ch1", characters=chars)
        assert sorted(r.list_names()) == ["narrator", "villain"]

    def test_frozen(self):
        r = CharacterRegistry(channel_id="ch1")
        with pytest.raises(ValidationError):
            r.channel_id = "ch2"


class TestStockLevel:
    def test_needs_replenish_low_count(self):
        s = StockLevel(asset_type=AssetType.MUSIC_YT_LIBRARY, mood=MusicMood.CINEMATIC,
                        count=5, needs_replenish=True)
        assert s.needs_replenish

    def test_healthy_stock(self):
        s = StockLevel(asset_type=AssetType.BROLL, count=50, avg_use_count=3.0)
        assert not s.needs_replenish


class TestAssetManagerSearch:
    @pytest.fixture
    def manager(self):
        return AssetManager(session_factory=MagicMock(), nas_base_path="/nas")

    @pytest.mark.asyncio
    async def test_search_music(self, manager):
        mock_repo = AsyncMock()
        mock_repo.search.return_value = [MagicMock(id=1, path="/nas/track.wav", use_count=2)]
        with patch.object(manager, "session_factory") as sf:
            sf.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            results = await manager.search_music(mood=MusicMood.CINEMATIC, limit=5)
            # implementation will call repo.search internally

    @pytest.mark.asyncio
    async def test_search_broll(self, manager):
        # verify it accepts tags parameter
        with patch.object(manager, "session_factory"):
            results = await manager.search_broll(tags=["ocean", "sunset"])

    @pytest.mark.asyncio
    async def test_search_template(self, manager):
        with patch.object(manager, "session_factory"):
            results = await manager.search_template(template_type="intro", channel_id="ch1")


class TestAssetManagerRegister:
    @pytest.fixture
    def manager(self):
        return AssetManager(session_factory=MagicMock(), nas_base_path="/nas")

    def test_compute_md5(self, manager, tmp_path):
        f = tmp_path / "test.wav"
        f.write_bytes(b"fake audio data 12345")
        md5 = manager.compute_md5(str(f))
        assert isinstance(md5, str) and len(md5) == 32

    def test_compute_md5_deterministic(self, manager, tmp_path):
        f = tmp_path / "test.wav"
        f.write_bytes(b"same content")
        assert manager.compute_md5(str(f)) == manager.compute_md5(str(f))

    def test_compute_md5_different_content(self, manager, tmp_path):
        f1 = tmp_path / "a.wav"
        f2 = tmp_path / "b.wav"
        f1.write_bytes(b"content A")
        f2.write_bytes(b"content B")
        assert manager.compute_md5(str(f1)) != manager.compute_md5(str(f2))


class TestAssetManagerStock:
    @pytest.fixture
    def manager(self):
        return AssetManager(session_factory=MagicMock(), nas_base_path="/nas")

    @pytest.mark.asyncio
    async def test_get_replenish_list_filters(self, manager):
        levels = [
            StockLevel(asset_type=AssetType.MUSIC_YT_LIBRARY, mood=MusicMood.CINEMATIC,
                        count=5, needs_replenish=True),
            StockLevel(asset_type=AssetType.BROLL, count=50, needs_replenish=False),
            StockLevel(asset_type=AssetType.MUSIC_AI_GENERATED, mood=MusicMood.EPIC,
                        count=3, avg_use_count=25.0, needs_replenish=True),
        ]
        with patch.object(manager, "get_stock_levels", new_callable=AsyncMock, return_value=levels):
            replenish = await manager.get_replenish_list()
            assert len(replenish) == 2
            assert all(l.needs_replenish for l in replenish)


class TestAssetManagerCharacter:
    @pytest.fixture
    def manager(self):
        return AssetManager(session_factory=MagicMock(), nas_base_path="/nas")

    @pytest.mark.asyncio
    async def test_load_empty_registry(self, manager):
        with patch.object(manager, "load_character_registry", new_callable=AsyncMock,
                           return_value=CharacterRegistry(channel_id="ch1")):
            reg = await manager.load_character_registry("ch1")
            assert reg.list_names() == []

    @pytest.mark.asyncio
    async def test_get_character(self, manager):
        char = CharacterProfile(name="narrator", reference_image="/ref.png")
        reg = CharacterRegistry(channel_id="ch1", characters={"narrator": char})
        with patch.object(manager, "load_character_registry", new_callable=AsyncMock, return_value=reg):
            result = await manager.get_character("ch1", "narrator")
            assert result is not None
            assert result.name == "narrator"

    @pytest.mark.asyncio
    async def test_get_character_missing(self, manager):
        reg = CharacterRegistry(channel_id="ch1")
        with patch.object(manager, "load_character_registry", new_callable=AsyncMock, return_value=reg):
            result = await manager.get_character("ch1", "nobody")
            assert result is None
```
