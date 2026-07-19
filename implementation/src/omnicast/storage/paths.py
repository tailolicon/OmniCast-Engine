"""Path resolution for NAS and local fallback storage.

Usage:
    resolver = PathResolver(
        nas_path="/Volumes/NAS/omnicast",
        local_path="/tmp/omnicast_local",
    )
    music_dir = resolver.assets("music")
    # → Path("/Volumes/NAS/omnicast/assets/music") if NAS available
    # → Path("/tmp/omnicast_local/assets/music") if NAS down

    render_path = resolver.render("raw", "video_001.mp4")
    # → Path("/Volumes/NAS/omnicast/renders/raw/video_001.mp4")
"""

import asyncio
from pathlib import Path
from enum import StrEnum
import structlog

logger = structlog.get_logger()


class AssetCategory(StrEnum):
    MUSIC = "music"
    IMAGES = "images"
    VOICES = "voices"
    TEMPLATES = "templates"


class RenderStage(StrEnum):
    RAW = "raw"
    FINAL = "final"
    THUMBNAILS = "thumbnails"


# All subdirectories that must exist
REQUIRED_DIRS = [
    "assets/music",
    "assets/images",
    "assets/voices",
    "assets/templates",
    "brand_configs",
    "renders/raw",
    "renders/final",
    "renders/thumbnails",
    "scripts",
    "temp",
]


class PathResolver:
    """Resolve storage paths with NAS/local fallback.

    Args:
        nas_path: NAS mount point (e.g. /Volumes/NAS/omnicast)
        local_path: Local fallback directory
    """

    def __init__(self, nas_path: str | Path, local_path: str | Path):
        self.nas_path = Path(nas_path)
        self.local_path = Path(local_path)
        self._use_local = False  # Set by health check

    @property
    def base_path(self) -> Path:
        """Return NAS path if available, else local fallback."""
        return self.local_path if self._use_local else self.nas_path

    def set_fallback(self, use_local: bool) -> None:
        """Switch between NAS and local storage. Called by health checker."""
        self._use_local = use_local

    def assets(self, category: str | AssetCategory) -> Path:
        """Return path to asset category directory.
        e.g. assets("music") → base_path / "assets" / "music"
        """
        return self.base_path / "assets" / str(category)

    def asset_file(self, category: str | AssetCategory, filename: str) -> Path:
        """Return full path to a specific asset file."""
        return self.assets(category) / filename

    def render(self, stage: str | RenderStage, filename: str) -> Path:
        """Return path to render file.
        e.g. render("raw", "v001.mp4") → base_path / "renders" / "raw" / "v001.mp4"
        """
        return self.base_path / "renders" / str(stage) / filename

    def brand_config(self, channel_id: str) -> Path:
        """Return path to channel's brand config JSON."""
        return self.base_path / "brand_configs" / f"{channel_id}.json"

    def script(self, video_id: str) -> Path:
        """Return path to video script JSON."""
        return self.base_path / "scripts" / f"{video_id}.json"

    def temp(self, filename: str) -> Path:
        """Return path in temp directory."""
        return self.base_path / "temp" / filename

    async def ensure_dirs(self) -> None:
        """Create all required directories if they don't exist.

        Use asyncio.to_thread(path.mkdir, parents=True, exist_ok=True)
        for each directory in REQUIRED_DIRS.
        Log: "Storage directories initialized at {base_path}"
        """
        base = self.base_path
        for dir_name in REQUIRED_DIRS:
            dir_path = base / dir_name
            await asyncio.to_thread(dir_path.mkdir, parents=True, exist_ok=True)
        logger.info("Storage directories initialized", base_path=str(base))