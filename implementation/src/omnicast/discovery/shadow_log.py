"""Append-only shadow-scoring telemetry.

WHY THIS EXISTS

`scoring_calibration` can only answer "may v2 decide?" from a corpus of real
discovery runs. That corpus did not exist: `shadow_row()` had no production
caller, the `topics` table stores a single `score` column, and `DiscoveryResult`
lives in memory for the length of one request. So "v2 is recorded on every
topic" was true only of a temporary object — nothing survived to calibrate on.

This writes one JSON line per scored topic, per run. JSONL rather than a new
table on purpose:

  * it is append-only, so two concurrent discovery runs cannot lose each
    other's rows the way a read-modify-write row would;
  * a malformed line costs one row, not the file (and `summarize` counts
    dropped rows rather than raising);
  * it can be moved, diffed and shipped to a notebook without a migration.

`decided_by` is the part that matters most. On the main API path the router
that actually picks the topic is `ChannelArchitectAgent`, not `TopicScorer` —
so a corpus that recorded only the scorer's lane would calibrate a decision
nobody makes. Every row therefore carries which component ranked it and, once
known, whether that component actually selected the topic.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import structlog

from omnicast.discovery.scoring_calibration import shadow_row

logger = structlog.get_logger()

DEFAULT_LOG_NAME = "shadow_scoring.jsonl"
# One run of one channel writes at most a few hundred rows; this bounds the file
# at roughly a few hundred MB before an operator has to rotate it.
MAX_LOG_BYTES = 256 * 1024 * 1024


def default_log_path() -> Path:
    root = Path(__file__).resolve().parents[3] / "output"
    return root / DEFAULT_LOG_NAME


def append_rows(rows: list[dict], path: Path | None = None) -> int:
    """Append rows as JSONL. Returns how many were written.

    Never raises: telemetry that can break a discovery run is worse than
    telemetry that is missing, and the caller has no way to recover anyway."""
    if not rows:
        return 0
    target = Path(path) if path else default_log_path()
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and target.stat().st_size > MAX_LOG_BYTES:
            logger.warning("shadow log is full; rotate or archive it",
                           path=str(target), limit_bytes=MAX_LOG_BYTES)
            return 0
        payload = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)
        # Single append write: O_APPEND makes concurrent writers interleave
        # whole lines rather than corrupt each other.
        with open(target, "a", encoding="utf-8") as handle:
            handle.write(payload)
        return len(rows)
    except Exception as exc:
        logger.warning("shadow log write failed", path=str(target), error=str(exc))
        return 0


def rows_for_run(scored, *, channel_id: str = "", run_id: str = "",
                 decided_by: str = "topic_scorer", now: datetime | None = None
                 ) -> list[dict]:
    """Build calibration rows for one discovery run."""
    stamp = (now or datetime.now(timezone.utc)).isoformat()
    out: list[dict] = []
    for item in scored:
        try:
            row = shadow_row(item)
        except Exception as exc:
            logger.warning("shadow row skipped", error=str(exc))
            continue
        row.update({
            "logged_at": stamp,
            "channel_id": channel_id,
            "discovery_run_id": run_id,
            "scoring_version": getattr(item, "scoring_version", ""),
            "scorer_action": getattr(item, "action", ""),
            # Which component's ranking actually routes this topic. See the
            # module docstring: on the main API path it is not the scorer.
            "decided_by": decided_by,
            # Filled in by `mark_selected` once the real router has chosen.
            "selected": None,
        })
        out.append(row)
    return out


def mark_selected(rows: list[dict], selected_titles, decided_by: str) -> list[dict]:
    """Record which topics the REAL router picked.

    Without this the corpus can say how the two scoring generations would have
    ranked topics, but not whether either ranking matched what got produced."""
    wanted = {str(t).strip().lower() for t in selected_titles if str(t).strip()}
    for row in rows:
        row["decided_by"] = decided_by
        row["selected"] = str(row.get("title", "")).strip().lower() in wanted
    return rows


def read_rows(path: Path | None = None) -> list[dict]:
    """Load a shadow log. Malformed lines are skipped and counted, not fatal."""
    target = Path(path) if path else default_log_path()
    if not target.exists():
        return []
    rows: list[dict] = []
    skipped = 0
    with open(target, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                parsed = json.loads(line)
            except Exception:
                skipped += 1
                continue
            if isinstance(parsed, dict):
                rows.append(parsed)
            else:
                skipped += 1
    if skipped:
        logger.warning("shadow log had unreadable lines", skipped=skipped,
                       path=str(target))
    return rows


def write_snapshot(rows: list[dict], path: Path) -> None:
    """Atomically write a filtered corpus (used by calibration tooling)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as out:
            for row in rows:
                out.write(json.dumps(row, ensure_ascii=False) + "\n")
        os.replace(tmp, path)
    except Exception:
        Path(tmp).unlink(missing_ok=True)
        raise
