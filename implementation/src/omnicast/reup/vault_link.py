"""Register reup jobs in `output/vault.db`.

The per-job `project.db` is working state — its data layer assumes one project
per file, so it cannot be merged into the vault. What belongs in the vault is
the job's lifecycle: which Douyin post was pulled, where its workspace lives,
how far it got, and whether it is waiting on human review. That is the part
other parts of OmniCast need to query.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from omnicast.vault.db import _connect

SCHEMA = """
CREATE TABLE IF NOT EXISTS reup_jobs (
    job_id TEXT PRIMARY KEY,
    source_platform TEXT NOT NULL DEFAULT 'douyin',
    source_url TEXT NOT NULL,
    aweme_id TEXT,
    title TEXT,
    title_vi TEXT,
    tags_vi TEXT,
    author_name TEXT,
    channel_id TEXT,
    project_id TEXT,
    project_root TEXT,
    source_video_path TEXT,
    exported_video_path TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    last_stage TEXT,
    segment_count INTEGER DEFAULT 0,
    review_pending INTEGER DEFAULT 0,
    voice_preset_id TEXT,
    error TEXT,
    extra_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_reup_jobs_status ON reup_jobs(status);
CREATE INDEX IF NOT EXISTS idx_reup_jobs_aweme ON reup_jobs(aweme_id);
-- One project legitimately has many job rows: resuming to run a later stage is
-- a new run against the same workspace. An earlier UNIQUE index here made the
-- second run die with an IntegrityError instead of recording progress.
DROP INDEX IF EXISTS idx_reup_jobs_project;
CREATE INDEX IF NOT EXISTS idx_reup_jobs_project ON reup_jobs(project_id);
"""


@dataclass(slots=True)
class ReupJobRow:
    job_id: str
    source_url: str
    status: str
    aweme_id: str | None = None
    title: str | None = None
    title_vi: str | None = None
    project_root: str | None = None
    exported_video_path: str | None = None
    review_pending: int = 0
    last_stage: str | None = None
    # Surfaced so the UI can say how long a job has been on its current stage.
    # Without these a five-minute download is indistinguishable from a hang.
    created_at: str | None = None
    updated_at: str | None = None
    # Without this the job list can show a red "failed" badge and nothing else
    # — the operator has to open the database to learn why.
    error: str | None = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def init_reup_tables(path: Path | None = None) -> None:
    with _connect(path) as conn:
        conn.executescript(SCHEMA)
        # Added after the first jobs were recorded; ALTER keeps those rows.
        existing = {r[1] for r in conn.execute("PRAGMA table_info(reup_jobs)")}
        for column in ("title_vi", "tags_vi"):
            if column not in existing:
                conn.execute(f"ALTER TABLE reup_jobs ADD COLUMN {column} TEXT")


def register_job(
    job_id: str,
    source_url: str,
    *,
    channel_id: str | None = None,
    voice_preset_id: str | None = None,
    path: Path | None = None,
) -> None:
    """Record a job before any work starts, so a crash still leaves a trace.

    source_platform is stamped from the URL right here — every caller (API,
    CLI, runner re-register) goes through this function, so none of them can
    forget to say which site the link belongs to.
    """
    from omnicast.ingest.detect import detect_source_platform

    init_reup_tables(path)
    now = _now()
    with _connect(path) as conn:
        conn.execute(
            """
            INSERT INTO reup_jobs
                (job_id, source_url, source_platform, channel_id, voice_preset_id,
                 status, created_at, updated_at)
            VALUES (?,?,?,?,?,'pending',?,?)
            ON CONFLICT(job_id) DO UPDATE SET
                source_url=excluded.source_url,
                source_platform=excluded.source_platform,
                channel_id=excluded.channel_id,
                voice_preset_id=excluded.voice_preset_id,
                updated_at=excluded.updated_at
            """,
            (job_id, source_url, detect_source_platform(source_url),
             channel_id, voice_preset_id, now, now),
        )


def update_job(
    job_id: str,
    *,
    status: str | None = None,
    last_stage: str | None = None,
    error: str | None = None,
    result: object | None = None,
    exported_video: Path | None = None,
    path: Path | None = None,
) -> None:
    """Patch a job row. `result` accepts a `ReupJobResult`.

    `exported_video` is for re-exports, which produce a new file without a full
    `ReupJobResult` to hand over — passing a stub result instead would blank
    every other column on the row.
    """
    fields: dict[str, object] = {"updated_at": _now()}
    if status is not None:
        fields["status"] = status
    if last_stage is not None:
        fields["last_stage"] = last_stage
    if error is not None:
        fields["error"] = error
    if exported_video is not None:
        fields["exported_video_path"] = str(exported_video)

    if result is not None:
        asset = getattr(result, "asset", None)
        fields.update(
            {
                "project_id": getattr(result, "project_id", None),
                "project_root": str(getattr(result, "project_root", "") or "") or None,
                "source_video_path": str(getattr(result, "source_video", "") or "") or None,
                "exported_video_path": str(getattr(result, "exported_video", "") or "") or None,
                "segment_count": int(getattr(result, "segment_count", 0) or 0),
                "title_vi": getattr(result, "title_vi", "") or None,
                "tags_vi": json.dumps(
                    list(getattr(result, "tags_vi", []) or []), ensure_ascii=False
                ),
                "review_pending": int(getattr(result, "review_pending", 0) or 0),
                "extra_json": json.dumps(
                    {
                        "stages_run": list(getattr(result, "stages_run", []) or []),
                        "subtitle_paths": [
                            str(p) for p in (getattr(result, "subtitle_paths", []) or [])
                        ],
                        "voice_track": str(getattr(result, "voice_track", "") or "") or None,
                        "mixed_audio": str(getattr(result, "mixed_audio", "") or "") or None,
                    },
                    ensure_ascii=False,
                ),
            }
        )
        if asset is not None:
            fields.update(
                {
                    "aweme_id": getattr(asset, "aweme_id", None),
                    "title": getattr(asset, "title", None),
                    "author_name": getattr(asset, "author_name", None),
                }
            )

    assignments = ", ".join(f"{key}=?" for key in fields)
    init_reup_tables(path)
    with _connect(path) as conn:
        conn.execute(
            f"UPDATE reup_jobs SET {assignments} WHERE job_id=?",
            (*fields.values(), job_id),
        )


def list_jobs(
    *, status: str | None = None, limit: int = 50, path: Path | None = None
) -> list[ReupJobRow]:
    init_reup_tables(path)
    query = (
        "SELECT job_id, source_url, status, aweme_id, title, title_vi, project_root, "
        "exported_video_path, review_pending, last_stage, created_at, updated_at, error "
        "FROM reup_jobs"
    )
    params: tuple[object, ...] = ()
    if status:
        query += " WHERE status=?"
        params = (status,)
    query += " ORDER BY created_at DESC LIMIT ?"
    params = (*params, limit)

    with _connect(path) as conn:
        rows: list[sqlite3.Row] = conn.execute(query, params).fetchall()
    return [ReupJobRow(**dict(row)) for row in rows]


def get_job(job_id: str, *, path: Path | None = None) -> dict[str, object] | None:
    init_reup_tables(path)
    with _connect(path) as conn:
        row = conn.execute("SELECT * FROM reup_jobs WHERE job_id=?", (job_id,)).fetchone()
    return dict(row) if row else None
