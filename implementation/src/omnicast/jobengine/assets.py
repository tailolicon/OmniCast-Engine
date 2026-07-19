"""Asset Registry + Garbage Collector (M0, PR3).

Wraps IStorage + the assets table: registers every generated file (dedup by
sha256), and a GC pass deletes files whose ttl has passed. Master assets carry
ttl=None and are never collected (M0 policy).
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from pathlib import Path

from omnicast.jobengine import store


class AssetService:
    def __init__(self, storage, db_path=None):
        self._st = storage
        self._db = db_path

    def register_file(self, local_path, *, kind, job_id=None, ttl_s=None):
        """Store a file via IStorage and register it. If an active asset with the
        same content (sha256) exists, drop the new copy and return the existing id."""
        ref = self._st.put(local_path, kind=kind)
        sha = self._st.sha256(ref)
        existing = store.find_asset_by_sha(sha, db_path=self._db)
        if existing:
            self._st.delete(ref)
            return existing["asset_id"]
        size = Path(self._st.get(ref)).stat().st_size
        ttl_at = None if ttl_s is None else (
            datetime.now(timezone.utc) + timedelta(seconds=ttl_s)).isoformat()
        return store.register_asset(kind=kind, storage_ref=ref, job_id=job_id,
                                    sha256=sha, size_bytes=size, ttl_at=ttl_at, db_path=self._db)

    def get(self, asset_id):
        return store.get_asset(asset_id, db_path=self._db)

    def gc(self, now=None) -> int:
        """Delete + mark every asset past its ttl. Returns count collected."""
        due = store.assets_due_for_gc(now=now, db_path=self._db)
        n = 0
        for a in due:
            try:
                self._st.delete(a["storage_ref"])
            except Exception:
                pass
            store.mark_asset_deleted(a["asset_id"], db_path=self._db)
            n += 1
        return n
