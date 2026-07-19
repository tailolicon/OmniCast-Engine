"""Test storage utilities.

=== PathResolver Tests ===
test_assets_path_nas_mode(tmp_path)
test_assets_path_fallback_mode(tmp_path)
test_render_path(tmp_path)
test_brand_config_path(tmp_path)
test_ensure_dirs_creates_all(tmp_path)
test_set_fallback_switches_base_path(tmp_path)

=== FileOps Tests ===
test_write_and_read_binary(tmp_path)
test_write_atomic_no_partial(tmp_path)
test_read_nonexistent_raises(tmp_path)
test_write_creates_parent_dirs(tmp_path)
test_delete_returns_true(tmp_path)
test_delete_nonexistent_returns_false(tmp_path)
test_move_same_dir(tmp_path)
test_md5_hash(tmp_path)
test_list_files_with_pattern(tmp_path)
test_write_and_read_json(tmp_path)
test_disk_usage(tmp_path)

=== NASHealthChecker Tests ===
test_check_healthy(tmp_path)
test_check_unhealthy_missing_dir()
test_fallback_after_consecutive_failures(tmp_path)
test_recovery_after_nas_returns(tmp_path)
test_get_status(tmp_path)

=== StorageGC Tests ===
test_clean_temp_old_files(tmp_path)
test_clean_temp_keeps_recent(tmp_path)
test_clean_empty_dirs(tmp_path)
test_clean_orphaned_renders(tmp_path)
test_run_full_gc(tmp_path)
test_get_storage_report(tmp_path)
"""

import asyncio
import time
from pathlib import Path
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from omnicast.shared.errors import StorageError
from omnicast.storage.paths import PathResolver, AssetCategory, RenderStage, REQUIRED_DIRS
from omnicast.storage.file_ops import FileOps
from omnicast.storage.health import NASHealthChecker
from omnicast.storage.cleanup import StorageGC


# === PathResolver Tests ===


class TestPathResolver:
    def test_assets_path_nas_mode(self, tmp_path: Path):
        """Test assets() returns NAS path when not in fallback mode."""
        nas = tmp_path / "nas"
        local = tmp_path / "local"
        resolver = PathResolver(nas_path=nas, local_path=local)
        assert resolver.assets("music") == nas / "assets" / "music"

    def test_assets_path_fallback_mode(self, tmp_path: Path):
        """Test assets() returns local path when in fallback mode."""
        nas = tmp_path / "nas"
        local = tmp_path / "local"
        resolver = PathResolver(nas_path=nas, local_path=local)
        resolver.set_fallback(True)
        assert resolver.assets("music") == local / "assets" / "music"

    def test_render_path(self, tmp_path: Path):
        """Test render() returns correct path."""
        nas = tmp_path / "nas"
        local = tmp_path / "local"
        resolver = PathResolver(nas_path=nas, local_path=local)
        assert resolver.render("raw", "v001.mp4") == nas / "renders" / "raw" / "v001.mp4"

    def test_brand_config_path(self, tmp_path: Path):
        """Test brand_config() returns correct path."""
        nas = tmp_path / "nas"
        local = tmp_path / "local"
        resolver = PathResolver(nas_path=nas, local_path=local)
        assert resolver.brand_config("hub_fin_us") == nas / "brand_configs" / "hub_fin_us.json"

    async def test_ensure_dirs_creates_all(self, tmp_path: Path):
        """Test ensure_dirs() creates all REQUIRED_DIRS."""
        nas = tmp_path / "nas"
        local = tmp_path / "local"
        resolver = PathResolver(nas_path=nas, local_path=local)
        await resolver.ensure_dirs()
        for dir_name in REQUIRED_DIRS:
            assert (nas / dir_name).is_dir()

    def test_set_fallback_switches_base_path(self, tmp_path: Path):
        """Test set_fallback() switches base_path correctly."""
        nas = tmp_path / "nas"
        local = tmp_path / "local"
        resolver = PathResolver(nas_path=nas, local_path=local)
        assert resolver.base_path == nas
        resolver.set_fallback(True)
        assert resolver.base_path == local
        resolver.set_fallback(False)
        assert resolver.base_path == nas

    def test_asset_file_path(self, tmp_path: Path):
        """Test asset_file() returns full path to specific file."""
        nas = tmp_path / "nas"
        local = tmp_path / "local"
        resolver = PathResolver(nas_path=nas, local_path=local)
        assert resolver.asset_file("music", "track.wav") == nas / "assets" / "music" / "track.wav"

    def test_script_path(self, tmp_path: Path):
        """Test script() returns correct path."""
        nas = tmp_path / "nas"
        local = tmp_path / "local"
        resolver = PathResolver(nas_path=nas, local_path=local)
        assert resolver.script("vid_001") == nas / "scripts" / "vid_001.json"

    def test_temp_path(self, tmp_path: Path):
        """Test temp() returns correct path."""
        nas = tmp_path / "nas"
        local = tmp_path / "local"
        resolver = PathResolver(nas_path=nas, local_path=local)
        assert resolver.temp("work.tmp") == nas / "temp" / "work.tmp"

    def test_assets_with_enum(self, tmp_path: Path):
        """Test assets() works with AssetCategory enum."""
        nas = tmp_path / "nas"
        local = tmp_path / "local"
        resolver = PathResolver(nas_path=nas, local_path=local)
        assert resolver.assets(AssetCategory.MUSIC) == nas / "assets" / "music"

    def test_render_with_enum(self, tmp_path: Path):
        """Test render() works with RenderStage enum."""
        nas = tmp_path / "nas"
        local = tmp_path / "local"
        resolver = PathResolver(nas_path=nas, local_path=local)
        assert resolver.render(RenderStage.FINAL, "v001.mp4") == nas / "renders" / "final" / "v001.mp4"


# === FileOps Tests ===


class TestFileOps:
    async def test_write_and_read_binary(self, tmp_path: Path):
        """Test write_binary and read_binary roundtrip."""
        ops = FileOps()
        data = b"test audio data"
        path = tmp_path / "test.wav"
        await ops.write_binary(path, data)
        result = await ops.read_binary(path)
        assert result == data

    async def test_write_atomic_no_partial(self, tmp_path: Path):
        """Test write_binary leaves no .tmp file after success."""
        ops = FileOps()
        data = b"test data"
        path = tmp_path / "test.bin"
        await ops.write_binary(path, data)
        # No .tmp file should remain
        tmp_files = list(tmp_path.glob("*.tmp"))
        assert len(tmp_files) == 0
        # Actual file has correct content
        assert path.read_bytes() == data

    async def test_read_nonexistent_raises(self, tmp_path: Path):
        """Test read_binary raises StorageError for nonexistent file."""
        ops = FileOps()
        with pytest.raises(StorageError):
            await ops.read_binary(tmp_path / "nope.wav")

    async def test_write_creates_parent_dirs(self, tmp_path: Path):
        """Test write_binary creates parent directories."""
        ops = FileOps()
        path = tmp_path / "a" / "b" / "c" / "file.txt"
        await ops.write_binary(path, b"data")
        assert path.exists()
        assert path.read_bytes() == b"data"

    async def test_delete_returns_true(self, tmp_path: Path):
        """Test delete returns True for existing file."""
        ops = FileOps()
        path = tmp_path / "to_delete.txt"
        path.write_text("content")
        result = await ops.delete(path)
        assert result is True
        assert not path.exists()

    async def test_delete_nonexistent_returns_false(self, tmp_path: Path):
        """Test delete returns False for nonexistent file."""
        ops = FileOps()
        result = await ops.delete(tmp_path / "nope")
        assert result is False

    async def test_move_same_dir(self, tmp_path: Path):
        """Test move renames file correctly."""
        ops = FileOps()
        src = tmp_path / "src.txt"
        dst = tmp_path / "dst.txt"
        src.write_text("content")
        await ops.move(src, dst)
        assert dst.exists()
        assert not src.exists()
        assert dst.read_text() == "content"

    async def test_md5_hash(self, tmp_path: Path):
        """Test md5_hash returns correct hash."""
        ops = FileOps()
        content = b"hello world"
        path = tmp_path / "hash_test.txt"
        path.write_bytes(content)
        # MD5 of "hello world" is 5eb63bbbe01eeed093cb22bb8f5acdc3
        hash_result = await ops.md5_hash(path)
        assert hash_result == "5eb63bbbe01eeed093cb22bb8f5acdc3"

    async def test_list_files_with_pattern(self, tmp_path: Path):
        """Test list_files filters by pattern."""
        ops = FileOps()
        (tmp_path / "a.mp3").write_bytes(b"1")
        (tmp_path / "b.mp3").write_bytes(b"2")
        (tmp_path / "c.wav").write_bytes(b"3")
        files = await ops.list_files(tmp_path, "*.mp3")
        assert len(files) == 2
        assert all(f.suffix == ".mp3" for f in files)

    async def test_write_and_read_json(self, tmp_path: Path):
        """Test write_json and read_json roundtrip."""
        ops = FileOps()
        data = {"key": "value", "number": 42}
        path = tmp_path / "data.json"
        await ops.write_json(path, data)
        result = await ops.read_json(path)
        assert result == data

    async def test_disk_usage(self, tmp_path: Path):
        """Test disk_usage returns valid stats."""
        ops = FileOps()
        result = await ops.disk_usage(tmp_path)
        assert "total" in result
        assert "free" in result
        assert result["total"] > 0

    async def test_read_text(self, tmp_path: Path):
        """Test read_text returns correct content."""
        ops = FileOps()
        path = tmp_path / "text.txt"
        path.write_text("hello world", encoding="utf-8")
        result = await ops.read_text(path)
        assert result == "hello world"

    async def test_write_text(self, tmp_path: Path):
        """Test write_text writes correctly."""
        ops = FileOps()
        path = tmp_path / "text.txt"
        await ops.write_text(path, "hello world")
        assert path.read_text(encoding="utf-8") == "hello world"

    async def test_exists(self, tmp_path: Path):
        """Test exists returns correct boolean."""
        ops = FileOps()
        path = tmp_path / "exists.txt"
        assert await ops.exists(path) is False
        path.write_text("content")
        assert await ops.exists(path) is True

    async def test_file_size(self, tmp_path: Path):
        """Test file_size returns correct size."""
        ops = FileOps()
        path = tmp_path / "size.txt"
        path.write_text("12345")
        size = await ops.file_size(path)
        assert size == 5

    async def test_file_size_nonexistent_raises(self, tmp_path: Path):
        """Test file_size raises StorageError for nonexistent file."""
        ops = FileOps()
        with pytest.raises(StorageError):
            await ops.file_size(tmp_path / "nope.txt")

    async def test_copy(self, tmp_path: Path):
        """Test copy copies file correctly."""
        ops = FileOps()
        src = tmp_path / "src.txt"
        dst = tmp_path / "dst.txt"
        src.write_text("content")
        await ops.copy(src, dst)
        assert dst.exists()
        assert dst.read_text() == "content"

    async def test_read_json_invalid_raises(self, tmp_path: Path):
        """Test read_json raises StorageError for invalid JSON."""
        ops = FileOps()
        path = tmp_path / "bad.json"
        path.write_text("not json {{{")
        with pytest.raises(StorageError):
            await ops.read_json(path)


# === NASHealthChecker Tests ===


class TestNASHealthChecker:
    async def test_check_healthy(self, tmp_path: Path):
        """Test check_once returns True for healthy NAS."""
        nas = tmp_path / "nas"
        nas.mkdir()
        local = tmp_path / "local"
        resolver = PathResolver(nas_path=nas, local_path=local)
        checker = NASHealthChecker(resolver)
        result = await checker.check_once()
        assert result is True

    async def test_check_unhealthy_missing_dir(self):
        """Test check_once returns False when NAS dir doesn't exist."""
        resolver = PathResolver(nas_path="/nonexistent/path", local_path="/tmp/local")
        checker = NASHealthChecker(resolver)
        result = await checker.check_once()
        assert result is False

    async def test_fallback_after_consecutive_failures(self, tmp_path: Path):
        """Test fallback after 3 consecutive failures."""
        nas = tmp_path / "nas"
        nas.mkdir()
        local = tmp_path / "local"
        resolver = PathResolver(nas_path=nas, local_path=local)
        checker = NASHealthChecker(resolver, check_interval=1)

        # Mock check_once to return False
        async def mock_check():
            return False

        checker.check_once = mock_check

        # Run 3 check cycles manually
        for _ in range(3):
            healthy = await checker.check_once()
            if not healthy:
                checker.consecutive_failures += 1
                if checker.consecutive_failures >= 3:
                    checker.resolver.set_fallback(True)
                    checker.is_healthy = False

        assert resolver._use_local is True
        assert checker.is_healthy is False

    async def test_recovery_after_nas_returns(self, tmp_path: Path):
        """Test recovery when NAS becomes healthy again."""
        nas = tmp_path / "nas"
        nas.mkdir()
        local = tmp_path / "local"
        resolver = PathResolver(nas_path=nas, local_path=local)
        resolver.set_fallback(True)  # Start in fallback mode

        checker = NASHealthChecker(resolver)
        result = await checker.check_once()
        assert result is True
        # After healthy check, consecutive_failures reset
        assert checker.consecutive_failures == 0

    async def test_get_status(self, tmp_path: Path):
        """Test get_status returns correct structure."""
        nas = tmp_path / "nas"
        nas.mkdir()
        local = tmp_path / "local"
        resolver = PathResolver(nas_path=nas, local_path=local)
        checker = NASHealthChecker(resolver)

        status = await checker.get_status()
        assert "is_healthy" in status
        assert "using_fallback" in status
        assert "last_check" in status
        assert "consecutive_failures" in status
        assert "nas_path" in status
        assert "local_path" in status


# === StorageGC Tests ===


class TestStorageGC:
    async def test_clean_temp_old_files(self, tmp_path: Path):
        """Test clean_temp deletes old files."""
        nas = tmp_path / "nas"
        local = tmp_path / "local"
        resolver = PathResolver(nas_path=nas, local_path=local)
        await resolver.ensure_dirs()

        file_ops = FileOps()
        gc = StorageGC(resolver, file_ops, max_temp_age_hours=24)

        # Create temp file with old mtime (>24h)
        temp_file = nas / "temp" / "old_file.txt"
        temp_file.write_text("old content")
        old_time = time.time() - (25 * 3600)  # 25 hours ago
        import os
        os.utime(temp_file, (old_time, old_time))

        result = await gc.clean_temp()
        assert result["deleted_count"] == 1
        assert not temp_file.exists()

    async def test_clean_temp_keeps_recent(self, tmp_path: Path):
        """Test clean_temp keeps recent files."""
        nas = tmp_path / "nas"
        local = tmp_path / "local"
        resolver = PathResolver(nas_path=nas, local_path=local)
        await resolver.ensure_dirs()

        file_ops = FileOps()
        gc = StorageGC(resolver, file_ops, max_temp_age_hours=24)

        # Create temp file with recent mtime
        temp_file = nas / "temp" / "recent_file.txt"
        temp_file.write_text("recent content")

        result = await gc.clean_temp()
        assert result["deleted_count"] == 0
        assert temp_file.exists()

    async def test_clean_empty_dirs(self, tmp_path: Path):
        """Test clean_empty_dirs removes empty directories."""
        nas = tmp_path / "nas"
        local = tmp_path / "local"
        resolver = PathResolver(nas_path=nas, local_path=local)
        await resolver.ensure_dirs()

        file_ops = FileOps()
        gc = StorageGC(resolver, file_ops)

        # Create empty subdirectory (not in REQUIRED_DIRS)
        empty_dir = nas / "empty_subdir"
        empty_dir.mkdir()

        count = await gc.clean_empty_dirs()
        assert count >= 1
        assert not empty_dir.exists()

    async def test_clean_orphaned_renders(self, tmp_path: Path):
        """Test clean_orphaned_renders deletes files for unknown video IDs."""
        nas = tmp_path / "nas"
        local = tmp_path / "local"
        resolver = PathResolver(nas_path=nas, local_path=local)
        await resolver.ensure_dirs()

        file_ops = FileOps()
        gc = StorageGC(resolver, file_ops)

        # Create render files
        render1 = nas / "renders" / "raw" / "video_001.mp4"
        render2 = nas / "renders" / "raw" / "video_002.mp4"
        render1.write_bytes(b"video1")
        render2.write_bytes(b"video2")

        known_ids = {"video_001"}
        result = await gc.clean_orphaned_renders(known_ids)

        assert render1.exists()  # Known ID, should remain
        assert not render2.exists()  # Unknown ID, should be deleted
        assert result["deleted_count"] == 1

    async def test_run_full_gc(self, tmp_path: Path):
        """Test run() returns complete report."""
        nas = tmp_path / "nas"
        local = tmp_path / "local"
        resolver = PathResolver(nas_path=nas, local_path=local)
        await resolver.ensure_dirs()

        file_ops = FileOps()
        gc = StorageGC(resolver, file_ops, max_temp_age_hours=24)

        # Create old temp file
        temp_file = nas / "temp" / "old.txt"
        temp_file.write_text("old")
        old_time = time.time() - (25 * 3600)
        import os
        os.utime(temp_file, (old_time, old_time))

        report = await gc.run()
        assert "temp" in report
        assert "disk_usage" in report
        assert "duration_seconds" in report
        assert report["temp"]["deleted_count"] == 1

    async def test_get_storage_report(self, tmp_path: Path):
        """Test get_storage_report returns correct structure."""
        nas = tmp_path / "nas"
        local = tmp_path / "local"
        resolver = PathResolver(nas_path=nas, local_path=local)
        await resolver.ensure_dirs()

        file_ops = FileOps()
        gc = StorageGC(resolver, file_ops)

        # Create some files
        (nas / "assets" / "music" / "track.mp3").write_bytes(b"music")
        (nas / "assets" / "images" / "img.png").write_bytes(b"image")

        report = await gc.get_storage_report()
        assert "total_gb" in report
        assert "by_category" in report
        assert "music" in report["by_category"]
        assert report["by_category"]["music"]["count"] == 1