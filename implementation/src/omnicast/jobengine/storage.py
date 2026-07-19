"""IStorage abstraction + LocalDiskStorage (M0, PR2).

Domain code stores blobs (audio, images, renders) through IStorage instead of
raw os.path, so the backend can switch from local disk to S3/MinIO/R2 for
multi-worker setups without touching callers. Sync API for M0 simplicity.
StorageRef format: "local://<relpath>" (or "s3://bucket/key" for future backends).
"""

from __future__ import annotations

import hashlib
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol


def _sha256_file(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


class IStorage(Protocol):
    scheme: str
    def put(self, src_path: str, *, kind: str) -> str: ...
    def put_bytes(self, data: bytes, *, name: str, kind: str) -> str: ...
    def get(self, ref: str) -> str: ...        # returns a usable local path
    def url(self, ref: str) -> str: ...         # file:// or presigned URL for the UI
    def exists(self, ref: str) -> bool: ...
    def delete(self, ref: str) -> None: ...
    def sha256(self, ref: str) -> str: ...


class LocalDiskStorage:
    """IStorage backed by a local directory tree (default M0 backend)."""

    scheme = "local"

    def __init__(self, root: str):
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)

    def _rel(self, ref):
        s = str(ref)
        return s[len("local://"):] if s.startswith("local://") else s

    def _abs(self, ref):
        return self._root / self._rel(ref)

    def _newrel(self, kind, suffix):
        return f"{kind}/{datetime.now(timezone.utc).strftime('%Y/%m')}/{uuid.uuid4().hex}{suffix}"

    def put(self, src_path, *, kind):
        rel = self._newrel(kind, Path(src_path).suffix)
        dst = self._root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src_path, dst)
        return "local://" + rel

    def put_bytes(self, data, *, name, kind):
        rel = self._newrel(kind, "_" + name)
        dst = self._root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(data)
        return "local://" + rel

    def get(self, ref):
        return str(self._abs(ref))

    def url(self, ref):
        return self._abs(ref).as_uri()

    def exists(self, ref):
        return self._abs(ref).exists()

    def delete(self, ref):
        p = self._abs(ref)
        if p.exists():
            p.unlink()

    def sha256(self, ref):
        return _sha256_file(self._abs(ref))
