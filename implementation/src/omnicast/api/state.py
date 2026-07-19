"""Pipeline state manager — reads/writes JSON state files for dashboard API.

State files live in output/ directory:
  output/pipeline_state.json   — active jobs + recent results
  output/niche_results.json    — latest niche discovery output
  output/cost_state.json       — accumulated LLM costs
"""

from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any

# src/omnicast/api/state.py → ../../../../.. = project root = implementation/
# output lives at implementation/../output  (sibling of implementation/)
# Actually keep output INSIDE implementation for easy access
OUTPUT_DIR = Path(__file__).parent.parent.parent.parent / "output"


def _ensure_output() -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    return OUTPUT_DIR


# ─── Pipeline State ──────────────────────────────────────────────────────────

def read_pipeline_state() -> dict:
    f = _ensure_output() / "pipeline_state.json"
    if not f.exists():
        return {"channels": {}, "active_jobs": [], "recent_results": [], "last_updated": None}
    # utf-8-sig tolerates a UTF-8 BOM (e.g. if the file was ever rewritten by a
    # tool that prepends one) so a stray BOM never 500s the whole dashboard.
    try:
        return json.loads(f.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, OSError):
        return {"channels": {}, "active_jobs": [], "recent_results": [], "last_updated": None}


def write_pipeline_event(
    channel_id: str,
    phase: str,          # "discovery" | "writing" | "critique" | "upload"
    status: str,         # "started" | "completed" | "failed"
    topic: str = "",
    score: int = 0,
    cost_usd: float = 0.0,
    extra: dict | None = None,
) -> None:
    """Called from run_pipeline.py at each phase transition."""
    state = read_pipeline_state()
    now = datetime.utcnow().isoformat()

    # Update channel entry
    if channel_id not in state["channels"]:
        state["channels"][channel_id] = {}

    ch = state["channels"][channel_id]
    ch["last_updated"] = now

    if status == "started":
        ch["status"] = f"{phase}_running"
        ch["current_phase"] = phase
        if topic:
            ch["current_topic"] = topic
    elif status == "completed":
        ch["status"] = "idle"
        ch["current_phase"] = None
        if topic:
            ch["last_topic"] = topic
        if score:
            ch["last_score"] = score
        if cost_usd:
            ch["last_cost_usd"] = cost_usd
        ch[f"last_{phase}_at"] = now
    elif status == "failed":
        ch["status"] = "error"
        ch["last_error"] = extra.get("error", "unknown") if extra else "unknown"

    # Add to recent results (keep last 20)
    state["recent_results"].insert(0, {
        "channel_id": channel_id,
        "phase": phase,
        "status": status,
        "topic": topic,
        "score": score,
        "cost_usd": round(cost_usd, 4),
        "ts": now,
        **(extra or {}),
    })
    state["recent_results"] = state["recent_results"][:20]

    state["last_updated"] = now
    _write(OUTPUT_DIR / "pipeline_state.json", state)


def set_active_job(channel_id: str, phase: str, topic: str = "") -> None:
    state = read_pipeline_state()
    # Remove existing job for same channel
    state["active_jobs"] = [j for j in state["active_jobs"] if j.get("channel_id") != channel_id]
    state["active_jobs"].append({
        "channel_id":    channel_id,
        "phase":         phase,
        "topic":         topic,
        "started_at":    datetime.utcnow().isoformat(),
        "stage_history": [],   # populated by set_active_job_progress
    })
    _write(OUTPUT_DIR / "pipeline_state.json", state)


def clear_active_job(channel_id: str) -> None:
    state = read_pipeline_state()
    state["active_jobs"] = [j for j in state["active_jobs"] if j.get("channel_id") != channel_id]
    # Also reset per-channel status so dashboard shows Idle immediately
    if channel_id in state.get("channels", {}):
        ch = state["channels"][channel_id]
        if str(ch.get("status", "")).endswith("_running"):
            ch["status"] = "idle"
            ch["current_phase"] = None
    _write(OUTPUT_DIR / "pipeline_state.json", state)


def set_active_job_progress(
    channel_id: str,
    stage: str,
    pct: int | None = None,
    detail: str | None = None,
) -> None:
    """Attach live stage / percent / detail to an existing active job entry.

    Fail-safe: silently no-ops if the channel has no active job, or on any IO error.
    Operators rely on this for visibility — failure to write progress MUST NOT crash the
    background task that called us.
    """
    try:
        state = read_pipeline_state()
        now = datetime.utcnow().isoformat()
        updated = False
        for job in state.get("active_jobs", []):
            if job.get("channel_id") == channel_id:
                # Only append to history when stage CHANGES (avoids spam on detail-only updates)
                prev_stage = job.get("stage")
                if stage != prev_stage:
                    job.setdefault("stage_history", []).append({
                        "stage": stage,
                        "pct":   max(0, min(100, int(pct))) if pct is not None else None,
                        "at":    now,
                    })
                    # cap stage_history at 20 entries
                    job["stage_history"] = job["stage_history"][-20:]
                job["stage"] = stage
                if pct is not None:
                    job["progress_pct"] = max(0, min(100, int(pct)))
                if detail is not None:
                    job["detail"] = detail
                job["progress_updated_at"] = now
                updated = True
                break
        if updated:
            _write(OUTPUT_DIR / "pipeline_state.json", state)
    except Exception:
        # Operator visibility is best-effort; never propagate to the worker task.
        return


# ─── Error Log ─── append-only ring buffer of last 50 failures ───────────────────
# Operator philosophy rule #4 (No Blackbox): if a background task crashes, the operator
# must be able to read the full traceback IN the dashboard — not have to SSH into the box
# and tail logs. This is that surface.

_ERROR_LOG_MAX = 50


def read_error_log() -> list[dict]:
    f = _ensure_output() / "error_log.json"
    if not f.exists():
        return []
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
        return data.get("errors", []) if isinstance(data, dict) else []
    except Exception:
        return []


def append_error(
    channel_id: str,
    stage: str,
    message: str,
    traceback_str: str = "",
    phase: str = "",
) -> None:
    """Record a background-task failure. Fail-safe: errors writing to the error log
    must never propagate up to the worker (we don't want a bug in OUR logger to mask
    the real bug we're trying to log).
    """
    try:
        errors = read_error_log()
        errors.insert(0, {
            "ts":         datetime.utcnow().isoformat(),
            "channel_id": channel_id,
            "phase":      phase,
            "stage":      stage,
            "message":    str(message)[:500],
            "traceback":  (traceback_str or "")[:4000],
        })
        errors = errors[:_ERROR_LOG_MAX]
        _write(OUTPUT_DIR / "error_log.json", {"errors": errors})
    except Exception:
        return


def clear_error_log() -> None:
    """Operator-triggered cleanup. Used by the 'Clear log' button in the dashboard."""
    try:
        _write(OUTPUT_DIR / "error_log.json", {"errors": []})
    except Exception:
        return


# ─── Niche State ─────────────────────────────────────────────────────────────

def read_niche_results() -> dict:
    f = _ensure_output() / "niche_results.json"
    if not f.exists():
        return {"niches": [], "scanned_at": None, "channels_analyzed": 0}
    return json.loads(f.read_text(encoding="utf-8"))


def write_niche_results(niches: list[dict], channels_analyzed: int) -> None:
    data = {
        "niches": niches,
        "channels_analyzed": channels_analyzed,
        "scanned_at": datetime.utcnow().isoformat(),
    }
    _write(OUTPUT_DIR / "niche_results.json", data)


# ─── Cost State ──────────────────────────────────────────────────────────────

def read_cost_state() -> dict:
    f = _ensure_output() / "cost_state.json"
    if not f.exists():
        return {"today_usd": 0.0, "total_usd": 0.0, "daily_cap_usd": 100.0, "breakdown": []}
    state = json.loads(f.read_text(encoding="utf-8"))
    # Daily rollover: "today_usd" was never reset by date — without this,
    # "Chi phí hôm nay" accumulates forever once cost recording is wired up.
    last = str(state.get("last_updated", ""))[:10]
    today = datetime.utcnow().strftime("%Y-%m-%d")
    if last and last != today and state.get("today_usd"):
        state["today_usd"] = 0.0
    return state


def accumulate_cost(amount_usd: float, category: str = "LLM") -> None:
    state = read_cost_state()
    state["today_usd"] = round(state.get("today_usd", 0) + amount_usd, 4)
    state["total_usd"] = round(state.get("total_usd", 0) + amount_usd, 4)
    # Update breakdown
    breakdown = state.get("breakdown", [])
    for item in breakdown:
        if item["category"] == category:
            item["amount"] = round(item["amount"] + amount_usd, 4)
            break
    else:
        breakdown.append({"category": category, "amount": round(amount_usd, 4)})
    state["breakdown"] = breakdown
    state["last_updated"] = datetime.utcnow().isoformat()
    _write(OUTPUT_DIR / "cost_state.json", state)


# ─── Live Agent Log ── ring buffer per channel, cleared at run start ──────────

_LIVE_LOG_MAX = 200


def append_live_log(channel_id: str, entry: dict) -> None:
    """Append one live event for an active run. Fail-safe."""
    try:
        path = _ensure_output() / f"live_log_{channel_id}.json"
        try:
            data: list = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            data = []
        entry.setdefault("ts", datetime.utcnow().isoformat())
        data.append(entry)
        path.write_text(
            json.dumps(data[-_LIVE_LOG_MAX:], ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception:
        pass


def read_live_log(channel_id: str) -> list[dict]:
    path = _ensure_output() / f"live_log_{channel_id}.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []


def clear_live_log(channel_id: str) -> None:
    try:
        (_ensure_output() / f"live_log_{channel_id}.json").write_text(
            "[]", encoding="utf-8"
        )
    except Exception:
        pass


# ─── Internal ────────────────────────────────────────────────────────────────

def _write(path: Path, data: dict) -> None:
    _ensure_output()
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
