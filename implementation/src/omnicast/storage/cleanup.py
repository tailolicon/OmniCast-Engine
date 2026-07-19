"""Garbage collection for temporary and orphaned files.

Runs periodically to:
1. Delete temp files older than max_age
2. Delete empty directories
3. Report disk usage stats

Usage:
    gc = StorageGC(
        resolver=path_resolver,
        file_ops=file_ops,
        max_temp_age_hours=24,
    )
    report = await gc.run()
    print(f"Cleaned {report['deleted_count']} files, freed {report['freed_bytes']} bytes")
"""

import asyncio
import time
from pathlib import Path
from datetime import datetime, timedelta, timezone

import structlog

from omnicast.storage.paths import REQUIRED_DIRS

logger = structlog.get_logger()


class StorageGC:
    """Garbage collector for storage.

    Args:
        resolver: PathResolver for directory paths
        file_ops: FileOps instance
        max_temp_age_hours: delete temp files older than this (default 24h)
    """

    def __init__(
        self,
        resolver: "PathResolver",
        file_ops: "FileOps",
        max_temp_age_hours: int = 24,
    ):
        self.resolver = resolver
        self.file_ops = file_ops
        self.max_temp_age = timedelta(hours=max_temp_age_hours)

    async def clean_temp(self) -> dict[str, int]:
        """Delete temp files older than max_temp_age.

        Steps:
        1. List all files in resolver.base_path / "temp"
        2. For each file: check modification time
        3. If older than max_temp_age → delete
        4. Return {"deleted_count": int, "freed_bytes": int}

        Use asyncio.to_thread(path.stat) to get mtime.
        Log each deletion: "GC deleted {filename}, age={hours}h"
        """
        temp_dir = self.resolver.base_path / "temp"
        deleted_count = 0
        freed_bytes = 0

        if not await asyncio.to_thread(temp_dir.is_dir):
            return {"deleted_count": 0, "freed_bytes": 0}

        now = datetime.now(timezone.utc)
        cutoff = now - self.max_temp_age

        def _list_files():
            return [f for f in temp_dir.iterdir() if f.is_file()]

        files = await asyncio.to_thread(_list_files)

        for file_path in files:
            try:
                stat = await asyncio.to_thread(file_path.stat)
                mtime = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
                if mtime < cutoff:
                    size = stat.st_size
                    await self.file_ops.delete(file_path)
                    age_hours = (now - mtime).total_seconds() / 3600
                    logger.info(
                        "GC deleted temp file",
                        filename=file_path.name,
                        age_hours=round(age_hours, 1),
                    )
                    deleted_count += 1
                    freed_bytes += size
            except Exception as e:
                logger.warning("GC failed to delete temp file", filename=file_path.name, error=str(e))

        return {"deleted_count": deleted_count, "freed_bytes": freed_bytes}

    async def clean_empty_dirs(self) -> int:
        """Remove empty directories under base_path.

        Walk directory tree bottom-up.
        Delete directories that contain no files (only empty subdirs).
        Return count of deleted directories.

        IMPORTANT: Never delete REQUIRED_DIRS even if empty.
        """
        base = self.resolver.base_path
        required_paths = {base / d for d in REQUIRED_DIRS}
        deleted_count = 0

        def _walk_dirs():
            """Walk bottom-up, collecting dirs."""
            dirs_to_check = []
            for root, dirs, files in base.walk(top_down=False):
                for d in dirs:
                    dir_path = root / d
                    dirs_to_check.append(dir_path)
            return dirs_to_check

        dirs = await asyncio.to_thread(_walk_dirs)

        for dir_path in dirs:
            # Skip required directories
            if dir_path in required_paths:
                continue

            try:
                # Check if directory is empty (no files, no subdirs)
                contents = await asyncio.to_thread(lambda p=dir_path: list(p.iterdir()))
                if not contents:
                    await asyncio.to_thread(dir_path.rmdir)
                    logger.info("GC deleted empty directory", path=str(dir_path))
                    deleted_count += 1
            except Exception as e:
                logger.warning(
                    "GC failed to delete empty dir",
                    path=str(dir_path),
                    error=str(e),
                )

        return deleted_count

    async def clean_orphaned_renders(self, known_video_ids: set[str]) -> dict[str, int]:
        """Delete render files for videos not in known_video_ids.

        Args:
            known_video_ids: set of valid video IDs from database

        Steps:
        1. List all files in renders/raw/ and renders/final/
        2. Extract video_id from filename (pattern: {video_id}_*.mp4)
        3. If video_id not in known_video_ids → delete
        4. Return {"deleted_count": int, "freed_bytes": int}

        This prevents storage leak when videos are deleted from DB
        but render files remain on disk.
        """
        deleted_count = 0
        freed_bytes = 0

        for stage in ("raw", "final"):
            render_dir = self.resolver.base_path / "renders" / stage
            if not await asyncio.to_thread(render_dir.is_dir):
                continue

            def _list_mp4():
                return list(render_dir.glob("*.mp4"))

            files = await asyncio.to_thread(_list_mp4)

            for file_path in files:
                # Extract video_id from filename: stem IS the video_id
                video_id = file_path.stem
                if video_id not in known_video_ids:
                    try:
                        stat = await asyncio.to_thread(file_path.stat)
                        size = stat.st_size
                        await self.file_ops.delete(file_path)
                        logger.info(
                            "GC deleted orphaned render",
                            filename=file_path.name,
                        )
                        deleted_count += 1
                        freed_bytes += size
                    except Exception as e:
                        logger.warning(
                            "GC failed to delete orphaned render",
                            filename=file_path.name,
                            error=str(e),
                        )

        return {"deleted_count": deleted_count, "freed_bytes": freed_bytes}

    async def run(self) -> dict:
        """Run full garbage collection cycle.

        Returns:
            {
                "temp": {"deleted_count": int, "freed_bytes": int},
                "empty_dirs": int,
                "disk_usage": {"total": int, "used": int, "free": int},
                "duration_seconds": float,
            }

        Log summary: "GC complete: deleted {n} files, freed {mb}MB, {free_pct}% free"
        """
        start = time.time()

        temp_result = await self.clean_temp()
        empty_dirs_count = await self.clean_empty_dirs()
        disk_usage = await self.file_ops.disk_usage(self.resolver.base_path)

        duration = time.time() - start
        total_deleted = temp_result["deleted_count"]
        total_freed = temp_result["freed_bytes"]
        free_pct = (disk_usage["free"] / disk_usage["total"] * 100) if disk_usage["total"] > 0 else 0

        logger.info(
            "GC complete",
            deleted_count=total_deleted,
            freed_mb=round(total_freed / (1024 * 1024), 1),
            free_pct=round(free_pct, 1),
        )

        return {
            "temp": temp_result,
            "empty_dirs": empty_dirs_count,
            "disk_usage": disk_usage,
            "duration_seconds": duration,
        }

    async def get_storage_report(self) -> dict:
        """Generate storage usage report for dashboard.

        Return:
            {
                "total_gb": float,
                "used_gb": float,
                "free_gb": float,
                "free_percent": float,
                "by_category": {
                    "music": {"count": int, "size_mb": float},
                    "images": {"count": int, "size_mb": float},
                    "voices": {"count": int, "size_mb": float},
                    "renders_raw": {"count": int, "size_mb": float},
                    "renders_final": {"count": int, "size_mb": float},
                    "temp": {"count": int, "size_mb": float},
                },
            }
        """
        base = self.resolver.base_path
        disk_usage = await self.file_ops.disk_usage(base)

        categories = {
            "music": base / "assets" / "music",
            "images": base / "assets" / "images",
            "voices": base / "assets" / "voices",
            "renders_raw": base / "renders" / "raw",
            "renders_final": base / "renders" / "final",
            "temp": base / "temp",
        }

        by_category = {}
        for name, dir_path in categories.items():
            count = 0
            total_size = 0
            if await asyncio.to_thread(dir_path.is_dir):
                def _scan():
                    c = 0
                    s = 0
                    for f in dir_path.rglob("*"):
                        if f.is_file():
                            c += 1
                            s += f.stat().st_size
                    return c, s
                count, total_size = await asyncio.to_thread(_scan)

            by_category[name] = {
                "count": count,
                "size_mb": round(total_size / (1024 * 1024), 2),
            }

        total = disk_usage["total"]
        used = disk_usage["used"]
        free = disk_usage["free"]

        return {
            "total_gb": round(total / (1024 ** 3), 2),
            "used_gb": round(used / (1024 ** 3), 2),
            "free_gb": round(free / (1024 ** 3), 2),
            "free_percent": round((free / total * 100) if total > 0 else 0, 1),
            "by_category": by_category,
        }