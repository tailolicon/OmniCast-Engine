"""Storage layer public API.

Usage:
    from omnicast.storage import PathResolver, FileOps, NASHealthChecker, StorageGC

    resolver = PathResolver(nas_path="/Volumes/NAS/omnicast", local_path="/tmp/omnicast_local")
    await resolver.ensure_dirs()

    file_ops = FileOps()
    await file_ops.write_binary(resolver.asset_file("music", "track.wav"), audio_data)

    health = NASHealthChecker(resolver)
    await health.start()
"""

from omnicast.storage.paths import PathResolver, AssetCategory, RenderStage, REQUIRED_DIRS
from omnicast.storage.file_ops import FileOps
from omnicast.storage.health import NASHealthChecker
from omnicast.storage.cleanup import StorageGC

__all__ = [
    "PathResolver",
    "AssetCategory",
    "RenderStage",
    "REQUIRED_DIRS",
    "FileOps",
    "NASHealthChecker",
    "StorageGC",
]