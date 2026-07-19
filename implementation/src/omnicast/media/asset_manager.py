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
        self.characters = self.characters.copy()
        self.characters[profile.name] = profile

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
        # Placeholder for actual music search
        # In production: query AssetRepository with filters, order by use_count ASC
        return []

    async def search_broll(
        self,
        tags: list[str],
        duration_needed: float | None = None,
        limit: int = 10,
    ) -> list[AssetRead]:
        """Semantic search B-roll by tags. ORDER BY use_count ASC."""
        # Placeholder for actual B-roll search
        # In production: query AssetRepository with tags, order by use_count ASC
        return []

    async def search_template(
        self,
        template_type: str,  # "intro" | "outro" | "overlay"
        channel_id: str | None = None,
        limit: int = 3,
    ) -> list[AssetRead]:
        """Search intro/outro/overlay templates. Channel-specific first, then global."""
        # Placeholder for actual template search
        # In production: query AssetRepository, filter by template_type and channel_id
        return []

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
        # Placeholder for actual asset registration
        # In production: compute MD5, check dedup, insert via AssetRepository
        return AssetRead(
            id=1,
            path=path,
            asset_type=asset_type,
            mood=mood,
            bpm=bpm,
            duration_seconds=duration_seconds,
            license_info=license_info,
            tags=tags or [],
            use_count=0,
            created_at=datetime.now(timezone.utc),
        )

    async def mark_used(self, asset_id: int) -> None:
        """Increment use_count. Call after asset used in production."""
        # Placeholder for actual use count increment
        # In production: update AssetRepository use_count
        pass

    async def get_stock_levels(self) -> list[StockLevel]:
        """Check stock per asset_type + mood. Flag needs_replenish when:
        - count < 10 per mood
        - avg_use_count > 20 (overused)
        """
        # Placeholder for actual stock level calculation
        # In production: query AssetRepository, aggregate by type+mood
        return []

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
        # Placeholder for actual character registry loading
        # In production: read JSON from NAS/{channel_id}/characters.json
        return CharacterRegistry(channel_id=channel_id)

    async def save_character_registry(self, registry: CharacterRegistry) -> None:
        """Save to NAS/{channel_id}/characters.json."""
        # Placeholder for actual character registry saving
        # In production: write JSON to NAS/{channel_id}/characters.json
        pass

    async def get_character(self, channel_id: str, name: str) -> CharacterProfile | None:
        """Shortcut: load registry → get character."""
        registry = await self.load_character_registry(channel_id)
        return registry.get(name)
