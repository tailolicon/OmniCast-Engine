"""SQLite store for the Job Engine (M0).

Owns the M0 tables in the SAME vault.db SSOT (jobs, job_steps, checkpoints,
assets, worker_slots, events). Additive-only: creating/using these tables does
not touch the existing niche vault or pipeline_executions tables.

Style matches omnicast/vault/db.py (WAL + foreign_keys) and
omnicast/pipeline/executions.py (functional, dict rows, db_path override).
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from omnicast.jobengine.models import JobSpec, JobStatus

# Same SSOT path as vault/db.py and pipeline/executions.py.
_DEFAULT_PATH = Path(__file__).resolve().parents[4] / "output" / "vault.db"


def _db(path: Path | None = None) -> Path:
    return path or _DEFAULT_PATH


def _connect(path: Path | None = None) -> sqlite3.Connection:
    p = _db(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Schema ────────────────────────────────────────────────────────────────────

_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
  job_id         TEXT PRIMARY KEY,
  type           TEXT NOT NULL,
  status         TEXT NOT NULL DEFAULT 'queued',
  resource_class TEXT NOT NULL DEFAULT 'cpu',
  priority       INTEGER NOT NULL DEFAULT 3,
  spec_json      TEXT NOT NULL DEFAULT '{}',
  parent_job_id  TEXT,
  attempt        INTEGER NOT NULL DEFAULT 0,
  error          TEXT,
  created_at     TEXT NOT NULL,
  started_at     TEXT,
  finished_at    TEXT
);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status, created_at);
CREATE INDEX IF NOT EXISTS idx_jobs_parent ON jobs(parent_job_id);

CREATE TABLE IF NOT EXISTS job_steps (
  job_id     TEXT NOT NULL REFERENCES jobs(job_id),
  idx        INTEGER NOT NULL,
  name       TEXT NOT NULL,
  status     TEXT NOT NULL DEFAULT 'pending',
  attempt    INTEGER NOT NULL DEFAULT 0,
  error      TEXT,
  started_at TEXT,
  finished_at TEXT,
  PRIMARY KEY (job_id, idx)
);

CREATE TABLE IF NOT EXISTS checkpoints (
  job_id          TEXT NOT NULL,
  step            TEXT NOT NULL,
  idempotency_key TEXT NOT NULL,
  output_ref      TEXT,
  output_json     TEXT NOT NULL DEFAULT '{}',
  created_at      TEXT NOT NULL,
  PRIMARY KEY (job_id, step)
);
CREATE INDEX IF NOT EXISTS idx_ckpt_idem ON checkpoints(idempotency_key);

CREATE TABLE IF NOT EXISTS assets (
  asset_id    TEXT PRIMARY KEY,
  kind        TEXT NOT NULL,
  job_id      TEXT,
  storage_ref TEXT NOT NULL,
  sha256      TEXT,
  size_bytes  INTEGER NOT NULL DEFAULT 0,
  state       TEXT NOT NULL DEFAULT 'active',
  ttl_at      TEXT,
  created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_assets_ttl ON assets(state, ttl_at);
CREATE INDEX IF NOT EXISTS idx_assets_sha ON assets(sha256);

CREATE TABLE IF NOT EXISTS worker_slots (
  worker_id  TEXT PRIMARY KEY,
  slots_gpu  INTEGER NOT NULL DEFAULT 0,
  slots_cpu  INTEGER NOT NULL DEFAULT 4,
  slots_net  INTEGER NOT NULL DEFAULT 8,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS events (
  event_id     INTEGER PRIMARY KEY AUTOINCREMENT,
  ts           TEXT NOT NULL,
  type         TEXT NOT NULL,
  job_id       TEXT,
  payload_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts);
"""


def init_jobengine_schema(db_path: Path | None = None) -> None:
    """Create all Job Engine tables if they don't exist (idempotent)."""
    with _connect(db_path) as conn:
        conn.executescript(_SCHEMA)
        conn.commit()


# ── Jobs ──────────────────────────────────────────────────────────────────────

def insert_job(spec: JobSpec, db_path: Path | None = None) -> str:
    init_jobengine_schema(db_path)
    with _connect(db_path) as conn:
        conn.execute(
            """INSERT INTO jobs
                 (job_id, type, status, resource_class, priority, spec_json,
                  parent_job_id, attempt, created_at)
               VALUES (?,?,?,?,?,?,?,0,?)""",
            (spec.job_id, spec.type, JobStatus.QUEUED.value,
             spec.resource_class.value, spec.priority,
             json.dumps(spec.payload, ensure_ascii=False),
             spec.parent_job_id, _now()),
        )
        conn.commit()
    return spec.job_id


def get_job(job_id: str, db_path: Path | None = None) -> dict | None:
    init_jobengine_schema(db_path)
    with _connect(db_path) as conn:
        row = conn.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
    if not row:
        return None
    d = dict(row)
    d["payload"] = json.loads(d.pop("spec_json", "{}"))
    return d


def set_job_status(
    job_id: str,
    status: JobStatus | str,
    *,
    error: str | None = None,
    mark_started: bool = False,
    mark_finished: bool = False,
    attempt: int | None = None,
    db_path: Path | None = None,
) -> None:
    init_jobengine_schema(db_path)
    sval = status.value if isinstance(status, JobStatus) else status
    sets = ["status=?"]
    params: list[Any] = [sval]
    if error is not None:
        sets.append("error=?"); params.append(error)
    if mark_started:
        sets.append("started_at=?"); params.append(_now())
    if mark_finished:
        sets.append("finished_at=?"); params.append(_now())
    if attempt is not None:
        sets.append("attempt=?"); params.append(attempt)
    params.append(job_id)
    with _connect(db_path) as conn:
        conn.execute(f"UPDATE jobs SET {', '.join(sets)} WHERE job_id=?", params)
        conn.commit()


def list_jobs(status: str | None = None, limit: int = 50, db_path: Path | None = None) -> list[dict]:
    init_jobengine_schema(db_path)
    where, params = "", []
    if status:
        where = "WHERE status=?"; params.append(status)
    params.append(limit)
    with _connect(db_path) as conn:
        rows = conn.execute(
            f"SELECT * FROM jobs {where} ORDER BY created_at DESC LIMIT ?", params
        ).fetchall()
    return [dict(r) for r in rows]


# ── Steps ─────────────────────────────────────────────────────────────────────

def upsert_step(
    job_id: str, idx: int, name: str, status: str,
    *, attempt: int = 0, error: str | None = None,
    mark_started: bool = False, mark_finished: bool = False,
    db_path: Path | None = None,
) -> None:
    init_jobengine_schema(db_path)
    started = _now() if mark_started else None
    finished = _now() if mark_finished else None
    with _connect(db_path) as conn:
        conn.execute(
            """INSERT INTO job_steps (job_id, idx, name, status, attempt, error, started_at, finished_at)
               VALUES (?,?,?,?,?,?,?,?)
               ON CONFLICT(job_id, idx) DO UPDATE SET
                 name=excluded.name, status=excluded.status, attempt=excluded.attempt,
                 error=excluded.error,
                 started_at=COALESCE(job_steps.started_at, excluded.started_at),
                 finished_at=excluded.finished_at""",
            (job_id, idx, name, status, attempt, error, started, finished),
        )
        conn.commit()


def get_steps(job_id: str, db_path: Path | None = None) -> list[dict]:
    init_jobengine_schema(db_path)
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM job_steps WHERE job_id=? ORDER BY idx", (job_id,)
        ).fetchall()
    return [dict(r) for r in rows]


# ── Checkpoints ───────────────────────────────────────────────────────────────

def save_checkpoint(
    job_id: str, step: str, idempotency_key: str,
    output_ref: str | None, output: dict | None = None,
    db_path: Path | None = None,
) -> None:
    init_jobengine_schema(db_path)
    with _connect(db_path) as conn:
        conn.execute(
            """INSERT INTO checkpoints (job_id, step, idempotency_key, output_ref, output_json, created_at)
               VALUES (?,?,?,?,?,?)
               ON CONFLICT(job_id, step) DO UPDATE SET
                 idempotency_key=excluded.idempotency_key,
                 output_ref=excluded.output_ref, output_json=excluded.output_json""",
            (job_id, step, idempotency_key, output_ref,
             json.dumps(output or {}, ensure_ascii=False), _now()),
        )
        conn.commit()


def get_checkpoint(job_id: str, step: str, db_path: Path | None = None) -> dict | None:
    init_jobengine_schema(db_path)
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM checkpoints WHERE job_id=? AND step=?", (job_id, step)
        ).fetchone()
    if not row:
        return None
    d = dict(row)
    d["output"] = json.loads(d.pop("output_json", "{}"))
    return d


# ── Assets ────────────────────────────────────────────────────────────────────

def register_asset(
    *, kind: str, storage_ref: str, job_id: str | None = None,
    sha256: str | None = None, size_bytes: int = 0, ttl_at: str | None = None,
    db_path: Path | None = None,
) -> str:
    """Register an asset. If `sha256` matches an existing ACTIVE asset, return
    that asset_id (dedup) instead of inserting a duplicate."""
    init_jobengine_schema(db_path)
    if sha256:
        existing = find_asset_by_sha(sha256, db_path=db_path)
        if existing:
            return existing["asset_id"]
    asset_id = uuid.uuid4().hex
    with _connect(db_path) as conn:
        conn.execute(
            """INSERT INTO assets
                 (asset_id, kind, job_id, storage_ref, sha256, size_bytes, state, ttl_at, created_at)
               VALUES (?,?,?,?,?,?,'active',?,?)""",
            (asset_id, kind, job_id, storage_ref, sha256, size_bytes, ttl_at, _now()),
        )
        conn.commit()
    return asset_id


def get_asset(asset_id: str, db_path: Path | None = None) -> dict | None:
    init_jobengine_schema(db_path)
    with _connect(db_path) as conn:
        row = conn.execute("SELECT * FROM assets WHERE asset_id=?", (asset_id,)).fetchone()
    return dict(row) if row else None


def find_asset_by_sha(sha256: str, db_path: Path | None = None) -> dict | None:
    init_jobengine_schema(db_path)
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM assets WHERE sha256=? AND state='active' ORDER BY created_at LIMIT 1",
            (sha256,),
        ).fetchone()
    return dict(row) if row else None


def assets_due_for_gc(now: str | None = None, db_path: Path | None = None) -> list[dict]:
    """Assets eligible for GC: not already deleted AND ttl_at set AND in the past.
    Master assets with ttl_at IS NULL are never returned."""
    init_jobengine_schema(db_path)
    now = now or _now()
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM assets WHERE state!='deleted' AND ttl_at IS NOT NULL AND ttl_at < ?",
            (now,),
        ).fetchall()
    return [dict(r) for r in rows]


def mark_asset_deleted(asset_id: str, db_path: Path | None = None) -> None:
    init_jobengine_schema(db_path)
    with _connect(db_path) as conn:
        conn.execute("UPDATE assets SET state='deleted' WHERE asset_id=?", (asset_id,))
        conn.commit()


# ── Worker slots (static config) ──────────────────────────────────────────────

def upsert_worker_slots(worker_id: str, *, slots_gpu: int, slots_cpu: int, slots_net: int,
                        db_path: Path | None = None) -> None:
    init_jobengine_schema(db_path)
    with _connect(db_path) as conn:
        conn.execute(
            """INSERT INTO worker_slots (worker_id, slots_gpu, slots_cpu, slots_net, updated_at)
               VALUES (?,?,?,?,?)
               ON CONFLICT(worker_id) DO UPDATE SET
                 slots_gpu=excluded.slots_gpu, slots_cpu=excluded.slots_cpu,
                 slots_net=excluded.slots_net, updated_at=excluded.updated_at""",
            (worker_id, slots_gpu, slots_cpu, slots_net, _now()),
        )
        conn.commit()


def get_worker_slots(worker_id: str, db_path: Path | None = None) -> dict | None:
    init_jobengine_schema(db_path)
    with _connect(db_path) as conn:
        row = conn.execute("SELECT * FROM worker_slots WHERE worker_id=?", (worker_id,)).fetchone()
    return dict(row) if row else None


# ── Events ────────────────────────────────────────────────────────────────────

def append_event(type: str, *, job_id: str | None = None, payload: dict | None = None,
                 db_path: Path | None = None) -> int:
    init_jobengine_schema(db_path)
    with _connect(db_path) as conn:
        cur = conn.execute(
            "INSERT INTO events (ts, type, job_id, payload_json) VALUES (?,?,?,?)",
            (_now(), type, job_id, json.dumps(payload or {}, ensure_ascii=False)),
        )
        conn.commit()
        return int(cur.lastrowid)


def list_events(since_id: int = 0, limit: int = 100, db_path: Path | None = None) -> list[dict]:
    init_jobengine_schema(db_path)
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM events WHERE event_id > ? ORDER BY event_id LIMIT ?",
            (since_id, limit),
        ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["payload"] = json.loads(d.pop("payload_json", "{}"))
        out.append(d)
    return out
