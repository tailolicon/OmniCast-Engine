"""Run artifact store — structured per-run output for review.

Each pipeline run creates:
  output/runs/{channel_id}/{YYYYMMDD_HHMMSS}/
    run_summary.json        - metadata, scores, timing, cost
    phase1_discovery.json   - topic, audience, all outliers, top opportunities
    phase2_scripts/
        variant_{id}.json   - full script JSON + debate rounds + visual cues
        debate_log.json     - all rounds per variant
    phase3_media.json       - TTS, render, subtitle status
    phase4_upload.json      - compliance, YouTube metadata, URL
    best_script.txt         - human-readable final script

API:
    GET /api/runs                    - list all runs (latest first)
    GET /api/runs/{channel_id}       - runs for one channel
    GET /api/runs/{run_id}/summary   - full run data
    GET /api/runs/{run_id}/script    - best script text
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

RUNS_DIR = Path(__file__).parent.parent.parent.parent / "output" / "runs"


# ─── Run lifecycle ────────────────────────────────────────────────────────────

def new_run(channel_id: str) -> str:
    """Create a new run directory. Returns run_id = channel_id/timestamp."""
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    run_id = f"{channel_id}/{ts}"
    run_dir = RUNS_DIR / channel_id / ts
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "phase2_scripts").mkdir(exist_ok=True)

    # Init summary
    _write_json(run_dir / "run_summary.json", {
        "run_id": run_id,
        "channel_id": channel_id,
        "started_at": datetime.utcnow().isoformat(),
        "finished_at": None,
        "status": "running",
        "phases_completed": [],
        "topic": None,
        "best_score": None,
        "total_cost_usd": 0.0,
        "timing": {},
    })
    return run_id


def save_phase1(run_id: str, data: dict) -> None:
    """Save Phase 1 discovery results.

    data keys:
        topic           str
        audience        str
        pain_point      str
        content_angle   str
        best_score      int
        top_opportunities list[dict]
        raw_outliers    list[dict]   (compact: title, views, outlier_ratio)
        source_counts   dict
        elapsed_s       float
        cost_usd        float
    """
    d = _run_dir(run_id)
    _write_json(d / "phase1_discovery.json", {**data, "saved_at": _now()})

    # Update summary
    _patch_summary(run_id, {
        "topic": data.get("topic"),
        "phases_completed": _append_phase(run_id, "phase1"),
        "timing.phase1_s": data.get("elapsed_s", 0),
        "total_cost_usd": data.get("cost_usd", 0),
    })


def save_phase2_variant(run_id: str, variant_id: str, data: dict) -> None:
    """Save one script variant + debate log.

    data keys:
        variant_id      str
        final_score     int
        approved        bool
        total_cost_usd  float
        hook            str
        segments        list[dict]
        outro           str
        rounds          list[dict]   (round_number, score, feedback)
        thinking_notes  str
    """
    d = _run_dir(run_id) / "phase2_scripts"
    _write_json(d / f"variant_{variant_id}.json", {**data, "saved_at": _now()})

    # Best score tracking
    summary = _read_summary(run_id)
    current_best = summary.get("best_score") or 0
    if data.get("final_score", 0) > current_best:
        _patch_summary(run_id, {"best_score": data["final_score"]})

    # Accumulate cost
    _patch_summary(run_id, {
        "total_cost_usd": round(
            summary.get("total_cost_usd", 0) + data.get("total_cost_usd", 0), 4
        )
    })


def save_phase2_debate_log(run_id: str, log: list[dict]) -> None:
    """Save full debate log (all variants, all rounds)."""
    d = _run_dir(run_id) / "phase2_scripts"
    _write_json(d / "debate_log.json", {"rounds": log, "saved_at": _now()})
    _patch_summary(run_id, {"phases_completed": _append_phase(run_id, "phase2")})


def save_best_script_txt(run_id: str, text: str) -> None:
    """Write human-readable best script."""
    (_run_dir(run_id) / "best_script.txt").write_text(text, encoding="utf-8")


def save_phase3(run_id: str, data: dict) -> None:
    """Save Phase 3 media pipeline results."""
    d = _run_dir(run_id)
    _write_json(d / "phase3_media.json", {**data, "saved_at": _now()})
    _patch_summary(run_id, {
        "phases_completed": _append_phase(run_id, "phase3"),
        "timing.phase3_s": data.get("elapsed_s", 0),
    })


def save_phase4(run_id: str, data: dict) -> None:
    """Save Phase 4 upload results (compliance + YouTube metadata)."""
    d = _run_dir(run_id)
    _write_json(d / "phase4_upload.json", {**data, "saved_at": _now()})
    _patch_summary(run_id, {
        "phases_completed": _append_phase(run_id, "phase4"),
        "youtube_url": data.get("youtube_url"),
        "youtube_video_id": data.get("youtube_video_id"),
    })


def finish_run(run_id: str, status: str = "completed") -> None:
    """Mark run as finished."""
    _patch_summary(run_id, {
        "finished_at": _now(),
        "status": status,
    })


# ─── Read API ────────────────────────────────────────────────────────────────

def list_runs(channel_id: str | None = None, limit: int = 50) -> list[dict]:
    """List all runs, latest first. Optionally filter by channel."""
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    runs = []

    if channel_id:
        ch_dir = RUNS_DIR / channel_id
        if ch_dir.exists():
            for ts_dir in sorted(ch_dir.iterdir(), reverse=True):
                if ts_dir.is_dir():
                    s = _read_summary_path(ts_dir / "run_summary.json")
                    if s:
                        runs.append(s)
    else:
        for ch_dir in sorted(RUNS_DIR.iterdir(), reverse=True):
            if not ch_dir.is_dir():
                continue
            for ts_dir in sorted(ch_dir.iterdir(), reverse=True):
                if ts_dir.is_dir():
                    s = _read_summary_path(ts_dir / "run_summary.json")
                    if s:
                        runs.append(s)

    return runs[:limit]


def get_run_summary(run_id: str) -> dict | None:
    """Get full summary for a run_id like 'fin_retirement_us/20250525_100000'."""
    parts = run_id.split("/", 1)
    if len(parts) != 2:
        return None
    p = RUNS_DIR / parts[0] / parts[1] / "run_summary.json"
    return _read_summary_path(p)


def get_run_phase1(run_id: str) -> dict | None:
    parts = run_id.split("/", 1)
    if len(parts) != 2:
        return None
    p = RUNS_DIR / parts[0] / parts[1] / "phase1_discovery.json"
    return _read_json(p)


def get_run_scripts(run_id: str) -> list[dict]:
    parts = run_id.split("/", 1)
    if len(parts) != 2:
        return []
    d = RUNS_DIR / parts[0] / parts[1] / "phase2_scripts"
    if not d.exists():
        return []
    scripts = []
    for f in sorted(d.glob("variant_*.json")):
        data = _read_json(f)
        if data:
            scripts.append(data)
    return scripts


def get_best_script_txt(run_id: str) -> str:
    parts = run_id.split("/", 1)
    if len(parts) != 2:
        return ""
    p = RUNS_DIR / parts[0] / parts[1] / "best_script.txt"
    return p.read_text(encoding="utf-8") if p.exists() else ""


# ─── Internal ────────────────────────────────────────────────────────────────

def _run_dir(run_id: str) -> Path:
    parts = run_id.split("/", 1)
    return RUNS_DIR / parts[0] / parts[1]


def _now() -> str:
    return datetime.utcnow().isoformat()


def _write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _read_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _read_summary(run_id: str) -> dict:
    p = _run_dir(run_id) / "run_summary.json"
    return _read_json(p) or {}


def _read_summary_path(path: Path) -> dict | None:
    return _read_json(path)


def _patch_summary(run_id: str, updates: dict) -> None:
    """Update specific keys in run_summary.json (supports dot-notation for nested)."""
    p = _run_dir(run_id) / "run_summary.json"
    data = _read_json(p) or {}
    for key, val in updates.items():
        if "." in key:
            # dot notation: "timing.phase1_s" → data["timing"]["phase1_s"]
            parts = key.split(".", 1)
            if parts[0] not in data:
                data[parts[0]] = {}
            data[parts[0]][parts[1]] = val
        else:
            data[key] = val
    _write_json(p, data)


def _append_phase(run_id: str, phase: str) -> list[str]:
    summary = _read_summary(run_id)
    phases = summary.get("phases_completed", [])
    if phase not in phases:
        phases.append(phase)
    return phases
