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

import asyncio
import hashlib
import shutil
from pathlib import Path

import aiofiles
import orjson
import structlog

from omnicast.shared.errors import StorageError

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
        try:
            await asyncio.to_thread(path.parent.mkdir, parents=True, exist_ok=True)
            tmp_path = path.with_suffix(path.suffix + ".tmp")
            async with aiofiles.open(tmp_path, "wb") as f:
                await f.write(data)
            await asyncio.to_thread(tmp_path.rename, path)
            logger.info("Written bytes to file", bytes=len(data), filename=path.name)
        except Exception as e:
            raise StorageError(f"Failed to write binary to {path}: {e}") from e

    async def write_text(self, path: Path, text: str, encoding: str = "utf-8") -> None:
        """Write text to file. Same atomic pattern as write_binary."""
        try:
            await asyncio.to_thread(path.parent.mkdir, parents=True, exist_ok=True)
            tmp_path = path.with_suffix(path.suffix + ".tmp")
            async with aiofiles.open(tmp_path, "w", encoding=encoding) as f:
                await f.write(text)
            await asyncio.to_thread(tmp_path.rename, path)
            logger.info("Written chars to file", chars=len(text), filename=path.name)
        except Exception as e:
            raise StorageError(f"Failed to write text to {path}: {e}") from e

    async def read_binary(self, path: Path) -> bytes:
        """Read binary file.

        Raises:
            StorageError: if file not found or read error
        """
        try:
            async with aiofiles.open(path, "rb") as f:
                return await f.read()
        except FileNotFoundError as e:
            raise StorageError(f"File not found: {path}") from e
        except Exception as e:
            raise StorageError(f"Failed to read binary from {path}: {e}") from e

    async def read_text(self, path: Path, encoding: str = "utf-8") -> str:
        """Read text file.

        Raises:
            StorageError: if file not found or read error
        """
        try:
            async with aiofiles.open(path, "r", encoding=encoding) as f:
                return await f.read()
        except FileNotFoundError as e:
            raise StorageError(f"File not found: {path}") from e
        except Exception as e:
            raise StorageError(f"Failed to read text from {path}: {e}") from e

    async def read_json(self, path: Path) -> dict:
        """Read and parse JSON file using orjson.

        Raises:
            StorageError: if file not found, read error, or invalid JSON
        """
        try:
            content = await self.read_text(path)
            return orjson.loads(content)
        except StorageError:
            raise
        except orjson.JSONDecodeError as e:
            raise StorageError(f"Invalid JSON in {path}: {e}") from e

    async def write_json(self, path: Path, data: dict) -> None:
        """Serialize dict to JSON and write. Use orjson with OPT_INDENT_2."""
        text = orjson.dumps(
            data, option=orjson.OPT_INDENT_2 | orjson.OPT_SORT_KEYS
        ).decode("utf-8")
        await self.write_text(path, text)

    async def delete(self, path: Path) -> bool:
        """Delete file. Return True if deleted, False if not found.

        Log: "Deleted {path.name}"
        """
        try:
            await asyncio.to_thread(path.unlink)
            logger.info("Deleted file", filename=path.name)
            return True
        except FileNotFoundError:
            return False
        except Exception as e:
            raise StorageError(f"Failed to delete {path}: {e}") from e

    async def move(self, src: Path, dst: Path) -> None:
        """Move/rename file.

        Implementation:
        1. Ensure dst parent exists
        2. If same filesystem → rename (atomic)
        3. If cross-filesystem → copy + delete source

        Raises:
            StorageError: if source not found
        """
        try:
            if not await asyncio.to_thread(src.exists):
                raise StorageError(f"Source not found: {src}")
            await asyncio.to_thread(dst.parent.mkdir, parents=True, exist_ok=True)
            try:
                await asyncio.to_thread(src.rename, dst)
            except OSError:
                # Cross-filesystem: copy + delete
                await self.copy(src, dst)
                await self.delete(src)
            logger.info("Moved %s → %s", src.name, dst.name)
        except StorageError:
            raise
        except Exception as e:
            raise StorageError(f"Failed to move {src} → {dst}: {e}") from e

    async def copy(self, src: Path, dst: Path) -> None:
        """Copy file. Ensure dst parent exists.

        Use asyncio.to_thread(shutil.copy2, src, dst) to preserve metadata.
        """
        try:
            await asyncio.to_thread(dst.parent.mkdir, parents=True, exist_ok=True)
            await asyncio.to_thread(shutil.copy2, src, dst)
            logger.info("Copied file", src=src.name, dst=dst.name)
        except Exception as e:
            raise StorageError(f"Failed to copy {src} → {dst}: {e}") from e

    async def exists(self, path: Path) -> bool:
        """Check if file exists. Non-blocking."""
        return await asyncio.to_thread(path.exists)

    async def file_size(self, path: Path) -> int:
        """Return file size in bytes. Raise StorageError if not found."""
        try:
            stat = await asyncio.to_thread(path.stat)
            return stat.st_size
        except FileNotFoundError as e:
            raise StorageError(f"File not found: {path}") from e
        except Exception as e:
            raise StorageError(f"Failed to stat {path}: {e}") from e

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
        hasher = hashlib.md5()
        async with aiofiles.open(path, "rb") as f:
            while chunk := await f.read(8192):
                hasher.update(chunk)
        return hasher.hexdigest()

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
        def _glob() -> list[Path]:
            if recursive:
                files = list(directory.rglob(pattern))
            else:
                files = list(directory.glob(pattern))
            return sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)

        return await asyncio.to_thread(_glob)

    async def disk_usage(self, path: Path) -> dict[str, int]:
        """Return disk usage stats for path's filesystem.

        Use asyncio.to_thread(shutil.disk_usage, path).
        Return {"total": int, "used": int, "free": int} in bytes.
        """
        usage = await asyncio.to_thread(shutil.disk_usage, path)
        return {"total": usage.total, "used": usage.used, "free": usage.free}