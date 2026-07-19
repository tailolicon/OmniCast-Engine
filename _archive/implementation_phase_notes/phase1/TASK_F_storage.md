# TASK F: NAS Storage Manager

> **Depends on:** TASK_A hoàn thành (shared/errors.py có StorageError, NASUnavailableError)
> **Output:** src/omnicast/storage/, tests/unit/test_storage.py
> **Parallel với:** TASK_B, C, D, E, G

## Context

OmniCast Engine lưu trữ assets trên Synology NAS (mount qua NFS/SMB).
Khi NAS unavailable → fallback sang local SSD (`/tmp/omnicast_local`).
Module này xử lý:
1. **File I/O** — read/write/delete với async (aiofiles)
2. **Path resolution** — NAS path ↔ local fallback
3. **Health check** — verify NAS mount is alive
4. **Garbage collection** — cleanup orphaned temp files

NAS directory structure:
```
/Volumes/NAS/omnicast/
├── assets/
│   ├── music/          # Generated music files (.wav, .mp3)
│   ├── images/         # Generated images (.png, .webp)
│   ├── voices/         # TTS audio files (.wav)
│   └── templates/      # Video templates (.json, .aep)
├── brand_configs/      # Per-channel brand config JSON
├── renders/
│   ├── raw/            # Raw rendered videos (.mp4)
│   ├── final/          # Final processed videos (.mp4)
│   └── thumbnails/     # Generated thumbnails (.png)
├── scripts/            # Generated scripts (.json)
└── temp/               # Temporary working files
```

## Files cần tạo

```
src/omnicast/storage/
├── __init__.py
├── paths.py            # Path resolution + directory structure
├── file_ops.py         # Async file operations
├── health.py           # NAS health check
└── cleanup.py          # Garbage collection
```

## 1. paths.py

```python
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

from pathlib import Path
from enum import StrEnum

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
```

## 2. file_ops.py

```python
"""Async file operations for storage layer.

All file I/O MUST be async to avoid blocking the event loop.
Uses aiofiles for text/binary read/write.
Uses asyncio.to_thread for os operations (rename, delete, stat).

Usage:
    ops = FileOps()
    await ops.write_binary(path, data)
    content = await ops.read_binary(path)
    await ops.move(src, dst)
    await ops.delete(path)
"""

import aiofiles
import asyncio
import hashlib
from pathlib import Path
import structlog

logger = structlog.get_logger()

class FileOps:
    """Async file operations."""
    
    async def write_binary(self, path: Path, data: bytes) -> None:
        """Write binary data to file.
        
        Implementation:
        1. Ensure parent directory exists (mkdir -p)
        2. Write to temp file first: path.with_suffix('.tmp')
        3. Rename temp → final (atomic on same filesystem)
        4. Log: "Written {len(data)} bytes to {path.name}"
        
        This pattern prevents partial writes on crash.
        
        Raises:
            StorageError: if write fails
        """
    
    async def write_text(self, path: Path, text: str, encoding: str = "utf-8") -> None:
        """Write text to file. Same atomic pattern as write_binary."""
    
    async def read_binary(self, path: Path) -> bytes:
        """Read binary file.
        
        Raises:
            StorageError: if file not found or read error
        """
    
    async def read_text(self, path: Path, encoding: str = "utf-8") -> str:
        """Read text file.
        
        Raises:
            StorageError: if file not found or read error
        """
    
    async def read_json(self, path: Path) -> dict:
        """Read and parse JSON file using orjson.
        
        Raises:
            StorageError: if file not found, read error, or invalid JSON
        """
    
    async def write_json(self, path: Path, data: dict) -> None:
        """Serialize dict to JSON and write. Use orjson with OPT_INDENT_2."""
    
    async def delete(self, path: Path) -> bool:
        """Delete file. Return True if deleted, False if not found.
        
        Use asyncio.to_thread(path.unlink, missing_ok=True).
        Log: "Deleted {path.name}"
        """
    
    async def move(self, src: Path, dst: Path) -> None:
        """Move/rename file.
        
        Implementation:
        1. Ensure dst parent exists
        2. If same filesystem → rename (atomic)
        3. If cross-filesystem → copy + delete source
        
        Raises:
            StorageError: if source not found
        """
    
    async def copy(self, src: Path, dst: Path) -> None:
        """Copy file. Ensure dst parent exists.
        
        Use asyncio.to_thread(shutil.copy2, src, dst) to preserve metadata.
        """
    
    async def exists(self, path: Path) -> bool:
        """Check if file exists. Non-blocking."""
        return await asyncio.to_thread(path.exists)
    
    async def file_size(self, path: Path) -> int:
        """Return file size in bytes. Raise StorageError if not found."""
    
    async def md5_hash(self, path: Path) -> str:
        """Calculate MD5 hash of file. Read in 8KB chunks.
        
        Used for asset deduplication.
        
        Implementation:
            hasher = hashlib.md5()
            async with aiofiles.open(path, 'rb') as f:
                while chunk := await f.read(8192):
                    hasher.update(chunk)
            return hasher.hexdigest()
        """
    
    async def list_files(
        self,
        directory: Path,
        pattern: str = "*",
        recursive: bool = False,
    ) -> list[Path]:
        """List files matching pattern.
        
        Use asyncio.to_thread with directory.glob() or rglob().
        Return sorted by modification time (newest first).
        """
    
    async def disk_usage(self, path: Path) -> dict[str, int]:
        """Return disk usage stats for path's filesystem.
        
        Use asyncio.to_thread(shutil.disk_usage, path).
        Return {"total": int, "used": int, "free": int} in bytes.
        """
```

## 3. health.py

```python
"""NAS health monitoring.

Periodically check if NAS mount is alive and writable.
If NAS goes down → switch PathResolver to local fallback.
If NAS comes back → switch back + sync pending files.

Usage:
    checker = NASHealthChecker(
        resolver=path_resolver,
        check_interval=30,
    )
    await checker.start()
    # ... runs in background ...
    await checker.stop()
"""

import asyncio
import time
from pathlib import Path
import structlog

logger = structlog.get_logger()

class NASHealthChecker:
    """Monitor NAS availability and manage fallback.
    
    Args:
        resolver: PathResolver instance to control fallback
        check_interval: seconds between health checks
        probe_file: filename for write probe test
    """
    
    def __init__(
        self,
        resolver: "PathResolver",
        check_interval: int = 30,
        probe_file: str = ".omnicast_probe",
    ):
        self.resolver = resolver
        self.check_interval = check_interval
        self.probe_file = probe_file
        self._task: asyncio.Task | None = None
        self._running = False
        self.last_check: float = 0.0
        self.consecutive_failures: int = 0
        self.is_healthy: bool = True
    
    async def check_once(self) -> bool:
        """Perform single health check.
        
        Steps:
        1. Check if NAS mount point exists (path.is_dir())
        2. Write probe file with timestamp
        3. Read probe file back → verify content matches
        4. Delete probe file
        5. If all OK → return True
        6. If any step fails → return False
        
        Must complete within 5s timeout (asyncio.wait_for).
        Use asyncio.to_thread for all file ops.
        
        Returns:
            True if NAS is healthy, False otherwise
        """
    
    async def _monitor_loop(self) -> None:
        """Background monitoring loop.
        
        Loop:
        1. await check_once()
        2. If healthy:
           - Reset consecutive_failures = 0
           - If was_unhealthy → log "NAS recovered", set resolver.set_fallback(False)
        3. If unhealthy:
           - Increment consecutive_failures
           - If consecutive_failures >= 3 (not first failure):
             - Log WARNING "NAS unavailable, switching to local"
             - resolver.set_fallback(True)
             - self.is_healthy = False
        4. Sleep check_interval
        
        3 consecutive failures before fallback → avoid flapping on transient issues.
        """
    
    async def start(self) -> None:
        """Start background monitoring task."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._monitor_loop())
        logger.info("NAS health checker started", interval=self.check_interval)
    
    async def stop(self) -> None:
        """Stop background monitoring."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("NAS health checker stopped")
    
    async def get_status(self) -> dict:
        """Return health status for dashboard.
        
        Return:
            {
                "is_healthy": bool,
                "using_fallback": bool,
                "last_check": float (timestamp),
                "consecutive_failures": int,
                "nas_path": str,
                "local_path": str,
            }
        """
```

## 4. cleanup.py

```python
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

from pathlib import Path
from datetime import datetime, timedelta, timezone
import structlog

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
    
    async def clean_empty_dirs(self) -> int:
        """Remove empty directories under base_path.
        
        Walk directory tree bottom-up.
        Delete directories that contain no files (only empty subdirs).
        Return count of deleted directories.
        
        IMPORTANT: Never delete REQUIRED_DIRS even if empty.
        """
    
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
```

## 5. __init__.py

```python
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
```

## 6. Tests

### tests/unit/test_storage.py

```python
"""Test storage utilities.

=== PathResolver Tests ===

test_assets_path_nas_mode(tmp_path):
    - resolver = PathResolver(nas_path=tmp_path/"nas", local_path=tmp_path/"local")
    - resolver.assets("music") → tmp_path/"nas"/"assets"/"music"

test_assets_path_fallback_mode(tmp_path):
    - resolver.set_fallback(True)
    - resolver.assets("music") → tmp_path/"local"/"assets"/"music"

test_render_path(tmp_path):
    - resolver.render("raw", "v001.mp4") → base/"renders"/"raw"/"v001.mp4"

test_brand_config_path(tmp_path):
    - resolver.brand_config("hub_fin_us") → base/"brand_configs"/"hub_fin_us.json"

test_ensure_dirs_creates_all(tmp_path):
    - await resolver.ensure_dirs()
    - All REQUIRED_DIRS exist

test_set_fallback_switches_base_path(tmp_path):
    - Initially base_path == nas_path
    - set_fallback(True) → base_path == local_path
    - set_fallback(False) → base_path == nas_path

=== FileOps Tests ===

test_write_and_read_binary(tmp_path):
    - ops = FileOps()
    - data = b"test audio data"
    - await ops.write_binary(tmp_path / "test.wav", data)
    - result = await ops.read_binary(tmp_path / "test.wav")
    - assert result == data

test_write_atomic_no_partial(tmp_path):
    - Write binary data
    - Verify no .tmp file remains after successful write
    - Verify actual file has correct content

test_read_nonexistent_raises(tmp_path):
    - await ops.read_binary(tmp_path / "nope.wav") → raises StorageError

test_write_creates_parent_dirs(tmp_path):
    - await ops.write_binary(tmp_path / "a" / "b" / "c" / "file.txt", b"data")
    - File exists with correct content

test_delete_returns_true(tmp_path):
    - Create file
    - await ops.delete(path) → True
    - File no longer exists

test_delete_nonexistent_returns_false(tmp_path):
    - await ops.delete(tmp_path / "nope") → False

test_move_same_dir(tmp_path):
    - Create file at src
    - await ops.move(src, dst)
    - dst exists, src doesn't

test_md5_hash(tmp_path):
    - Write known content
    - hash = await ops.md5_hash(path)
    - assert hash == expected_md5  # pre-computed

test_list_files_with_pattern(tmp_path):
    - Create: a.mp3, b.mp3, c.wav
    - await ops.list_files(tmp_path, "*.mp3") → [a.mp3, b.mp3]

test_write_and_read_json(tmp_path):
    - data = {"key": "value", "number": 42}
    - await ops.write_json(path, data)
    - result = await ops.read_json(path)
    - assert result == data

test_disk_usage(tmp_path):
    - result = await ops.disk_usage(tmp_path)
    - assert "total" in result and "free" in result
    - assert result["total"] > 0

=== NASHealthChecker Tests ===

test_check_healthy(tmp_path):
    - resolver = PathResolver(nas_path=tmp_path, local_path=tmp_path/"local")
    - checker = NASHealthChecker(resolver)
    - result = await checker.check_once()
    - assert result is True

test_check_unhealthy_missing_dir():
    - resolver with nas_path="/nonexistent/path"
    - result = await checker.check_once()
    - assert result is False

test_fallback_after_consecutive_failures(tmp_path):
    - Mock check_once to return False
    - Run 3 check cycles
    - Verify resolver._use_local is True

test_recovery_after_nas_returns(tmp_path):
    - Set to fallback mode
    - Mock check_once to return True
    - Run check cycle
    - Verify resolver._use_local is False

test_get_status(tmp_path):
    - status = await checker.get_status()
    - assert "is_healthy" in status
    - assert "using_fallback" in status

=== StorageGC Tests ===

test_clean_temp_old_files(tmp_path):
    - Create temp files with old mtime (>24h)
    - result = await gc.clean_temp()
    - assert result["deleted_count"] > 0

test_clean_temp_keeps_recent(tmp_path):
    - Create temp file with recent mtime
    - result = await gc.clean_temp()
    - assert result["deleted_count"] == 0
    - File still exists

test_clean_empty_dirs(tmp_path):
    - Create empty subdirectories
    - count = await gc.clean_empty_dirs()
    - assert count > 0

test_clean_orphaned_renders(tmp_path):
    - Create render files: video_001.mp4, video_002.mp4
    - known_ids = {"video_001"}
    - result = await gc.clean_orphaned_renders(known_ids)
    - video_001.mp4 still exists
    - video_002.mp4 deleted

test_run_full_gc(tmp_path):
    - Create mix of old temp files and valid files
    - report = await gc.run()
    - assert "temp" in report
    - assert "disk_usage" in report
    - assert "duration_seconds" in report

test_get_storage_report(tmp_path):
    - Create some files in various categories
    - report = await gc.get_storage_report()
    - assert "total_gb" in report
    - assert "by_category" in report
"""
```

## 7. DO NOT

- ❌ Đừng dùng synchronous file I/O — tất cả async (aiofiles hoặc asyncio.to_thread)
- ❌ Đừng write trực tiếp vào final path — write to .tmp rồi rename (atomic)
- ❌ Đừng ignore NAS failures — phải có fallback mechanism
- ❌ Đừng delete files không qua StorageGC — centralize deletion logic
- ❌ Đừng hardcode paths — dùng PathResolver
- ❌ Đừng block event loop với shutil.copy — wrap trong asyncio.to_thread
- ❌ Đừng delete REQUIRED_DIRS trong clean_empty_dirs

## 8. Acceptance Criteria

```bash
uv run pytest tests/unit/test_storage.py -v
uv run pyright src/omnicast/storage/
```
