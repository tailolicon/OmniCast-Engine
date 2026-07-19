"""SQLite-backed executions log for the Kestra-lite pipeline runner.

Persists every pipeline execution (status, per-step results, error) to vault.db
so operators can answer "what ran, when, and did it succeed?".
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, UTC
from pathlib import Path

import structlog

logger = structlog.get_logger()

_DEFAULT_DB: Path | None = None


def _db(path: Path | None = None) -> Path:
    if path:
        return path
    if _DEFAULT_DB:
        return _DEFAULT_DB
    from pathlib import Path as _P
    return _P(__file__).resolve().parents[4] / "output" / "vault.db"


def init_executions_table(db_path: Path | None = None) -> None:
    """Create pipeline_executions table if it doesn't exist."""
    with sqlite3.connect(str(_db(db_path))) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS pipeline_executions (
                execution_id  TEXT PRIMARY KEY,
                pipeline_id   TEXT NOT NULL,
                channel_id    TEXT,
                status        TEXT NOT NULL DEFAULT 'running',
                started_at    TEXT NOT NULL,
                finished_at   TEXT,
                inputs_json   TEXT NOT NULL DEFAULT '{}',
                steps_json    TEXT NOT NULL DEFAULT '{}',
                error         TEXT
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_pe_pipeline_id
                ON pipeline_executions (pipeline_id, started_at DESC)
        """)
        conn.commit()


def upsert_execution(execution, db_path: Path | None = None) -> None:
    """Insert or update an Execution record."""
    from omnicast.pipeline.models import Execution
    ex: Execution = execution
    init_executions_table(db_path)
    with sqlite3.connect(str(_db(db_path))) as conn:
        conn.execute("""
            INSERT INTO pipeline_executions
                (execution_id, pipeline_id, channel_id, status,
                 started_at, finished_at, inputs_json, steps_json, error)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(execution_id) DO UPDATE SET
                status       = excluded.status,
                finished_at  = excluded.finished_at,
                steps_json   = excluded.steps_json,
                error        = excluded.error
        """, (
            ex.execution_id,
            ex.pipeline_id,
            ex.channel_id,
            ex.status.value,
            ex.started_at.isoformat(),
            ex.finished_at.isoformat() if ex.finished_at else None,
            json.dumps(ex.inputs, ensure_ascii=False),
            json.dumps(
                {k: v.model_dump(mode="json") for k, v in ex.steps.items()},
                ensure_ascii=False,
            ),
            ex.error,
        ))
        conn.commit()


def list_executions(
    pipeline_id: str | None = None,
    channel_id: str | None = None,
    limit: int = 50,
    db_path: Path | None = None,
) -> list[dict]:
    """Return recent execution summaries (newest first)."""
    init_executions_table(db_path)
    clauses, params = [], []
    if pipeline_id:
        clauses.append("pipeline_id = ?")
        params.append(pipeline_id)
    if channel_id:
        clauses.append("channel_id = ?")
        params.append(channel_id)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(limit)
    with sqlite3.connect(str(_db(db_path))) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            f"""SELECT execution_id, pipeline_id, channel_id, status,
                       started_at, finished_at, error
                FROM pipeline_executions {where}
                ORDER BY started_at DESC LIMIT ?""",
            params,
        ).fetchall()
    return [dict(r) for r in rows]


def get_execution(execution_id: str, db_path: Path | None = None) -> dict | None:
    """Return full execution record including steps_json."""
    init_executions_table(db_path)
    with sqlite3.connect(str(_db(db_path))) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM pipeline_executions WHERE execution_id = ?",
            (execution_id,),
        ).fetchone()
    if not row:
        return None
    d = dict(row)
    d["inputs"] = json.loads(d.pop("inputs_json", "{}"))
    d["steps"] = json.loads(d.pop("steps_json", "{}"))
    return d
