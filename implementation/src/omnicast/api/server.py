"""OmniCast Dashboard API Server.

Endpoints:
  GET  /api/status          — system overview + KPIs
  GET  /api/channels        — all channels with status
  GET  /api/pipeline        — active jobs + recent results
  GET  /api/niches          — latest niche discovery results
  GET  /api/budget          — cost tracking
  POST /api/discover-niches — trigger niche discovery (background)
  POST /api/run/{channel_id}— trigger phase-1 for channel (background)

Run:  uvicorn omnicast.api.server:app --reload --port 8765
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path

class SafeStream:
    """Wrap standard streams to silently ignore OSError (Errno 22) on Windows detached consoles."""
    def __init__(self, stream):
        self.stream = stream
    def write(self, data):
        try:
            if self.stream: self.stream.write(data)
        except (OSError, UnicodeEncodeError):
            try:
                if self.stream:
                    safe = data.encode('utf-8', errors='replace').decode('utf-8')
                    self.stream.write(safe)
            except Exception:
                pass
    def flush(self):
        try:
            if self.stream: self.stream.flush()
        except OSError:
            pass

# Reconfigure stdout/stderr to UTF-8 on Windows to handle emoji/unicode in logs
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except AttributeError:
    pass  # not a TextIOWrapper (e.g. already wrapped)

sys.stdout = SafeStream(sys.stdout)
sys.stderr = SafeStream(sys.stderr)

import structlog
structlog.configure(
    logger_factory=structlog.PrintLoggerFactory(file=sys.stdout)
)
logger = structlog.get_logger()

from fastapi import FastAPI, HTTPException, BackgroundTasks, Body, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

# Ensure src is on path when run directly
_ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(_ROOT))

# Load implementation/.env into the real process environment. pydantic-settings
# (config/settings.py) reads .env directly for its own typed fields, but several
# call sites here use os.getenv(...) straight (OMNICAST_CREDENTIAL_FERNET_KEY,
# etc.) — those only see .env values if something puts them in os.environ first.
# Without this, credentials silently stored unencrypted (base64 fallback) even
# with a real Fernet key configured in .env. Never overrides a var the process
# environment already set explicitly.
try:
    from dotenv import load_dotenv as _load_dotenv
    _load_dotenv(_ROOT / ".env", override=False)
except Exception:
    pass

from omnicast.api.state import (
    read_pipeline_state, read_niche_results, read_cost_state,
    write_niche_results, set_active_job, clear_active_job,
    write_pipeline_event, set_active_job_progress,
    read_error_log, append_error, clear_error_log,
    append_live_log, read_live_log, clear_live_log,
)

# Reuse the Streamlit dashboard's sync PostgreSQL+Redis data layer.
# Will be relocated out of the Streamlit tree in Pass #11.
from omnicast.dashboard.data_service import DashboardDataService
from omnicast.config.settings import get_settings as _get_app_settings

CHANNELS_DIR = _ROOT.parent / "channels"   # implementation/../channels
OUTPUT_DIR = _ROOT.parent / "output"        # implementation/../output → actually in implementation/output
# Re-align: channels/ and output/ are siblings of src/ inside implementation/
CHANNELS_DIR = _ROOT / "channels"
OUTPUT_DIR = _ROOT / "output"

app = FastAPI(title="OmniCast Engine API", version="1.0")


_job_engine = None


def _get_job_engine():
    """Lazy production JobEngine singleton with the pipeline handler registered."""
    global _job_engine
    if _job_engine is not None:
        return _job_engine

    from omnicast.jobengine import JobEngine
    from omnicast.jobengine import store as job_store
    from omnicast.pipeline.runner import PipelineRunner

    db_path = OUTPUT_DIR / "vault.db"
    job_store.init_jobengine_schema(db_path)
    engine = JobEngine(db_path=db_path)

    async def _pipeline_handler(ctx):
        payload = dict(ctx.payload or {})
        pipeline_id = str(payload.get("pipeline_id") or "default_channel")
        pipelines_dir = _ROOT.parent / "pipelines"
        if not pipelines_dir.exists():
            pipelines_dir = _ROOT / "pipelines"
        yaml_file = pipelines_dir / f"{pipeline_id}.yaml"
        if not yaml_file.exists():
            raise FileNotFoundError(f"Pipeline '{pipeline_id}.yaml' not found in {pipelines_dir}")

        inputs = dict(payload.get("inputs") or {})
        ctx.progress(1, 2, "pipeline", "running")
        try:
            execution = await PipelineRunner(db_path=db_path).run_checkpointed_file(
                yaml_file, inputs=inputs, job_id=ctx.job_id, events=ctx.events
            )
            ctx.progress(2, 2, "pipeline", str(execution.status.value))
            if execution.error:
                raise RuntimeError(execution.error)
            
            # Auto-queue for approval if render succeeded and upload was not run
            if execution.status.value == "success" and "render" in execution.steps:
                upload_step_skipped = True
                if "upload" in execution.steps:
                    upload_step_skipped = (execution.steps["upload"].status.value == "skipped")
                if upload_step_skipped:
                    render_step = execution.steps["render"]
                    if render_step.status.value in {"success", "skipped"}:
                        video_path = render_step.outputs.get("video_path")
                        cid = inputs.get("channel_id")
                        if cid and video_path:
                            try:
                                await queue_channel_publish(cid, {"video_path": video_path, "job_id": ctx.job_id})
                                logger.info("Auto-queued publish approval for successful pipeline", channel_id=cid, video_path=video_path)
                            except Exception as auto_err:
                                logger.warning("Auto-queue publish approval failed", error=str(auto_err))

            return {"execution_id": execution.execution_id, "status": execution.status.value}
        except Exception as e:
            err_msg = str(e)
            if "WAITING_EDIT:" in err_msg:
                parts = err_msg.split("WAITING_EDIT:")
                script_path = parts[1]
                from omnicast.api.state import set_active_job_progress
                set_active_job_progress(
                    inputs.get("channel_id"),
                    stage="WAITING_EDIT",
                    pct=50,
                    detail=script_path,
                )
            raise

    engine.register("pipeline", _pipeline_handler)
    engine.register("pipeline.default_channel", _pipeline_handler)
    _job_engine = engine
    return engine


try:
    from omnicast.jobengine.api import create_app as _create_jobengine_app

    app.mount("/jobengine", _create_jobengine_app(_get_job_engine()), name="jobengine")
except Exception as _exc:
    logger.warning("Job Engine API not mounted", error=str(_exc))


@app.on_event("startup")
async def _clear_stale_jobs_on_startup():
    """On every server start/reload, clear all active_jobs.

    Background tasks cannot survive a process restart, so any job that was
    'active' before is now dead. Leaving them causes the dashboard to show
    phantom 'Running' states forever.
    """
    try:
        from omnicast.api.state import read_pipeline_state, _write, OUTPUT_DIR
        state = read_pipeline_state()
        if state.get("active_jobs"):
            for job in state["active_jobs"]:
                ch_id = job.get("channel_id", "")
                if ch_id and ch_id in state.get("channels", {}):
                    ch = state["channels"][ch_id]
                    if str(ch.get("status", "")).endswith("_running"):
                        ch["status"] = "idle"
                        ch["current_phase"] = None
            state["active_jobs"] = []
            _write(OUTPUT_DIR / "pipeline_state.json", state)
            logger.info("Cleared stale active_jobs on startup")
    except Exception:
        pass


# ─── Autonomous scheduler (CRON-like, MoneyPrinter-style) ────────────────────
# Background loop: per channel cadence + prime-time hour → auto-pilot one channel
# per tick (discover→topic→script→render→optional upload). Off by default.
_SCHED_STATE = OUTPUT_DIR / "scheduler_state.json"
_CADENCE_PER_WEEK = {"daily": 7, "3x_weekly": 3, "twice_weekly": 2, "weekly": 1}
_SCHED_TICK_S = 300


def _read_sched() -> dict:
    try:
        return json.loads(_SCHED_STATE.read_text(encoding="utf-8-sig"))
    except Exception:
        return {"enabled": False, "upload": False, "channels": {}}


def _write_sched(d: dict) -> None:
    try:
        _SCHED_STATE.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def _chan_sched(st: dict, ch: dict) -> dict:
    """Per-channel schedule config: scheduler_state override > channel.json default."""
    cid = ch.get("channel_id", "")
    s = (st.get("channels", {}) or {}).get(cid, {})
    return {
        "enabled": s.get("enabled", False),  # per-channel must be opted in
        "cadence": s.get("cadence", ch.get("upload_cadence", "3x_weekly")),
        "prime_hours": s.get("prime_hours", ch.get("prime_time_hours") or [9, 12, 17]),
        "shorts": s.get("shorts", False),
        "upload": s.get("upload", False),
        "last_run": s.get("last_run"),
        "week": s.get("week"),
        "week_count": s.get("week_count", 0),
    }


def _due_channel(st: dict):
    """Pick ONE per-channel-enabled channel due now → (cid, shorts, upload). None."""
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    today, week, hour = now.strftime("%Y-%m-%d"), now.strftime("%Y-%W"), now.hour
    for ch in _all_channels():
        cid = ch.get("channel_id")
        if not cid:
            continue
        c = _chan_sched(st, ch)
        if not c["enabled"] or hour not in c["prime_hours"]:
            continue
        target = _CADENCE_PER_WEEK.get(c["cadence"], 3)
        wk_count = c["week_count"] if c["week"] == week else 0
        if c["last_run"] == today or wk_count >= target:
            continue
        return cid, c["shorts"], c["upload"]
    return None


async def _scheduler_loop():
    import asyncio as _aio
    from datetime import datetime, timezone
    await _aio.sleep(20)  # let startup settle
    while True:
        try:
            st = _read_sched()
            if st.get("enabled") and not _auto_state.get("running") \
               and not read_pipeline_state().get("active_jobs"):
                due = _due_channel(st)
                if due:
                    cid, shorts, upload = due
                    now = datetime.now(timezone.utc)
                    chans = st.setdefault("channels", {})
                    s = chans.setdefault(cid, {})
                    if s.get("week") != now.strftime("%Y-%W"):
                        s["week"], s["week_count"] = now.strftime("%Y-%W"), 0
                    s["last_run"] = now.strftime("%Y-%m-%d")
                    s["week_count"] = s.get("week_count", 0) + 1
                    _write_sched(st)
                    logger.info("Scheduler firing", channel=cid, shorts=shorts)
                    await _auto_cycle_task([cid], bool(upload), 35, shorts=bool(shorts))
        except Exception as exc:
            logger.warning("scheduler tick failed", error=str(exc))
        await _aio.sleep(_SCHED_TICK_S)


@app.on_event("startup")
async def _start_scheduler():
    import asyncio as _aio
    _aio.create_task(_scheduler_loop())


# ─── Weekly policy watcher (APScheduler) ─────────────────────────────────────
async def _policy_watcher_loop():
    """Run policy check once per week (every Sunday 03:00 UTC).

    Uses APScheduler AsyncIOScheduler when available; falls back to a plain
    asyncio 7-day sleep so the feature works even without the extra dep.
    """
    import asyncio as _aio
    # Let the server settle and vault.db init before the first scheduled run.
    await _aio.sleep(60)
    try:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        from apscheduler.triggers.cron import CronTrigger

        async def _do_check():
            logger.info("APScheduler: weekly policy check starting")
            await _run_policy_check_task()

        sched = AsyncIOScheduler()
        sched.add_job(_do_check, CronTrigger(day_of_week="sun", hour=3, minute=0))
        sched.start()
        logger.info("Policy watcher scheduled (APScheduler, every Sunday 03:00 UTC)")
        while True:
            await _aio.sleep(3600)  # keep coroutine alive
    except ImportError:
        logger.warning("APScheduler not installed — using 7-day asyncio fallback for policy watcher")
        while True:
            await _aio.sleep(7 * 24 * 3600)
            logger.info("asyncio fallback: weekly policy check starting")
            await _run_policy_check_task()


@app.on_event("startup")
async def _start_policy_watcher():
    import asyncio as _aio
    _aio.create_task(_policy_watcher_loop())


# ─── Kestra-lite pipeline scheduler ──────────────────────────────────────────
_pipeline_scheduler = None


@app.on_event("startup")
async def _start_pipeline_scheduler():
    """Register APScheduler cron jobs for every pipeline YAML that has schedule:."""
    global _pipeline_scheduler
    pipelines_dir = _ROOT.parent / "pipelines"
    if not pipelines_dir.exists():
        pipelines_dir = _ROOT / "pipelines"
    if not pipelines_dir.exists():
        return
    try:
        from omnicast.pipeline.runner import PipelineScheduler
        from omnicast.pipeline.executions import init_executions_table
        VAULT_DB = OUTPUT_DIR / "vault.db"
        init_executions_table(VAULT_DB)
        _pipeline_scheduler = PipelineScheduler(
            pipelines_dir=pipelines_dir,
            db_path=VAULT_DB,
        )
        _pipeline_scheduler.start()
    except Exception as exc:
        logger.warning("PipelineScheduler failed to start", error=str(exc))


@app.on_event("shutdown")
async def _stop_pipeline_scheduler():
    if _pipeline_scheduler:
        _pipeline_scheduler.shutdown()


@app.get("/api/pipelines/executions")
async def list_pipeline_executions(
    pipeline_id: str | None = None,
    channel_id: str | None = None,
    limit: int = 50,
):
    """Recent pipeline execution records from vault.db."""
    from omnicast.pipeline.executions import list_executions
    VAULT_DB = OUTPUT_DIR / "vault.db"
    rows = list_executions(pipeline_id=pipeline_id, channel_id=channel_id,
                           limit=min(limit, 200), db_path=VAULT_DB)
    return {"executions": rows, "total": len(rows)}


@app.get("/api/pipelines/executions/{execution_id}")
async def get_pipeline_execution(execution_id: str):
    """Full detail for one pipeline execution (includes per-step results)."""
    from omnicast.pipeline.executions import get_execution
    VAULT_DB = OUTPUT_DIR / "vault.db"
    row = get_execution(execution_id, VAULT_DB)
    if not row:
        raise HTTPException(404, f"Execution {execution_id!r} not found")
    return row


@app.post("/api/pipelines/run")
async def trigger_pipeline_run(
    background_tasks: BackgroundTasks,
    pipeline_id: str = "default_channel",
    channel_id: str | None = None,
    do_upload: bool = False,
):
    """Trigger a named pipeline from the pipelines/ directory on demand."""
    pipelines_dir = _ROOT.parent / "pipelines"
    if not pipelines_dir.exists():
        pipelines_dir = _ROOT / "pipelines"
    yaml_file = pipelines_dir / f"{pipeline_id}.yaml"
    if not yaml_file.exists():
        raise HTTPException(404, f"Pipeline '{pipeline_id}.yaml' not found in {pipelines_dir}")

    inputs = {"do_upload": do_upload}
    if channel_id:
        inputs["channel_id"] = channel_id

    from omnicast.jobengine.models import JobSpec, ResourceClass

    job_id = f"pipeline_{pipeline_id}_{uuid.uuid4().hex[:12]}"
    spec = JobSpec(
        job_id=job_id,
        type="pipeline",
        resource_class=ResourceClass.CPU,
        priority=3,
        payload={"pipeline_id": pipeline_id, "inputs": inputs},
    )
    await _get_job_engine().submit(spec)
    return {
        "status": "started",
        "pipeline_id": pipeline_id,
        "inputs": inputs,
        "job_id": job_id,
        "job_status_url": f"/jobengine/api/v1/jobs/{job_id}",
    }


@app.get("/api/script/edit")
async def get_script_edit(path: str):
    from pathlib import Path
    import json
    p = Path(path)
    if not p.exists():
        raise HTTPException(404, f"Script file not found: {path}")
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        raise HTTPException(500, f"Failed to parse script JSON: {str(e)}")


@app.put("/api/script/edit")
async def put_script_edit(path: str = Query(...), payload: dict = Body(...)):
    from pathlib import Path
    import json
    p = Path(path)
    if not p.exists():
        raise HTTPException(404, f"Script file not found: {path}")
    try:
        p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"status": "saved", "path": path}
    except Exception as e:
        raise HTTPException(500, f"Failed to write script JSON: {str(e)}")


@app.post("/api/pipelines/resume/{job_id}")
async def resume_pipeline_job(job_id: str):
    from pathlib import Path
    import json
    from omnicast.jobengine import store as job_store
    
    db_path = OUTPUT_DIR / "vault.db"
    
    # 1. Update the job spec payload to add "resume_script": True
    with job_store._connect(db_path) as conn:
        row = conn.execute("SELECT spec_json FROM jobs WHERE job_id=?", (job_id,)).fetchone()
        if not row:
            raise HTTPException(404, f"Job not found: {job_id}")
        spec = json.loads(row[0])
        payload = spec.setdefault("payload", {})
        inputs = payload.setdefault("inputs", {})
        inputs["resume_script"] = True
        
        conn.execute("UPDATE jobs SET spec_json=? WHERE job_id=?", (json.dumps(spec), job_id))
        conn.commit()
        
    # 2. Call retry on the job engine
    try:
        await _get_job_engine().retry(job_id)
    except Exception as e:
        raise HTTPException(500, f"Failed to resume job: {str(e)}")
        
    return {"status": "resumed", "job_id": job_id}


@app.get("/api/scheduler")
async def get_scheduler():
    """Scheduler master switch + per-channel schedule (merged config + run log)."""
    st = _read_sched()
    chans = []
    for ch in _all_channels():
        c = _chan_sched(st, ch)
        c["channel_id"] = ch.get("channel_id")
        c["name"] = ch.get("name", ch.get("channel_id"))
        chans.append(c)
    return {
        "enabled": st.get("enabled", False),
        "tick_seconds": _SCHED_TICK_S,
        "cadence_map": _CADENCE_PER_WEEK,
        "channels": chans,
    }


@app.post("/api/scheduler/toggle")
async def toggle_scheduler(enabled: bool):
    """Master on/off for the whole scheduler."""
    st = _read_sched()
    st["enabled"] = bool(enabled)
    _write_sched(st)
    return {"enabled": st["enabled"]}


@app.post("/api/scheduler/channel/{channel_id}")
async def set_channel_schedule(channel_id: str, enabled: bool | None = None,
                               cadence: str | None = None, shorts: bool | None = None,
                               upload: bool | None = None, prime_hours: str | None = None):
    """Set a single channel's schedule (enabled, cadence, shorts, upload, prime_hours
    CSV of UTC hours e.g. '9,12,17')."""
    st = _read_sched()
    chans = st.setdefault("channels", {})
    s = chans.setdefault(channel_id, {})
    if enabled is not None:
        s["enabled"] = bool(enabled)
    if cadence is not None and cadence in _CADENCE_PER_WEEK:
        s["cadence"] = cadence
    if shorts is not None:
        s["shorts"] = bool(shorts)
    if upload is not None:
        s["upload"] = bool(upload)
    if prime_hours is not None:
        try:
            s["prime_hours"] = sorted({int(h) for h in prime_hours.split(",")
                                       if 0 <= int(h) <= 23})
        except Exception:
            pass
    _write_sched(st)
    return {"channel_id": channel_id, "schedule": s}


# ─── Lazy singleton: shared DashboardDataService (DB + Redis) ─────────────────
_data_service: DashboardDataService | None = None
_data_service_init_error: str | None = None


def _get_data_service() -> DashboardDataService:
    """Lazy init so server can boot even if Postgres / Redis are temporarily down,
    OR if settings cannot be loaded at all (e.g. missing .env file).

    Rule #3 (provenance): we never raise from here. If settings fail to load we
    return a service instantiated with empty URLs (every DB/Redis call inside it
    is already wrapped in try/except and returns empty/None) and stash the root
    cause in `_data_service_init_error` so endpoints can surface it to the operator.
    """
    global _data_service, _data_service_init_error
    if _data_service is None:
        try:
            settings = _get_app_settings()
            _data_service = DashboardDataService(
                db_url=settings.database_url,
                redis_url=settings.redis_url,
                channels_dir=CHANNELS_DIR,
                vault_path=OUTPUT_DIR / "vault.db",
            )
            _data_service_init_error = None
        except Exception as exc:
            # Build a defanged service so endpoints keep working in degraded mode.
            _data_service_init_error = f"settings load failed: {str(exc)[:300]}"
            _data_service = DashboardDataService(
                db_url="",  # engine init will fail-soft; methods return empty
                redis_url="redis://localhost:6379/0",
                channels_dir=CHANNELS_DIR,
                vault_path=OUTPUT_DIR / "vault.db",
            )
    return _data_service


def _envelope(payload, source: str) -> dict:
    """Provenance envelope every new endpoint wraps responses in.

    Rule #3 of the operator philosophy: every datum must carry source + fetched_at
    so operators can answer 'where did this number come from?'.
    """
    return {
        "data":       payload,
        "source":     source,
        "fetched_at": datetime.utcnow().isoformat() + "Z",
    }

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Video-render routes + media static (isolated router) ────────────────────
try:
    from pathlib import Path as _Path

    from fastapi.staticfiles import StaticFiles

    from omnicast.api.render_routes import OUT_DIR as _OUT_DIR, render_router

    app.include_router(render_router)
    _OUT_DIR.mkdir(parents=True, exist_ok=True)
    app.mount("/media", StaticFiles(directory=str(_OUT_DIR)), name="media")
    # Products tree (output/products) is the SSOT for rendered videos but wasn't
    # HTTP-served — the Studio player, thumbnails and scene timeline (_status/status.json)
    # all live here, so expose it read-only under /pmedia.
    from omnicast.storage import products as _products_mod
    _PRODUCTS_DIR = _products_mod.PRODUCTS_DIR
    _PRODUCTS_DIR.mkdir(parents=True, exist_ok=True)
    app.mount("/pmedia", StaticFiles(directory=str(_PRODUCTS_DIR)), name="pmedia")
except Exception as _exc:  # don't let render routes break the core API
    print(f"[server] render routes not mounted: {_exc}")


# ─── Thumb Studio — operator-curated FLOW-ONLY thumbnails ────────────────────
# Decoupled from the render pipeline (operator policy 2026-07-09): generate N
# candidates with distinct clickbait angles, pick the official one, regenerate
# with a free-text operator note that is injected into the Flow prompt.

def _thumb_product_dir(channel_id: str, slug: str) -> Path:
    from omnicast.storage import products as _p
    d = _p.PRODUCTS_DIR / channel_id / slug
    if not d.exists():
        raise HTTPException(status_code=404, detail=f"product not found: {channel_id}/{slug}")
    return d


def _thumb_studio_mod():
    import sys as _sys
    _impl = str(Path(__file__).resolve().parents[3])
    if _impl not in _sys.path:
        _sys.path.insert(0, _impl)
    import thumb_studio
    return thumb_studio


@app.get("/api/thumbs/{channel_id}/{slug}")
def api_thumbs_list(channel_id: str, slug: str):
    d = _thumb_product_dir(channel_id, slug)
    tdir = d / "thumbs"
    meta: dict = {}
    if (tdir / "meta.json").exists():
        try:
            meta = json.loads((tdir / "meta.json").read_text(encoding="utf-8"))
        except Exception:
            meta = {}
    cands = sorted((p.name for p in tdir.glob("cand_*.png")), reverse=True) if tdir.exists() else []
    return {"candidates": cands, "selected": meta.get("selected"),
            "title": meta.get("title", ""),
            "has_official": (d / "video_thumb.png").exists()}


@app.post("/api/thumbs/{channel_id}/{slug}/generate")
async def api_thumbs_generate(channel_id: str, slug: str,
                              background_tasks: BackgroundTasks,
                              payload: dict | None = Body(default=None)):
    d = _thumb_product_dir(channel_id, slug)
    note = str((payload or {}).get("note") or "")
    count = max(1, min(int((payload or {}).get("count") or 4), 4))
    per_angle = max(1, min(int((payload or {}).get("per_angle") or 2), 4))

    def _run():
        _thumb_studio_mod().generate_candidates(
            d, note=note, count=count, per_angle=per_angle)

    background_tasks.add_task(_run)
    return {"status": "started", "count": count, "per_angle": per_angle,
            "total": count * per_angle, "note": note}


@app.post("/api/thumbs/{channel_id}/{slug}/select")
def api_thumbs_select(channel_id: str, slug: str, payload: dict = Body(...)):
    d = _thumb_product_dir(channel_id, slug)
    name = str(payload.get("candidate") or "")
    if "/" in name or "\\" in name or not name.startswith("cand_"):
        raise HTTPException(status_code=400, detail="invalid candidate name")
    _thumb_studio_mod().select(d, name)
    return {"status": "ok", "selected": name}


@app.get("/thumbs")
def thumbs_page():
    """Standalone Thumb Studio page (gallery + select + regenerate-with-note).
    Kept server-rendered so it works without a webui_v2 rebuild; integrate into
    the React Studio tab later."""
    from fastapi.responses import HTMLResponse
    from omnicast.storage import products as _p
    rows = []
    for ch_dir in sorted(_p.PRODUCTS_DIR.iterdir() if _p.PRODUCTS_DIR.exists() else []):
        if not ch_dir.is_dir():
            continue
        for prod in sorted(ch_dir.iterdir(), reverse=True):
            if prod.is_dir() and (prod / "script.txt").exists():
                rows.append((ch_dir.name, prod.name))
    opts = "".join(f'<option value="{c}/{s}">{c} / {s[:60]}</option>' for c, s in rows[:40])
    html = """<!doctype html><html><head><meta charset="utf-8"><title>Thumb Studio</title>
<style>
 body{font-family:system-ui,sans-serif;background:#faf7ff;margin:24px;color:#2a2440}
 h1{font-size:20px} select,textarea,button{font:inherit;padding:8px;border-radius:10px;border:2px solid #2a2440}
 textarea{width:100%;max-width:720px;min-height:64px} .bar{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin:10px 0}
 .grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:16px;margin-top:16px}
 .card{background:#fff;border:2px solid #2a2440;border-radius:14px;padding:10px;box-shadow:4px 4px 0 #2a244022}
 .card img{width:100%;border-radius:8px;display:block}
 .card.sel{outline:4px solid #10B981}
 .tag{font-size:12px;color:#6b6383;margin:6px 0}
 button.primary{background:#10B981;color:#fff;border-color:#0b8a63;cursor:pointer}
 button{cursor:pointer} #status{font-size:13px;color:#6b6383}
</style></head><body>
<h1>🖼️ Thumb Studio <span style="font-weight:400;font-size:13px;color:#6b6383">(FLOW-only · chọn bản chính thức · tạo lại kèm yêu cầu)</span></h1>
<div class="bar">
 <select id="prod">__OPTS__</select>
 <button onclick="load()">Xem ứng viên</button>
 <span id="status"></span>
</div>
<div class="bar" style="align-items:flex-start">
 <textarea id="note" placeholder="Yêu cầu cho agent tạo thumb (vd: 'mặt kinh hãi hơn nữa, camera sát hơn, thêm mũi tên đỏ chỉ vào ly cà phê, chữ to hơn')"></textarea>
 <label>Ảnh/góc <select id="pa"><option>1</option><option selected>2</option><option>3</option><option>4</option></select></label>
 <button class="primary" onclick="gen()">⚡ Tạo batch thumb (4 góc × N)</button>
</div>
<div id="grid" class="grid"></div>
<script>
const $=id=>document.getElementById(id);
function prod(){return $('prod').value.split('/');}
async function load(){
 const [c,s]=prod();
 const r=await fetch(`/api/thumbs/${c}/${s}`); const d=await r.json();
 $('status').textContent = d.title ? `Title: ${d.title}` : '';
 const g=$('grid'); g.innerHTML='';
 if(d.has_official){
   g.innerHTML += `<div class="card sel"><img src="/pmedia/${c}/${s}/video_thumb.png?${Date.now()}">
     <div class="tag">✅ BẢN CHÍNH THỨC hiện tại (video_thumb.png)</div></div>`;
 }
 for(const f of d.candidates){
   const isSel = d.selected===f;
   g.innerHTML += `<div class="card ${isSel?'sel':''}"><img src="/pmedia/${c}/${s}/thumbs/${f}?${Date.now()}">
     <div class="tag">${f}${isSel?' · đang dùng':''}</div>
     <button class="primary" onclick="pick('${f}')">Dùng làm thumb chính thức</button></div>`;
 }
 if(!d.candidates.length && !d.has_official) g.innerHTML='<p>Chưa có thumb — bấm "Tạo 4 thumb mới".</p>';
}
async function pick(f){
 const [c,s]=prod();
 await fetch(`/api/thumbs/${c}/${s}/select`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({candidate:f})});
 load();
}
async function gen(){
 const [c,s]=prod();
 const pa=parseInt($('pa').value)||2;
 $('status').textContent=`⏳ Đang tạo batch ${4*pa} ảnh qua Flow (4 góc × ${pa})...`;
 await fetch(`/api/thumbs/${c}/${s}/generate`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({note:$('note').value,count:4,per_angle:pa})});
 let n=0; const t=setInterval(async()=>{ n++; await load(); if(n>150) clearInterval(t); }, 8000);
}
load();
</script></body></html>"""
    return HTMLResponse(html.replace("__OPTS__", opts))


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _load_channel_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _all_channels() -> list[dict]:
    channels = []
    if CHANNELS_DIR.exists():
        for p in sorted(CHANNELS_DIR.glob("*.json")):
            try:
                ch = _load_channel_json(p)
            except Exception:
                continue
            # channels/ chứa cả file không phải channel config (credentials.json) —
            # thiếu channel_id thì bỏ qua, tránh card ma channel_id="" trên UI.
            if not (isinstance(ch, dict) and ch.get("channel_id")):
                continue
            channels.append(ch)
    return channels


def _channel_display(ch: dict, pipeline_state: dict) -> dict:
    cid = ch.get("channel_id", "")
    ch_state = pipeline_state.get("channels", {}).get(cid, {})
    return {
        "channel_id": cid,
        "name": ch.get("name", cid),
        "niche": ch.get("niche", ""),
        "sub_niche": ch.get("sub_niche", ""),
        "niches": ch.get("niches", []),
        "youtube_channel_id": ch.get("youtube_channel_id", ""),
        "market": ch.get("market", "US"),
        "brand_voice": ch.get("brand_voice", "")[:60],
        "competitor_handles": ch.get("competitor_handles", []),
        "rpm_floor": ch.get("rpm_floor", 7.0),
        "destinations": ch.get("destinations", []),
        # Live state
        "status": ch_state.get("status", "idle"),
        "current_phase": ch_state.get("current_phase"),
        "current_topic": ch_state.get("current_topic"),
        "last_topic": ch_state.get("last_topic"),
        "last_score": ch_state.get("last_score"),
        "last_cost_usd": ch_state.get("last_cost_usd"),
        "last_updated": ch_state.get("last_updated"),
    }


# ─── Endpoints ───────────────────────────────────────────────────────────────

@app.get("/api/status")
async def get_status():
    """System overview KPIs."""
    pipeline = read_pipeline_state()
    cost = read_cost_state()
    channels = _all_channels()
    niche_data = read_niche_results()

    active_jobs = pipeline.get("active_jobs", [])
    recent = pipeline.get("recent_results", [])
    approved = [r for r in recent if r.get("score", 0) >= 70]

    return {
        "timestamp": datetime.utcnow().isoformat(),
        "system": {
            "status": "operational",
            "channels_total": len(channels),
            "active_jobs": len(active_jobs),
            "niches_discovered": len(niche_data.get("niches", [])),
        },
        "kpis": {
            "scripts_approved_today": len(approved),
            "active_runs": len(active_jobs),
            "daily_spend_usd": cost.get("today_usd", 0.0),
            "daily_cap_usd": cost.get("daily_cap_usd", 100.0),
            "total_channels": len(channels),
        },
        "recent_activity": recent[:5],
    }


@app.get("/api/channels")
async def get_channels():
    """All channels with live pipeline status."""
    from omnicast.vault import db as vault_db
    VAULT_DB = OUTPUT_DIR / "vault.db"
    vault_db.init_db(VAULT_DB)
    stats_by_id = {s.channel_id: s for s in vault_db.list_channel_stats(VAULT_DB)}

    pipeline = read_pipeline_state()
    st = _read_sched()
    channels = _all_channels()

    def _display_with_stats(ch):
        disp = _channel_display(ch, pipeline)
        cid = ch.get("channel_id", "")
        s = stats_by_id.get(cid)
        sched_cfg = _chan_sched(st, ch)
        disp.update({
            "subscribers": s.subscribers if s else 0,
            "total_views": s.total_views if s else 0,
            "video_count": s.video_count if s else 0,
            "est_revenue_usd": s.est_revenue_usd if s else 0.0,
            "linked": bool(s and s.youtube_channel_id),
            "enabled": sched_cfg.get("enabled", False),
            "shorts": sched_cfg.get("shorts", False),
            "upload": sched_cfg.get("upload", False),
            "cadence": sched_cfg.get("cadence", "3x_weekly"),
        })
        return disp

    return {
        "channels": [_display_with_stats(ch) for ch in channels],
        "total": len(channels),
    }


def _platform_specs() -> list[dict]:
    from omnicast.platforms.tiktok import TikTokPlatform
    from omnicast.platforms.youtube import YouTubePlatform

    return [
        {
            "platform_id": YouTubePlatform.id,
            "name": "YouTube",
            "format_spec": YouTubePlatform.format_spec.model_dump(mode="json"),
            "capabilities": {
                "publish": True,
                "analytics": True,
                "comments": False,
                "scheduling": YouTubePlatform.format_spec.supports_scheduling,
                "thumbnail": YouTubePlatform.format_spec.supports_thumbnail,
            },
        },
        {
            "platform_id": TikTokPlatform.id,
            "name": "TikTok",
            "format_spec": TikTokPlatform.format_spec.model_dump(mode="json"),
            "capabilities": {
                "publish": "dry_run_or_official_api",
                "analytics": False,
                "comments": False,
                "scheduling": TikTokPlatform.format_spec.supports_scheduling,
                "thumbnail": TikTokPlatform.format_spec.supports_thumbnail,
            },
        },
    ]


def _destinations_for_channel(ch: dict) -> list[dict]:
    cid = ch.get("channel_id", "")
    configured = ch.get("destinations") or []
    if configured:
        return [
            {
                **dest,
                "channel_id": cid,
                "channel_name": ch.get("name", cid),
            }
            for dest in configured
        ]
    return [{
        "destination_id": f"{cid}_youtube",
        "channel_id": cid,
        "channel_name": ch.get("name", cid),
        "platform_id": "youtube",
        "account_id": ch.get("youtube_channel_id") or cid,
        "format_variant": "youtube_16x9",
        "enabled": True,
        "approval_required": False,
        "schedule_policy": "prime_time",
        "market": ch.get("market", "US"),
        "metadata_overrides": {},
        "implicit_legacy": True,
    }]


_LATEST_OUTPUTS_CACHE: dict = {"key": None, "at": 0.0, "value": []}
_LATEST_OUTPUTS_TTL = 60.0  # seconds — readiness is polled every few seconds by the UI


def _latest_video_outputs(limit: int = 5) -> list[dict]:
    """Newest rendered videos + their audit, for the readiness panel.

    Perf-critical (BUG-1): the UI polls this on a short interval + SSE, so it must NOT
    (a) rglob the whole repo or (b) re-run ffmpeg loudness per call. Instead: scan only
    the two known render trees, PREFER the `_output_audit.json` sidecar the pipeline
    already wrote, fall back to a cheap ffprobe (no ebur128), and cache by (path, mtime).
    """
    import time
    from omnicast.media.output_audit import OutputQualityAuditor

    roots = [OUTPUT_DIR / "products", OUTPUT_DIR / "pipeline_renders"]
    roots = [r for r in roots if r.exists()] or [OUTPUT_DIR]
    candidates: list[Path] = []
    for root in roots:
        candidates.extend(p for p in root.rglob("*.mp4") if "_assets" not in p.parts)
    unique = {str(path.resolve()): path for path in candidates}
    files = sorted(unique.values(), key=lambda p: p.stat().st_mtime, reverse=True)[:limit]

    key = tuple((str(p), p.stat().st_mtime) for p in files)
    now = time.time()
    if _LATEST_OUTPUTS_CACHE["key"] == key and now - _LATEST_OUTPUTS_CACHE["at"] < _LATEST_OUTPUTS_TTL:
        return _LATEST_OUTPUTS_CACHE["value"]

    auditor = OutputQualityAuditor(measure_loudness=False)  # no ebur128 full-decode here
    out = []
    for path in files:
        sidecar = path.parent / "_output_audit.json"
        audit = None
        if sidecar.exists() and sidecar.stat().st_mtime >= path.stat().st_mtime:
            try:
                audit = json.loads(sidecar.read_text(encoding="utf-8"))
            except Exception:
                audit = None
        if audit is None:
            audit = auditor.inspect(path)  # ffprobe only — cheap, no console window
        out.append({
            "path": str(path),
            "size_mb": round(path.stat().st_size / (1024 * 1024), 2),
            "modified_at": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(),
            "audit": audit,
        })
    _LATEST_OUTPUTS_CACHE.update(key=key, at=now, value=out)
    return out


def _vault_table_exists(table_name: str) -> bool:
    from omnicast.vault import db as vault_db

    vault_db.init_db(OUTPUT_DIR / "vault.db")
    with vault_db._connect(OUTPUT_DIR / "vault.db") as conn:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table_name,),
        ).fetchone()
    return bool(row)


def _monetization_readiness() -> dict:
    from omnicast.capabilities.registry import CapabilityRegistry
    from omnicast.vault import db as vault_db

    vault_db.init_db(OUTPUT_DIR / "vault.db")
    channels = _all_channels()
    destinations = []
    for ch in channels:
        destinations.extend(_destinations_for_channel(ch))
    platform_ids = {dest.get("platform_id") for dest in destinations}
    approval_targets = [dest for dest in destinations if dest.get("approval_required")]
    outputs = _latest_video_outputs()
    audited_outputs = [out for out in outputs if out.get("audit", {}).get("passed")]
    active_offers = vault_db.list_offers(path=OUTPUT_DIR / "vault.db")
    credentials = vault_db.list_credentials(path=OUTPUT_DIR / "vault.db")
    encrypted_credentials = [c for c in credentials if c.secret_ref.startswith("fernet:")]
    credential_provider_ids = {
        c.provider for c in credentials
        if getattr(c, "status", "active") == "active"
    }
    capabilities = CapabilityRegistry(OUTPUT_DIR / "vault.db").list_capabilities()
    capability_stack: dict[str, list[str]] = {}
    missing_paid_provider_credentials: set[str] = set()
    for cap in capabilities:
        metadata = dict(getattr(cap, "metadata", {}) or {})
        config_schema = dict(metadata.get("config_schema") or {})
        credential_aliases = {cap.provider_id}
        for field in config_schema.values():
            if isinstance(field, dict) and field.get("provider"):
                credential_aliases.add(str(field.get("provider")))
        requires_credential = bool(metadata.get("requires_credential", False))
        has_credential = bool(credential_aliases & credential_provider_ids)
        if requires_credential and not has_credential:
            missing_paid_provider_credentials.add(cap.provider_id)
        if not requires_credential or has_credential:
            capability_stack.setdefault(cap.kind, []).append(cap.provider_id)
    required_generation_kinds = ("image", "video", "tts")
    provider_generation_stack_ready = all(
        capability_stack.get(kind) for kind in required_generation_kinds
    )
    post_metrics_ready = _vault_table_exists("post_metrics")
    affiliate_ready = all(_vault_table_exists(t) for t in [
        "offers", "placements", "clicks", "conversions", "revenue_events",
    ])
    credential_vault_ready = _vault_table_exists("credentials")
    capability_registry_ready = all(_vault_table_exists(t) for t in [
        "providers", "models",
    ])
    budget_guard_ready = all(_vault_table_exists(t) for t in [
        "usage_ledger", "budgets",
    ])
    runtime_router_ready = True

    checks = [
        {
            "name": "platform_contract",
            "passed": True,
            "evidence": "IPlatform contract + YouTube/TikTok adapters present",
        },
        {
            "name": "destinations_configured",
            "passed": bool(destinations),
            "evidence": f"{len(destinations)} destination(s) detected",
        },
        {
            "name": "second_platform_available",
            "passed": "tiktok" in {p.get("platform_id") for p in _platform_specs()},
            "evidence": "TikTok adapter available in dry-run/official API mode",
        },
        {
            "name": "vertical_variant_export",
            "passed": True,
            "evidence": "RenderVariantExporter can build 9:16 FFmpeg commands",
        },
        {
            "name": "approval_gate_configured",
            "passed": bool(approval_targets),
            "evidence": f"{len(approval_targets)} destination(s) require HITL approval",
        },
        {
            "name": "official_upload_only",
            "passed": True,
            "evidence": "YouTube uses Data API; TikTok adapter uses Content Posting API contract only",
        },
        {
            "name": "multi_platform_analytics",
            "passed": post_metrics_ready,
            "evidence": "Vault-backed post_metrics ingestion exists for all platforms",
        },
        {
            "name": "affiliate_tracking",
            "passed": affiliate_ready,
            "evidence": "Offer, placement, click, conversion, and revenue ledgers exist",
        },
        {
            "name": "credential_vault",
            "passed": credential_vault_ready,
            "evidence": "Credential vault schema and safe listing API exist",
        },
        {
            "name": "capability_registry",
            "passed": capability_registry_ready,
            "evidence": "Capability providers/models registry tables and /api/capabilities exist",
        },
        {
            "name": "budget_guard",
            "passed": budget_guard_ready,
            "evidence": "Vault-backed usage_ledger and budgets power persistent spend guards",
        },
        {
            "name": "runtime_router",
            "passed": runtime_router_ready,
            "evidence": "RuntimeRouter resolves local/remote/browser fallback with VRAM gating",
        },
        {
            "name": "provider_generation_stack",
            "passed": provider_generation_stack_ready,
            "evidence": ", ".join(
                f"{kind}: {', '.join(capability_stack.get(kind, [])) or 'missing'}"
                for kind in required_generation_kinds
            ),
        },
        {
            "name": "paid_provider_credentials",
            "passed": not missing_paid_provider_credentials,
            "evidence": (
                "All paid providers have matching credentials"
                if not missing_paid_provider_credentials
                else "Missing credentials for: " + ", ".join(sorted(missing_paid_provider_credentials))
            ),
        },
        {
            "name": "encrypted_credentials_configured",
            "passed": bool(encrypted_credentials),
            "evidence": f"{len(encrypted_credentials)} encrypted credential(s) configured",
        },
        {
            "name": "active_offer_configured",
            "passed": bool(active_offers),
            "evidence": f"{len(active_offers)} active offer(s) configured",
        },
        {
            "name": "sample_output_present",
            "passed": bool(outputs),
            "evidence": f"{len(outputs)} recent MP4 output(s) found" if outputs else "No MP4 output found",
        },
        {
            "name": "sample_output_technical_audit",
            "passed": bool(audited_outputs),
            "evidence": f"{len(audited_outputs)} recent MP4 output(s) passed ffprobe audit",
        },
    ]
    passed = sum(1 for check in checks if check["passed"])
    total = len(checks)
    ratio = passed / total if total else 0.0
    if ratio >= 0.85 and all(check["passed"] for check in checks if check["name"] in {
        "approval_gate_configured",
        "multi_platform_analytics",
        "affiliate_tracking",
        "credential_vault",
        "capability_registry",
        "budget_guard",
        "runtime_router",
        "provider_generation_stack",
        "encrypted_credentials_configured",
        "active_offer_configured",
        "sample_output_technical_audit",
    }):
        recommendation = "ship"
    elif ratio >= 0.5:
        recommendation = "wait"
    else:
        recommendation = "reject"
    blockers = [check for check in checks if not check["passed"]]
    return {
        "recommendation": recommendation,
        "score": round(ratio * 100, 1),
        "checks": checks,
        "blockers": blockers,
        "platform_ids": sorted(pid for pid in platform_ids if pid),
        "destination_count": len(destinations),
        "latest_outputs": outputs,
    }


@app.get("/api/platforms")
async def get_platforms():
    """M1 platform surfaces and format capabilities."""
    specs = _platform_specs()
    return {"platforms": specs, "total": len(specs)}


@app.get("/api/destinations")
async def get_destinations():
    """Channel publishing destinations. Legacy channels expose an implicit YouTube target."""
    destinations = []
    for ch in _all_channels():
        destinations.extend(_destinations_for_channel(ch))
    return {"destinations": destinations, "total": len(destinations)}


@app.get("/api/quota")
async def get_quota():
    """BS-1 — YouTube Data API quota estimate for today (units used vs daily limit).
    Counts today's uploads from vault.published_videos × per-upload cost."""
    from datetime import datetime, timezone
    from omnicast.vault import db as vault_db

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    try:
        pubs = vault_db.list_published(path=OUTPUT_DIR / "vault.db")
    except Exception:
        pubs = []
    uploads_today = sum(
        1 for p in pubs if str(getattr(p, "published_at", "") or "").startswith(today))
    try:
        from omnicast.upload.youtube_api import YouTubeUploader
        per = int(YouTubeUploader.estimate_quota_cost(True))
    except Exception:
        per = 1600
    limit = int(os.environ.get("OMNICAST_YT_QUOTA_LIMIT", "10000"))
    return {
        "used_units": uploads_today * per,
        "limit_units": limit,
        "uploads_today": uploads_today,
        "per_upload_units": per,
        "reset_hint": "00:00 America/Los_Angeles",
    }


@app.get("/api/credentials")
async def list_safe_credentials(provider: str | None = None):
    """Safe credential listing. Secret values are never returned."""
    from os import getenv
    from omnicast.services.credential_vault import CredentialVault

    vault = CredentialVault(
        db_path=OUTPUT_DIR / "vault.db",
        encryption_key=getenv("OMNICAST_CREDENTIAL_FERNET_KEY"),
    )
    credentials = vault.list_safe(provider)
    return {"credentials": credentials, "total": len(credentials)}


@app.post("/api/credentials")
async def store_credential(payload: dict = Body(...)):
    """Store a provider credential in the vault. Requires provider/account_id/secret."""
    from os import getenv
    from omnicast.services.credential_vault import CredentialVault

    provider = str(payload.get("provider") or "").strip()
    account_id = str(payload.get("account_id") or "").strip()
    secret = str(payload.get("secret") or "")
    if not provider or not account_id or not secret:
        raise HTTPException(400, "provider, account_id and secret are required")
    vault = CredentialVault(
        db_path=OUTPUT_DIR / "vault.db",
        encryption_key=getenv("OMNICAST_CREDENTIAL_FERNET_KEY"),
    )
    record = vault.store_secret(
        provider=provider,
        account_id=account_id,
        secret=secret,
        label=str(payload.get("label") or ""),
        scopes=list(payload.get("scopes") or []),
        priority=int(payload.get("priority") or 100),
    )
    return {
        "credential_id": record.credential_id,
        "provider": record.provider,
        "account_id": record.account_id,
        "encrypted": record.secret_ref.startswith("fernet:"),
    }


@app.post("/api/platforms/metrics")
async def ingest_platform_metrics(payload: dict = Body(...)):
    """Ingest official or manual post metrics for any platform."""
    from omnicast.platforms.analytics_store import PlatformAnalyticsStore
    from omnicast.platforms.models import PlatformId, PostStats

    stats = PostStats(
        platform_id=PlatformId(str(payload["platform_id"])),
        account_id=str(payload["account_id"]),
        post_id=str(payload["post_id"]),
        channel_id=str(payload.get("channel_id") or ""),
        views=int(payload.get("views") or 0),
        likes=int(payload.get("likes") or 0),
        comments=int(payload.get("comments") or 0),
        shares=int(payload.get("shares") or 0),
        watch_time_seconds=float(payload.get("watch_time_seconds") or 0.0),
        revenue=float(payload.get("revenue") or 0.0),
        raw=dict(payload.get("raw") or {}),
    )
    store = PlatformAnalyticsStore(OUTPUT_DIR / "vault.db")
    store.record(stats)
    return {"status": "recorded", "post_id": stats.post_id, "platform_id": stats.platform_id}


@app.get("/api/platforms/metrics")
async def list_platform_metrics(channel_id: str):
    from omnicast.platforms.analytics_store import PlatformAnalyticsStore

    store = PlatformAnalyticsStore(OUTPUT_DIR / "vault.db")
    metrics = [m.model_dump(mode="json") for m in store.list_channel(channel_id)]
    return {"metrics": metrics, "total": len(metrics)}


@app.get("/api/published")
async def list_published_videos(channel_id: str | None = None):
    """I3 — published ledger, so the UI can map a platform metrics row (post_id =
    youtube_video_id) back to the script/product that generated it (join on title)."""
    from omnicast.vault import db as vault_db

    vault_db.init_db(OUTPUT_DIR / "vault.db")
    pubs = vault_db.list_published(channel_id=channel_id, path=OUTPUT_DIR / "vault.db")
    items = [{"video_id": p.video_id, "channel_id": p.channel_id, "title": p.title,
              "youtube_video_id": p.youtube_video_id, "published_at": p.published_at,
              "status": p.status} for p in pubs]
    return {"published": items, "total": len(items)}


@app.get("/api/monetization/offers")
async def list_affiliate_offers():
    from omnicast.vault import db as vault_db

    vault_db.init_db(OUTPUT_DIR / "vault.db")
    offers = [o.__dict__ for o in vault_db.list_offers(path=OUTPUT_DIR / "vault.db")]
    return {"offers": offers, "total": len(offers)}


@app.post("/api/monetization/offers")
async def upsert_affiliate_offer(payload: dict = Body(...)):
    from datetime import datetime, timezone
    from omnicast.monetization.affiliate import AffiliateService
    from omnicast.vault.models import OfferRecord

    offer_id = str(payload.get("offer_id") or "").strip()
    name = str(payload.get("name") or "").strip()
    url = str(payload.get("url") or "").strip()
    if not offer_id or not name or not url:
        raise HTTPException(400, "offer_id, name and url are required")
    now = datetime.now(timezone.utc).isoformat()
    offer = OfferRecord(
        offer_id=offer_id,
        name=name,
        network=str(payload.get("network") or ""),
        url=url,
        niches=list(payload.get("niches") or []),
        commission_type=str(payload.get("commission_type") or "unknown"),
        commission_value=float(payload.get("commission_value") or 0.0),
        disclosure=str(
            payload.get("disclosure")
            or "As an affiliate, we may earn from qualifying purchases."
        ),
        status=str(payload.get("status") or "active"),
        created_at=now,
        updated_at=now,
    )
    AffiliateService(OUTPUT_DIR / "vault.db").upsert_offer(offer)
    return {"status": "saved", "offer_id": offer.offer_id}


@app.get("/r/{placement_id}")
async def track_affiliate_redirect(placement_id: str):
    """Track an affiliate click and redirect to the placement destination."""
    from omnicast.monetization.redirect import RedirectService
    from omnicast.shared.errors import NotFoundError

    try:
        url = RedirectService(OUTPUT_DIR / "vault.db").track_click(placement_id)
    except NotFoundError as exc:
        raise HTTPException(404, exc.message) from exc
    return RedirectResponse(url, status_code=302)


@app.post("/api/monetization/conversions")
async def record_affiliate_conversion(payload: dict = Body(...)):
    from omnicast.monetization.affiliate import AffiliateService

    placement_id = str(payload.get("placement_id") or "").strip()
    amount = float(payload.get("amount") or 0.0)
    if not placement_id or amount <= 0:
        raise HTTPException(400, "placement_id and positive amount are required")
    record = AffiliateService(OUTPUT_DIR / "vault.db").record_conversion(
        placement_id=placement_id,
        amount=amount,
        currency=str(payload.get("currency") or "USD"),
        raw=dict(payload.get("raw") or {}),
    )
    return {"status": "recorded", "conversion_id": record.conversion_id}


@app.get("/api/capabilities")
async def list_capabilities(kind: str | None = None):
    from omnicast.capabilities.registry import CapabilityRegistry

    registry = CapabilityRegistry(OUTPUT_DIR / "vault.db")
    capabilities = [
        {
            "capability_id": c.capability_id,
            "kind": c.kind,
            "provider_id": c.provider_id,
            "model_id": c.model_id,
            "runtime": c.runtime,
            "cost_per_unit": c.cost_per_unit,
            "min_vram_mb": c.min_vram_mb,
            "fallback": c.fallback,
            "metadata": c.metadata,
        }
        for c in registry.list_capabilities(kind)
    ]
    return {"capabilities": capabilities, "total": len(capabilities)}


@app.post("/api/capabilities/{kind}/{provider_id}/health")
async def check_capability_health(kind: str, provider_id: str):
    """Probe a provider without generating paid media/content output."""
    import inspect
    from os import getenv

    from omnicast.capabilities.registry import CapabilityRegistry
    from omnicast.services.credential_vault import CredentialVault

    kind = str(kind or "").strip()
    provider_id = str(provider_id or "").strip()
    if not kind or not provider_id:
        raise HTTPException(400, "kind and provider_id are required")

    registry = CapabilityRegistry(OUTPUT_DIR / "vault.db")
    matches = [
        c for c in registry.list_capabilities(kind)
        if c.provider_id == provider_id
    ]
    capability = matches[0] if matches else None
    metadata = dict(getattr(capability, "metadata", {}) or {})
    config_schema = dict(metadata.get("config_schema") or {})
    credential_aliases = {provider_id}
    for field in config_schema.values():
        if isinstance(field, dict) and field.get("provider"):
            credential_aliases.add(str(field.get("provider")))
    credential_vault = CredentialVault(
        db_path=OUTPUT_DIR / "vault.db",
        encryption_key=getenv("OMNICAST_CREDENTIAL_FERNET_KEY"),
    )
    safe_credentials = []
    for alias in sorted(credential_aliases):
        safe_credentials.extend(credential_vault.list_safe(alias))
    requires_credential = bool(metadata.get("requires_credential", False))
    missing_required_credential = requires_credential and not safe_credentials

    try:
        if kind == "image":
            from omnicast.media.providers.registry import get_image_provider
            provider = get_image_provider(provider_id)
        elif kind == "video":
            from omnicast.media.providers.registry import get_video_provider
            provider = get_video_provider(provider_id)
        elif kind == "tts":
            from omnicast.media.providers.registry import get_tts_provider
            provider = get_tts_provider(provider_id)
        else:
            ok = capability is not None and not missing_required_credential
            return {
                "ok": ok,
                "mode": "registry",
                "capability": kind,
                "provider_id": provider_id,
                "registered": capability is not None,
                "requires_credential": requires_credential,
                "credentials_present": bool(safe_credentials),
                "credential_count": len(safe_credentials),
                "message": (
                    "Missing required credential for this provider."
                    if missing_required_credential
                    else "Registered capability; no active provider probe is defined for this kind."
                ),
            }

        if missing_required_credential:
            return JSONResponse(
                {
                    "ok": False,
                    "mode": "provider",
                    "capability": kind,
                    "provider_id": provider_id,
                    "registered": capability is not None,
                    "requires_credential": True,
                    "credentials_present": False,
                    "credential_count": 0,
                    "credential_aliases": sorted(credential_aliases),
                    "error": "Missing required credential for this provider.",
                },
                status_code=503,
            )

        health_fn = getattr(provider, "health_check", None)
        health = health_fn() if callable(health_fn) else {"ok": True}
        if inspect.isawaitable(health):
            health = await health
        if isinstance(health, bool):
            health = {"ok": health}
        if not isinstance(health, dict):
            health = {"ok": True, "detail": str(health)}
        ok = bool(health.get("ok", True))
        body = {
            "ok": ok,
            "mode": "provider",
            "capability": kind,
            "provider_id": provider_id,
            "provider_name": getattr(provider, "name", provider_id),
            "requires_credential": requires_credential,
            "credentials_present": bool(safe_credentials),
            "credential_count": len(safe_credentials),
            "health": health,
        }
        if ok:
            return body
        return JSONResponse(body, status_code=503)
    except Exception as exc:
        return JSONResponse(
            {
                "ok": False,
                "mode": "provider",
                "capability": kind,
                "provider_id": provider_id,
                "registered": capability is not None,
                "requires_credential": requires_credential,
                "credentials_present": bool(safe_credentials),
                "credential_count": len(safe_credentials),
                "error": str(exc)[:500],
            },
            status_code=503,
        )


@app.get("/api/budgets")
async def list_budgets():
    from omnicast.vault import db as vault_db

    vault_db.init_db(OUTPUT_DIR / "vault.db")
    budgets = [b.__dict__ for b in vault_db.list_budgets(OUTPUT_DIR / "vault.db")]
    usage_total = vault_db.sum_usage_cost(path=OUTPUT_DIR / "vault.db")
    return {"budgets": budgets, "usage_total_usd": usage_total, "total": len(budgets)}


@app.post("/api/budgets")
async def set_budget(payload: dict = Body(...)):
    from omnicast.credentials.budget_guard import BudgetGuard

    scope = str(payload.get("scope") or "global")
    scope_id = str(payload.get("scope_id") or "default")
    limit_usd = float(payload.get("limit_usd") or 0.0)
    if limit_usd < 0:
        raise HTTPException(400, "limit_usd must be non-negative")
    record = BudgetGuard(OUTPUT_DIR / "vault.db").set_budget(
        scope=scope,
        scope_id=scope_id,
        limit_usd=limit_usd,
        reset_at=payload.get("reset_at"),
    )
    return {"status": "saved", "budget": record.__dict__}


@app.get("/api/usage")
async def list_usage(scope: str | None = None, scope_id: str | None = None):
    from omnicast.vault import db as vault_db

    vault_db.init_db(OUTPUT_DIR / "vault.db")
    usage = [u.__dict__ for u in vault_db.list_usage(scope, scope_id, OUTPUT_DIR / "vault.db")]
    return {
        "usage": usage,
        "total": len(usage),
        "cost_usd": vault_db.sum_usage_cost(scope, scope_id, OUTPUT_DIR / "vault.db"),
    }


@app.get("/api/monetization/readiness")
async def get_monetization_readiness():
    """Operational readiness for turning on monetized/public publishing."""
    return _monetization_readiness()


def _ensure_approvals_table() -> None:
    from omnicast.vault import db as vault_db

    vault_db.init_db(OUTPUT_DIR / "vault.db")
    with vault_db._connect(OUTPUT_DIR / "vault.db") as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS approvals (
                approval_id    TEXT PRIMARY KEY,
                job_id         TEXT NOT NULL DEFAULT '',
                channel_id     TEXT NOT NULL DEFAULT '',
                video_id       TEXT NOT NULL DEFAULT '',
                destination_id TEXT NOT NULL DEFAULT '',
                platform_id    TEXT NOT NULL DEFAULT '',
                video_path     TEXT NOT NULL DEFAULT '',
                title          TEXT NOT NULL DEFAULT '',
                summary        TEXT NOT NULL DEFAULT '',
                status         TEXT NOT NULL DEFAULT 'waiting_approval',
                requested_at   TEXT NOT NULL,
                decided_at     TEXT,
                decided_by     TEXT,
                decision_note  TEXT NOT NULL DEFAULT '',
                raw            TEXT NOT NULL DEFAULT '{}'
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_approvals_status ON approvals(status, requested_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_approvals_channel ON approvals(channel_id, requested_at)")


def _approval_row_to_dict(row) -> dict:
    import json

    data = dict(row)
    try:
        data["raw"] = json.loads(data.get("raw") or "{}")
    except Exception:
        data["raw"] = {}
    return data


@app.get("/api/approvals")
async def list_approvals(status: str | None = "waiting_approval"):
    from omnicast.vault import db as vault_db

    _ensure_approvals_table()
    query = "SELECT * FROM approvals"
    args: list[str] = []
    if status:
        query += " WHERE status=?"
        args.append(status)
    query += " ORDER BY requested_at DESC LIMIT 100"
    with vault_db._connect(OUTPUT_DIR / "vault.db") as conn:
        rows = conn.execute(query, args).fetchall()
    approvals = [_approval_row_to_dict(r) for r in rows]
    return {"approvals": approvals, "total": len(approvals)}


@app.post("/api/approvals")
async def create_approval(payload: dict = Body(...)):
    import hashlib
    import json
    from datetime import datetime, timezone

    from omnicast.vault import db as vault_db

    _ensure_approvals_table()
    now = datetime.now(timezone.utc).isoformat()
    seed = "|".join(str(payload.get(k) or "") for k in (
        "job_id", "channel_id", "video_id", "destination_id", "platform_id", "video_path", "title",
    ))
    approval_id = str(payload.get("approval_id") or hashlib.sha256(f"{seed}|{now}".encode()).hexdigest()[:20])
    with vault_db._connect(OUTPUT_DIR / "vault.db") as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO approvals
                (approval_id, job_id, channel_id, video_id, destination_id, platform_id,
                 video_path, title, summary, status, requested_at, raw)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'waiting_approval', ?, ?)
            """,
            (
                approval_id,
                str(payload.get("job_id") or ""),
                str(payload.get("channel_id") or ""),
                str(payload.get("video_id") or ""),
                str(payload.get("destination_id") or ""),
                str(payload.get("platform_id") or ""),
                str(payload.get("video_path") or ""),
                str(payload.get("title") or ""),
                str(payload.get("summary") or ""),
                now,
                json.dumps(dict(payload.get("raw") or {}), ensure_ascii=False),
            ),
        )
        row = conn.execute("SELECT * FROM approvals WHERE approval_id=?", (approval_id,)).fetchone()
    
    try:
        _get_job_engine().events.emit(
            "approval.created",
            job_id=str(payload.get("job_id") or ""),
            approval_id=approval_id,
            channel_id=str(payload.get("channel_id") or "")
        )
    except Exception:
        pass

    return {"status": "queued", "approval": _approval_row_to_dict(row)}


@app.post("/api/publish/{channel_id}")
async def queue_channel_publish(channel_id: str, payload: dict = Body(default_factory=dict)):
    """Queue the latest rendered product for HITL publish approval."""
    from pathlib import Path as _Path

    from omnicast.storage import products as _products

    channel_file = CHANNELS_DIR / f"{channel_id}.json"
    if not channel_file.exists():
        raise HTTPException(404, f"Channel not found: {channel_id}")
    channel = _load_channel_json(channel_file)

    requested_video = str(payload.get("video_path") or "").strip()
    video = _Path(requested_video) if requested_video else _products.latest_video(channel_id)
    if not video or not video.exists():
        raise HTTPException(404, f"No rendered video found for channel {channel_id}")

    product_dir = video.parent
    product_meta = _products.read_meta(product_dir)
    title_file = video.with_name(video.stem + "_title.txt")
    title = str(payload.get("title") or product_meta.get("title") or "").strip()
    if not title and title_file.exists():
        title = title_file.read_text(encoding="utf-8", errors="ignore").strip()
    title = (title or video.stem)[:100]

    description = str(payload.get("description") or product_meta.get("description") or "").strip()
    if not description:
        description = f"{title}\n\nMade with AI (AI-generated narration & visuals)."
    privacy_status = str(payload.get("privacy_status") or "private")
    if privacy_status not in {"private", "unlisted", "public"}:
        privacy_status = "private"
    raw_tags = payload.get("tags") or product_meta.get("tags") or []
    tags = [t.strip() for t in raw_tags.split(",") if t.strip()] if isinstance(raw_tags, str) else list(raw_tags)
    raw_thumbs = payload.get("thumbnail_paths") or []
    thumbnail_paths = [raw_thumbs] if isinstance(raw_thumbs, str) and raw_thumbs.strip() else list(raw_thumbs)

    destinations = [d for d in _destinations_for_channel(channel) if d.get("enabled", True)]
    if not destinations:
        raise HTTPException(400, f"No enabled publish destinations for channel {channel_id}")

    approvals = []
    for destination in destinations:
        queued = await create_approval({
            "job_id": str(payload.get("job_id") or f"manual_publish:{channel_id}"),
            "channel_id": channel_id,
            "video_id": str(payload.get("video_id") or product_meta.get("slug") or video.stem),
            "destination_id": destination.get("destination_id") or f"{channel_id}_{destination.get('platform_id', 'manual')}",
            "platform_id": destination.get("platform_id") or "youtube",
            "video_path": str(video.resolve()),
            "title": title,
            "summary": description,
            "raw": {
                "account_id": channel_id if destination.get("platform_id") == "youtube" else destination.get("account_id") or channel_id,
                "destination_account_id": destination.get("account_id") or "",
                "format_variant": destination.get("format_variant") or "youtube_16x9",
                "privacy_status": privacy_status,
                "description": description,
                "tags": tags,
                "niche": channel.get("niche") or product_meta.get("niche") or "",
                "thumbnail_paths": thumbnail_paths,
                "dry_run": bool(payload.get("dry_run", destination.get("platform_id") != "youtube")),
            },
        })
        approvals.append(queued["approval"])
    return {"status": "waiting_approval", "approvals": approvals, "total": len(approvals)}


async def _publish_approved_video(row: dict) -> dict:
    """Real continuation of an 'approve' decision: compliance gate → YouTube
    upload → dedup ledger. Returns a dict merged into the approval's `raw`
    column so the operator can see exactly what happened (youtube_video_id,
    url, or the failure reason) — approving never silently no-ops anymore.
    """
    from omnicast.platforms.service import publish_approval_row

    return await publish_approval_row(
        row,
        channels_dir=CHANNELS_DIR,
        output_dir=OUTPUT_DIR,
        impl_root=IMPL_ROOT,
    )

    import json as _json
    from datetime import datetime, timezone
    from pathlib import Path as _Path

    from omnicast.config.channel import ChannelProfileLoader
    from omnicast.upload.compliance import ComplianceChecker
    from omnicast.upload.models import UploadMetadata, UploadRequest
    from omnicast.upload.oauth import OAuth2Manager
    from omnicast.upload.scheduler import UploadScheduler
    from omnicast.upload.orchestrator import UploadPipelineOrchestrator
    from omnicast.upload.youtube_api import YouTubeUploader
    from omnicast.config.settings import get_settings
    from omnicast.models.enums import ChannelType
    from omnicast.vault import db as vault_db
    from omnicast.vault.models import PublishedVideo

    channel_id = str(row.get("channel_id") or "")
    video_path = str(row.get("video_path") or "")
    raw = row.get("raw") or {}
    if isinstance(raw, str):
        try:
            raw = _json.loads(raw)
        except Exception:
            raw = {}

    if not channel_id or not video_path:
        return {"publish_error": "missing channel_id or video_path on approval row"}
    vpath = _Path(video_path)
    if not vpath.exists():
        return {"publish_error": f"video file not found: {video_path}"}

    settings = get_settings()
    mgr = OAuth2Manager(
        token_dir=str(IMPL_ROOT / settings.youtube_token_dir),
        encryption_key=settings.youtube_token_key or None,
    )
    if not mgr.has_token(channel_id):
        return {"publish_error": f"channel '{channel_id}' not authorized — "
                                  f"run scripts/youtube_authorize.py --channel {channel_id}"}

    title = str(row.get("title") or vpath.stem)[:100]
    description = str(row.get("summary") or raw.get("description") or "").strip()
    if not description:
        description = (title + "\n\nMade with AI (AI-generated narration & visuals).")
    tags = list(raw.get("tags") or [])
    privacy_status = str(raw.get("privacy_status") or "private")
    if privacy_status not in ("private", "unlisted", "public"):
        privacy_status = "private"

    thumb_candidates = list(raw.get("thumbnail_paths") or [])
    if not thumb_candidates:
        sibling = vpath.with_name(vpath.stem + "_thumb.png")
        if sibling.exists():
            thumb_candidates = [str(sibling.resolve())]

    meta = UploadMetadata(title=title, description=description, tags=tags,
                          privacy_status=privacy_status)

    try:
        channel = await ChannelProfileLoader(CHANNELS_DIR).load(channel_id)
    except Exception:
        channel = None

    comp = ComplianceChecker()
    req_for_check = UploadRequest(
        video_id=str(row.get("video_id") or vpath.stem), channel_id=channel_id,
        video_path=str(vpath.resolve()), thumbnail_paths=thumb_candidates, metadata=meta,
    )
    comp_result = comp.check(req_for_check)
    if not comp_result.passed and not bool(raw.get("force")):
        return {"publish_error": "compliance_blocked", "violations": comp_result.violations,
                "checks": comp_result.checks}

    orchestrator = UploadPipelineOrchestrator(
        compliance=comp, scheduler=UploadScheduler(), uploader=YouTubeUploader(mgr),
    )
    state, result = await orchestrator.run(
        video_id=str(row.get("video_id") or vpath.stem),
        channel_id=channel_id,
        channel_type=(channel.channel_type if channel else None) or ChannelType.HUB,
        video_path=str(vpath.resolve()),
        metadata=meta,
        thumbnail_paths=thumb_candidates,
        channel=channel,
    )
    if result is None or result.status.value == "failed":
        return {"publish_error": (result.error if result else "upload pipeline rejected "
                                   "(compliance/scheduling failed before upload)")}

    try:
        vault_db.init_db(OUTPUT_DIR / "vault.db")
        vault_db.record_published(PublishedVideo(
            video_id=f"{channel_id}:{vpath.stem}", channel_id=channel_id, title=title,
            youtube_video_id=result.youtube_video_id,
            published_at=datetime.now(timezone.utc).isoformat(), status="uploaded",
        ), OUTPUT_DIR / "vault.db")
    except Exception:
        pass

    # Stamp the PRODUCT manifest as uploaded. This is what moves a product out of
    # the Xưởng (WIP workspace) and into the Thư viện (finished library): the UI
    # filters on meta.youtube_id.
    try:
        from omnicast.storage import products as _prod_store
        _ppd = vpath.parent
        if (_ppd / "meta.json").exists():
            _prod_store.write_meta(
                _ppd, youtube_id=result.youtube_video_id, youtube_url=result.url,
                uploaded_at=datetime.now(timezone.utc).isoformat(), status="uploaded")
    except Exception:
        pass

    return {
        "youtube_video_id": result.youtube_video_id,
        "url": result.url,
        "thumbnail_set": result.thumbnail_set,
        "privacy_status": privacy_status,
    }


@app.post("/api/approvals/{approval_id}/{decision}")
async def decide_approval(approval_id: str, decision: str, payload: dict = Body(default_factory=dict)):
    import json as _json
    from datetime import datetime, timezone

    from omnicast.vault import db as vault_db

    decision = str(decision or "").lower()
    if decision not in {"approve", "reject"}:
        raise HTTPException(400, "decision must be approve or reject")
    _ensure_approvals_table()
    now = datetime.now(timezone.utc).isoformat()
    with vault_db._connect(OUTPUT_DIR / "vault.db") as conn:
        row = conn.execute("SELECT * FROM approvals WHERE approval_id=?", (approval_id,)).fetchone()
        if not row:
            raise HTTPException(404, "approval not found")
        row_dict = _approval_row_to_dict(row)

    status = "rejected"
    publish_outcome: dict = {}
    if decision == "approve":
        # Merge any per-decision overrides (privacy_status, force, tags, description)
        # from the request body into the approval's raw payload before publishing.
        merged_raw = dict(row_dict.get("raw") or {})
        merged_raw.update({k: v for k, v in payload.items()
                           if k in ("privacy_status", "force", "tags", "description")})
        row_dict["raw"] = merged_raw
        try:
            publish_outcome = await _publish_approved_video(row_dict)
        except Exception as exc:
            publish_outcome = {"publish_error": str(exc)[:400]}
        publish_status = str(publish_outcome.get("publish_status") or "")
        status = (
            "published"
            if not publish_outcome.get("publish_error") and publish_status in {"published", "draft", "scheduled"}
            else "approve_failed"
        )

    with vault_db._connect(OUTPUT_DIR / "vault.db") as conn:
        row = conn.execute("SELECT * FROM approvals WHERE approval_id=?", (approval_id,)).fetchone()
        raw = _approval_row_to_dict(row).get("raw") or {}
        raw.update(publish_outcome)
        conn.execute(
            """
            UPDATE approvals
            SET status=?, decided_at=?, decided_by=?, decision_note=?, raw=?
            WHERE approval_id=?
            """,
            (
                status,
                now,
                str(payload.get("operator") or "dashboard"),
                str(payload.get("note") or ""),
                _json.dumps(raw, ensure_ascii=False),
                approval_id,
            ),
        )
        updated = conn.execute("SELECT * FROM approvals WHERE approval_id=?", (approval_id,)).fetchone()
    return {"status": status, "approval": _approval_row_to_dict(updated)}


def _channel_card(ch: dict, stats_by_id: dict, pipeline: dict) -> dict:
    """Merge a channel config with its cached YouTube stats for a card view."""
    cid = ch.get("channel_id", "")
    s = stats_by_id.get(cid)
    ch_state = pipeline.get("channels", {}).get(cid, {})
    return {
        "channel_id": cid,
        "name": ch.get("name", cid),
        "niche": ch.get("niche", ""),
        "niches": ch.get("niches", []),
        "market": ch.get("market", "US"),
        "avatar_url": s.avatar_url if s else "",
        "youtube_channel_id": ch.get("youtube_channel_id", "") or (s.youtube_channel_id if s else ""),
        "subscribers": s.subscribers if s else 0,
        "total_views": s.total_views if s else 0,
        "video_count": s.video_count if s else 0,
        "est_revenue_usd": s.est_revenue_usd if s else 0.0,
        "health": s.health if s else 0,
        "linked": bool(s and s.youtube_channel_id),
        "status": ch_state.get("status", "idle"),
        "fetched_at": s.fetched_at if s else None,
    }


@app.get("/api/channels/overview")
async def channels_overview():
    """Channels management overview: aggregate KPIs + per-channel cards (merges
    channel configs with cached YouTube stats from vault.db)."""
    from omnicast.vault import db as vault_db
    VAULT_DB = OUTPUT_DIR / "vault.db"
    vault_db.init_db(VAULT_DB)
    stats_by_id = {s.channel_id: s for s in vault_db.list_channel_stats(VAULT_DB)}
    pipeline = read_pipeline_state()
    channels = _all_channels()
    cards = [_channel_card(ch, stats_by_id, pipeline) for ch in channels]
    return {
        "totals": {
            "channels": len(cards),
            "views": sum(c["total_views"] for c in cards),
            "videos": sum(c["video_count"] for c in cards),
            "subscribers": sum(c["subscribers"] for c in cards),
            "est_revenue_usd": round(sum(c["est_revenue_usd"] for c in cards), 2),
            "linked": sum(1 for c in cards if c["linked"]),
        },
        "channels": sorted(cards, key=lambda c: c["total_views"], reverse=True),
    }


@app.post("/api/channels/refresh-stats")
async def channels_refresh_stats(channel_id: str | None = None):
    """Pull fresh public YouTube stats (channels.list) for one or all channels
    and cache them in vault.db. Needs youtube_api_key + each channel's
    youtube_channel_id. Returns per-channel results (linked / hint)."""
    from omnicast.analytics import youtube_stats
    from omnicast.vault import db as vault_db
    settings = get_settings()
    api_key = settings.youtube_api_key
    VAULT_DB = OUTPUT_DIR / "vault.db"
    vault_db.init_db(VAULT_DB)
    targets = _all_channels()
    if channel_id:
        targets = [c for c in targets if c.get("channel_id") == channel_id]
        if not targets:
            raise HTTPException(404, f"Channel {channel_id} not found")
    if not api_key:
        raise HTTPException(412, "youtube_api_key not configured (settings).")
    results = [youtube_stats.refresh_channel_stats(ch, api_key, VAULT_DB) for ch in targets]
    linked = sum(1 for r in results if r.get("linked"))
    return {"refreshed": len(results), "linked": linked, "results": results}


@app.get("/api/analytics/{channel_id}")
async def channel_analytics(channel_id: str, days: int = 28):
    """Channel health from the vault daily time series (views, watch time,
    subscriber growth, revenue, AVD, trends, anomalies). No API call — use the
    POST endpoint below to pull fresh data first."""
    from omnicast.analytics import collector
    from omnicast.vault import db as vault_db
    VAULT_DB = OUTPUT_DIR / "vault.db"
    vault_db.init_db(VAULT_DB)
    summary = collector.summarize(channel_id, days=days, vault_db_path=VAULT_DB)
    summary["daily"] = vault_db.list_channel_metrics_daily(channel_id, days, VAULT_DB)
    return summary


@app.post("/api/analytics/{channel_id}/collect")
async def channel_analytics_collect(channel_id: str, days: int = 28):
    """Pull real YouTube Analytics (watch time / AVD / subs / revenue) via the
    channel's OAuth token into vault.channel_metrics_daily, then return the
    refreshed health summary. Token must include analytics scopes
    (scripts/youtube_authorize.py --analytics)."""
    from omnicast.analytics import collector
    from omnicast.upload.oauth import OAuth2Manager
    from omnicast.vault import db as vault_db
    settings = get_settings()
    VAULT_DB = OUTPUT_DIR / "vault.db"
    vault_db.init_db(VAULT_DB)
    oauth = OAuth2Manager(token_dir=settings.youtube_token_dir,
                          encryption_key=settings.youtube_token_key or None)
    return await collector.collect_and_store(
        channel_id, oauth, date_range=days, vault_db_path=VAULT_DB)


@app.get("/api/channels/{channel_id}/detail")
async def channel_detail(channel_id: str):
    """Everything an operator needs about one channel: full config + cached stats
    + assigned niches + topic-vault counts + recent activity."""
    file_path = CHANNELS_DIR / f"{channel_id}.json"
    if not file_path.exists():
        raise HTTPException(404, f"Channel {channel_id} not found")
    cfg = json.loads(file_path.read_text(encoding="utf-8"))
    from omnicast.vault import db as vault_db
    VAULT_DB = OUTPUT_DIR / "vault.db"
    vault_db.init_db(VAULT_DB)
    stats = vault_db.get_channel_stats(channel_id, VAULT_DB)
    topic_counts = vault_db.count_topics(channel_id, VAULT_DB)
    pipeline = read_pipeline_state()
    recent = [e for e in pipeline.get("recent_results", [])
              if e.get("channel_id") == channel_id][:10]
    return {
        "config": cfg,
        "stats": stats.__dict__ if stats else None,
        "niches": cfg.get("niches", []),
        "topic_counts": topic_counts,
        "recent_activity": recent,
    }


@app.get("/api/channels/{channel_id}")
async def get_channel(channel_id: str):
    """Get full JSON config of a specific channel."""
    file_path = CHANNELS_DIR / f"{channel_id}.json"
    if not file_path.exists():
        raise HTTPException(status_code=404, detail=f"Channel {channel_id} not found")
    try:
        return json.loads(file_path.read_text(encoding="utf-8"))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error reading channel: {e}")


@app.post("/api/channels")
async def create_channel(body: dict = Body(...)):
    """Create a new channel configuration."""
    channel_id = body.get("channel_id")
    if not channel_id:
        raise HTTPException(status_code=400, detail="channel_id is required")
        
    file_path = CHANNELS_DIR / f"{channel_id}.json"
    if file_path.exists():
        raise HTTPException(status_code=409, detail=f"Channel {channel_id} already exists")
        
    file_path.write_text(json.dumps(body, indent=2, ensure_ascii=False), encoding="utf-8")
    return {"status": "created", "channel_id": channel_id}


@app.put("/api/channels/{channel_id}")
async def update_channel(channel_id: str, body: dict = Body(...)):
    """Update an existing channel configuration."""
    file_path = CHANNELS_DIR / f"{channel_id}.json"
    if not file_path.exists():
        raise HTTPException(status_code=404, detail=f"Channel {channel_id} not found")
        
    existing = json.loads(file_path.read_text(encoding="utf-8"))
    existing.update(body)
    existing["channel_id"] = channel_id  # Enforce identity
    
    file_path.write_text(json.dumps(existing, indent=2, ensure_ascii=False), encoding="utf-8")
    return {"status": "updated", "channel_id": channel_id}


@app.delete("/api/channels/{channel_id}")
async def delete_channel(channel_id: str):
    """Delete a channel configuration."""
    file_path = CHANNELS_DIR / f"{channel_id}.json"
    if not file_path.exists():
        raise HTTPException(status_code=404, detail=f"Channel {channel_id} not found")
        
    file_path.unlink()
    return {"status": "deleted", "channel_id": channel_id}


@app.get("/api/pipeline")
async def get_pipeline():
    """Active jobs + recent results.

    Each active job is enriched with computed `elapsed_seconds` and `eta_seconds`
    (linear extrapolation from progress velocity) so the operator can answer
    "how long until this finishes?" without leaving the dashboard.
    """
    state = read_pipeline_state()
    now = datetime.utcnow()
    enriched = []
    for job in state.get("active_jobs", []):
        job = dict(job)  # shallow copy; don't mutate the file on read
        # Elapsed
        elapsed = None
        if job.get("started_at"):
            try:
                elapsed = int((now - datetime.fromisoformat(job["started_at"])).total_seconds())
            except Exception:
                elapsed = None
        job["elapsed_seconds"] = elapsed
        # ETA (only meaningful when 0 < pct < 100 and we have elapsed)
        pct = job.get("progress_pct")
        if (elapsed is not None and elapsed > 0
                and isinstance(pct, (int, float)) and 0 < pct < 100):
            try:
                job["eta_seconds"] = int(elapsed / pct * (100 - pct))
            except Exception:
                job["eta_seconds"] = None
        else:
            job["eta_seconds"] = None
        enriched.append(job)
    return {
        "active_jobs":     enriched,
        "recent_results":  state.get("recent_results", []),
        "last_updated":    state.get("last_updated"),
    }


@app.get("/api/errors")
async def get_errors(limit: int = 20):
    """Recent background-task failures with full Python traceback.

    Polled by the dashboard so the operator never needs to SSH+tail logs.
    Returns provenance envelope.
    """
    log = read_error_log()
    limit = max(1, min(int(limit or 20), 50))
    return _envelope(
        payload={
            "errors": log[:limit],
            "total":  len(log),
        },
        source="json_state",
    )


@app.post("/api/errors/clear")
async def post_errors_clear():
    """Operator-triggered cleanup of the error log.

    Audit-trail: we don't delete the file silently; the timestamp of the clear is
    recorded so the operator can see "this log was reset at X" on next page load.
    """
    clear_error_log()
    # Drop an info-level marker so the cleared-at timestamp is visible
    append_error(
        channel_id="__system__",
        phase="audit",
        stage="log_cleared",
        message="Operator cleared the error log via /api/errors/clear",
        traceback_str="",
    )
    return _envelope(payload={"ok": True}, source="json_state")


@app.get("/api/niches")
async def get_niches():
    """Latest niche discovery results."""
    data = read_niche_results()
    return data


@app.get("/api/budget")
async def get_budget():
    """Cost tracking. Aggregates real per-event costs from the pipeline log so
    the figure reflects actual spend even when accumulate_cost wasn't wired into
    a given phase (cost_state.json would otherwise read 0)."""
    cost = read_cost_state()
    try:
        pl = read_pipeline_state()
        events = pl.get("recent_results", []) or []
        evt_total = round(sum(float(r.get("cost_usd") or 0) for r in events), 4)
        ch_total = round(sum(float(c.get("last_cost_usd") or 0)
                             for c in (pl.get("channels", {}) or {}).values()), 4)
        real_total = max(evt_total, ch_total, float(cost.get("total_usd") or 0))
        # Per-phase breakdown from the event log.
        byphase: dict[str, float] = {}
        for r in events:
            c = float(r.get("cost_usd") or 0)
            if c:
                ph = r.get("phase") or "other"
                byphase[ph] = round(byphase.get(ph, 0) + c, 4)
        cost = {
            **cost,
            "today_usd": max(float(cost.get("today_usd") or 0), evt_total),
            "total_usd": real_total,
            "breakdown": cost.get("breakdown") or [
                {"category": k, "amount": v} for k, v in sorted(byphase.items(), key=lambda x: -x[1])
            ],
            "events_today": len(events),
        }
    except Exception:
        pass
    return cost


@app.get("/api/vault")
async def get_vault(status: str | None = None, market: str | None = None):
    """List vault niches with optional filters."""
    from omnicast.vault import db as vault_db
    from omnicast.vault.models import NicheStatus
    VAULT_DB = _ROOT / "output" / "vault.db"
    vault_db.init_db(VAULT_DB)
    status_enum = None
    if status:
        try:
            status_enum = NicheStatus(status.lower())
        except ValueError:
            pass
    records = vault_db.list_niches(status=status_enum, market=market, path=VAULT_DB)
    return {
        "niches": [
            {
                "niche_id": r.niche_id,
                "niche_name": r.niche_name,
                "market": r.market,
                "status": r.status.value,
                "original_score": r.original_score,
                "current_health": r.current_health,
                "saved_at": r.saved_at,
                "last_checked": r.last_checked,
                "category": r.niche_data.get("category") or r.niche_data.get("cat") or "",
                "estimated_rpm": r.niche_data.get("estimated_rpm") or r.niche_data.get("rpm") or 0,
                "health_notes": r.niche_data.get("_last_health_notes", []),
                "top_video": (r.niche_data.get("evidence") or [{}])[0] if r.niche_data.get("evidence") else {},
                # Detailed opportunity evidence keys merged from niche_data for front-end rendering:
                "why_opportunity": r.niche_data.get("why_opportunity") or r.niche_data.get("note") or "",
                "breakout_titles": r.niche_data.get("breakout_titles") or [],
                "example_channels": r.niche_data.get("example_channels") or [],
                "evidence": r.niche_data.get("evidence") or [],
            }
            for r in records
        ],
        "total": len(records),
        "hot_count": sum(1 for r in records if r.status.value == "hot"),
        "watching_count": sum(1 for r in records if r.status.value == "watching"),
        "stale_count": sum(1 for r in records if r.status.value == "stale"),
    }


@app.post("/api/vault/save-all")
async def vault_save_all(background_tasks: BackgroundTasks):
    """Save all niches from latest niche_results.json to vault."""
    cache_path = _ROOT / "output" / "niche_results.json"
    if not cache_path.exists():
        raise HTTPException(status_code=404, detail="No niche_results.json found. Run niche scan first.")
    background_tasks.add_task(_vault_save_all_task)
    return {"status": "started"}


@app.post("/api/vault/health-check")
async def vault_health_check(background_tasks: BackgroundTasks):
    """Run health check on all watching niches."""
    background_tasks.add_task(_vault_health_check_task)
    return {"status": "started"}


@app.post("/api/vault/archive/{niche_id}")
async def vault_archive(niche_id: str):
    """Archive a niche."""
    from omnicast.vault import db as vault_db
    from omnicast.vault.models import NicheStatus
    VAULT_DB = _ROOT / "output" / "vault.db"
    vault_db.init_db(VAULT_DB)
    record = vault_db.get_niche(niche_id, VAULT_DB)
    if not record:
        raise HTTPException(status_code=404, detail=f"Niche '{niche_id}' not found")
    vault_db.update_status(niche_id, NicheStatus.ARCHIVED, record.current_health, VAULT_DB)
    return {"status": "archived", "niche_id": niche_id}


@app.post("/api/vault/create-channel/{niche_id}")
async def vault_create_channel(niche_id: str):
    """Auto-generate a complete channel configuration from a vault niche."""
    from omnicast.vault import db as vault_db
    from omnicast.vault.models import NicheStatus
    from omnicast.agents.channel_name_debate import ChannelNameDebateAgent
    from omnicast.agents.channel_builder import ChannelBuilderAgent
    from omnicast.capabilities.llm_factory import create_llm
    from omnicast.config.settings import get_settings

    VAULT_DB = _ROOT / "output" / "vault.db"
    vault_db.init_db(VAULT_DB)
    record = vault_db.get_niche(niche_id, VAULT_DB)
    if not record:
        # Self-heal: the Vault page lists niches from the latest discovery results
        # (/api/niches), whose ids may not be saved to vault.db yet. Auto-save the
        # matching discovered niche so Auto-Create works directly from a card.
        record = _autosave_discovered_niche(niche_id, VAULT_DB)
    if not record:
        raise HTTPException(
            status_code=404,
            detail=f"Niche '{niche_id}' not found in Vault or latest discovery results",
        )

    # If a channel already covers this niche's theme, assign the niche to that
    # channel instead of spawning a duplicate (operator's anti-dilution rule).
    channels_dir = _ROOT / "channels"
    existing = _find_channel_for_niche(record, channels_dir)
    if existing:
        cfg, cfile = existing
        assigned = _assign_niche_to_channel(cfg, cfile, record)
        vault_db.update_status(niche_id, NicheStatus.ACTIVE, record.current_health, VAULT_DB)
        return {
            "status": "assigned",
            "channel_id": cfg.get("channel_id"),
            "channel_name": cfg.get("name"),
            "niche_id": niche_id,
            "niche_name": record.niche_name,
            "reason": f"Existing channel '{cfg.get('name')}' already covers this theme; "
                      "niche assigned to it instead of creating a new channel.",
            "niches": assigned,
        }

    settings = get_settings()
    
    # Run the 4-stage Name Debate Pipeline to ensure handle availability and audience trust
    flash_llm = create_llm(default_provider="deepseek", model=settings.deepseek_flash_model)
    chat_llm = create_llm(default_provider="deepseek", model=settings.deepseek_pro_model)
    
    name_debater = ChannelNameDebateAgent(flash_llm=flash_llm, chat_llm=chat_llm, yt_api_key=settings.youtube_api_key)
    debate_result = await name_debater.debate(record.niche_data)
    
    # Pass the debated winner to the Builder Pipeline
    agent = ChannelBuilderAgent(llm=chat_llm, youtube_api_key=settings.youtube_api_key)
    cfg_obj = await agent.build(
        niche=record.niche_data, 
        market=record.market,
        approved_name=debate_result.winner.name,
        approved_channel_id=debate_result.winner.channel_id
    )
    
    if not cfg_obj:
        raise HTTPException(status_code=500, detail="ChannelBuilderAgent failed to generate config")
        
    # Ensure channels dir exists
    channels_dir.mkdir(parents=True, exist_ok=True)
    channel_file = channels_dir / f"{cfg_obj.channel_id}.json"
    
    # If channel_id collision, append a number
    counter = 1
    while channel_file.exists():
        cfg_obj.channel_id = f"{cfg_obj.channel_id}_{counter}"
        channel_file = channels_dir / f"{cfg_obj.channel_id}.json"
        counter += 1
        
    with open(channel_file, "w", encoding="utf-8") as f:
        json.dump(cfg_obj.to_dict(), f, indent=2, ensure_ascii=False)
        
    return {
        "status": "created", 
        "channel": cfg_obj.to_dict(),
        "debate": {
            "winner": debate_result.winner.name,
            "runner_up": debate_result.runner_up.name if debate_result.runner_up else None,
            "reason": debate_result.selection_reason,
            "candidates": [
                {
                    "name": c.name,
                    "handle": c.handle,
                    "trust": c.audience_trust,
                    "seo": c.searchability,
                    "total_score": c.total_score,
                    "available": c.handle_available
                } for c in debate_result.all_candidates
            ]
        }
    }

@app.get("/api/infra")
async def get_infra():
    """Infrastructure health — DB + Redis pings + worker heartbeats from Redis.

    Auto-polled by the dashboard (5 s). Fail-soft: never raises; surfaces failures in
    the response body so the operator can see WHY a component is down, not just THAT.
    """
    svc = _get_data_service()

    # DB ping — run in thread to avoid blocking event loop
    db_ok, db_err = True, None
    if _data_service_init_error:
        db_ok, db_err = False, _data_service_init_error
    else:
        def _db_ping():
            try:
                eng = svc._get_engine()
                if eng is None:
                    return False, "engine init failed"
                from sqlalchemy import text
                with eng.connect() as c:
                    c.execute(text("SELECT 1"))
                return True, None
            except Exception as exc:
                return False, str(exc)[:200]
        db_ok, db_err = await asyncio.to_thread(_db_ping)

    # Redis ping — run in thread to avoid blocking event loop
    redis_ok, redis_err = True, None
    def _redis_ping():
        try:
            r = svc._get_redis()
            if r is None:
                return False, "redis init failed"
            r.ping()
            return True, None
        except Exception as exc:
            return False, str(exc)[:200]
    redis_ok, redis_err = await asyncio.to_thread(_redis_ping)

    # Workers (returns [] if Redis down — graceful) — run in thread
    workers = await asyncio.to_thread(svc.get_worker_statuses)
    worker_list = [
        {
            "worker_id":      w.worker_id,
            "hostname":       w.hostname,
            "cpu_percent":    w.cpu_percent,
            "ram_percent":    w.ram_percent,
            "gpu_temp":       w.gpu_temp,
            "last_heartbeat": w.last_heartbeat.isoformat() if w.last_heartbeat else None,
            "status":         w.status,
            "current_task":   w.current_task,
        }
        for w in workers
    ]

    healthy  = sum(1 for w in workers if w.status == "healthy")
    degraded = sum(1 for w in workers if w.status == "degraded")
    offline  = sum(1 for w in workers if w.status == "offline")

    return _envelope(
        payload={
            "db":      {"ok": db_ok,    "error": db_err},
            "redis":   {"ok": redis_ok, "error": redis_err},
            "workers": worker_list,
            "summary": {
                "total":    len(workers),
                "healthy":  healthy,
                "degraded": degraded,
                "offline":  offline,
            },
        },
        source="postgres+redis",
    )


@app.get("/api/system/state")
async def get_system_state():
    """Kill-switch state — SSOT is vault.db `system_state` table (SQLite, always
    available on this single-machine desktop app). Redis is reported for visibility
    only (fast-path cache), it is no longer required for the kill-switch to work.

    Polled by the topbar indicator (4 s).
    """
    svc = _get_data_service()

    redis_available = True
    try:
        r = svc._get_redis()
        if r is None:
            redis_available = False
        else:
            r.ping()
    except Exception:
        redis_available = False

    # Always read from vault.db (SSOT) regardless of Redis availability.
    paused = svc.is_pipeline_paused()
    since  = svc.get_pipeline_paused_since()

    return _envelope(
        payload={
            "paused":          paused,
            "paused_since":    since,
            "redis_available": redis_available,
        },
        source="vault+redis_cache",
    )


@app.post("/api/system/pause")
async def post_system_pause(body: dict = Body(default_factory=dict)):
    """Engage kill-switch. Durable write to vault.db `system_state` (SSOT);
    Redis mirror is best-effort only — does not block the kill-switch.

    Idempotent — calling on already-paused system is safe.
    Returns the new state so the client never has to re-query.
    """
    svc = _get_data_service()
    operator = (body or {}).get("operator", "dashboard")
    ok = svc.pause_pipeline(operator=operator)
    if not ok:
        raise HTTPException(status_code=503, detail="vault.db unavailable — cannot engage kill-switch")
    return _envelope(
        payload={
            "ok":           True,
            "paused":       True,
            "paused_since": svc.get_pipeline_paused_since(),
            "operator":     operator,
        },
        source="vault",
    )


@app.post("/api/system/resume")
async def post_system_resume(body: dict = Body(default_factory=dict)):
    """Disengage kill-switch (vault.db SSOT; Redis mirror best-effort)."""
    svc = _get_data_service()
    operator = (body or {}).get("operator", "dashboard")
    ok = svc.resume_pipeline(operator=operator)
    if not ok:
        raise HTTPException(status_code=503, detail="vault.db unavailable — cannot resume")
    return _envelope(
        payload={"ok": True, "paused": False, "operator": operator},
        source="vault",
    )


@app.get("/api/policy")
async def get_policy():
    """Policy control surface: pending rule changes (human-gated), active rules,
    the per-upload compliance checklist, and last-fetch metadata."""
    from omnicast.vault import db as vault_db
    from omnicast.upload.compliance import REQUIRED_CHECKS
    import json
    VDB = OUTPUT_DIR / "vault.db"
    vault_db.init_db(VDB)
    _CHECK_DESC = {
        "ai_disclosure": "Mô tả phải khai báo 'Made with AI' (YouTube bắt buộc)",
        "no_misleading_metadata": "Chặn scam/false-promise (get rich quick, miracle cure…)",
        "no_copyrighted_music": "Chỉ dùng nhạc royalty-free (Kevin MacLeod CC-BY)",
        "ftc_disclosure": "Có affiliate/promo → phải có disclosure (#ad/sponsored)",
        "advertiser_friendly": "Chặn từ gây demonetize (suicide, violence, drugs…)",
        "not_targeting_children": "COPPA — không nhắm trẻ em trừ khi khai báo",
        "cross_channel_unique": "Không trùng video đã đăng ở kênh khác (reused content)",
    }
    try:
        pending = vault_db.get_pending_rules(VDB)
    except Exception:
        pending = []
    try:
        active = vault_db.get_active_rules(VDB)
    except Exception:
        active = []
    try:
        scan_meta_str = vault_db.get_system_state("policy_last_scan", VDB)
        scan_meta = json.loads(scan_meta_str) if scan_meta_str else None
    except Exception:
        scan_meta = None
    return {
        "pending": pending,
        "active": active,
        "compliance_checks": [{"id": c, "desc": _CHECK_DESC.get(c, c)} for c in REQUIRED_CHECKS],
        "policy_running": any(j.get("channel_id") == "__policy__"
                              for j in read_pipeline_state().get("active_jobs", [])),
        "last_scan": scan_meta,
    }


async def _run_policy_check_task():
    set_active_job("__policy__", "policy_scan")
    try:
        from omnicast.compliance.policy_fetcher import run_policy_check
        from omnicast.capabilities.llm_factory import create_llm
        from omnicast.config.settings import get_settings
        s = get_settings()
        llm = create_llm(default_provider="deepseek", model=s.deepseek_flash_model)
        n = await run_policy_check(llm, OUTPUT_DIR / "vault.db")
        write_pipeline_event("__policy__", "policy_scan", "completed",
                             extra={"new_rules": n})
        import json
        from datetime import datetime, timezone
        from omnicast.vault.db import set_system_state
        scan_meta = {
            "last_scan_at": datetime.now(timezone.utc).isoformat(),
            "new_rules": n,
            "summary": f"Tìm thấy {n} rule mới chờ phê duyệt" if n > 0 else "Không tìm thấy thay đổi chính sách nào mới"
        }
        set_system_state("policy_last_scan", json.dumps(scan_meta), updated_by="system", path=OUTPUT_DIR / "vault.db")
    except Exception as exc:
        append_error(channel_id="__policy__", phase="policy_scan",
                     stage="fetch", message=str(exc), traceback_str=traceback.format_exc())
        write_pipeline_event("__policy__", "policy_scan", "failed", extra={"error": str(exc)[:200]})
    finally:
        clear_active_job("__policy__")


@app.post("/api/policy/fetch")
async def policy_fetch(background_tasks: BackgroundTasks):
    """Fetch latest YouTube policy pages, diff vs last snapshot, LLM-extract rule
    changes into pending_approval (human-gated). Background."""
    if any(j.get("channel_id") == "__policy__" for j in read_pipeline_state().get("active_jobs", [])):
        return JSONResponse({"status": "already_running"}, status_code=409)
    background_tasks.add_task(_run_policy_check_task)
    return {"status": "started"}


@app.post("/api/policy/rules/{rule_id}/{action}")
async def policy_rule_action(rule_id: int, action: str):
    """Approve (activate) or reject a pending policy rule change."""
    from omnicast.vault import db as vault_db
    from datetime import datetime, timezone
    VDB = OUTPUT_DIR / "vault.db"
    vault_db.init_db(VDB)
    if action == "approve":
        vault_db.approve_rule(rule_id, "operator",
                              datetime.now(timezone.utc).isoformat(), VDB)
        return {"status": "approved", "rule_id": rule_id}
    if action == "reject":
        vault_db.reject_rule(rule_id, VDB)
        return {"status": "rejected", "rule_id": rule_id}
    raise HTTPException(400, "action must be approve|reject")


@app.post("/api/discover-niches")
async def trigger_niche_discovery(background_tasks: BackgroundTasks):
    """Trigger niche discovery in background."""
    # Check if already running
    state = read_pipeline_state()
    active = state.get("active_jobs", [])
    if any(j.get("channel_id") == "__niche_discovery__" for j in active):
        return JSONResponse({"status": "already_running"}, status_code=409)

    background_tasks.add_task(_run_niche_discovery)
    return {"status": "started", "message": "Niche discovery running in background"}


@app.post("/api/run/{channel_id}")
async def trigger_channel_run(channel_id: str, background_tasks: BackgroundTasks):
    """Trigger phase-1 discovery for a channel."""
    # Verify channel exists
    channel_file = CHANNELS_DIR / f"{channel_id}.json"
    if not channel_file.exists():
        raise HTTPException(status_code=404, detail=f"Channel '{channel_id}' not found")

    # Check if already running
    state = read_pipeline_state()
    active = state.get("active_jobs", [])
    if any(j.get("channel_id") == channel_id for j in active):
        return JSONResponse({"status": "already_running"}, status_code=409)

    background_tasks.add_task(_run_channel_phase1, channel_id)
    return {"status": "started", "channel_id": channel_id}


@app.post("/api/run/{channel_id}/cancel")
async def cancel_channel_run(channel_id: str):
    """Force-clear any active job for a channel (kill-switch for stuck runs)."""
    state = read_pipeline_state()
    active = state.get("active_jobs", [])
    was_running = any(j.get("channel_id") == channel_id for j in active)
    if not was_running:
        return {"status": "not_running", "channel_id": channel_id}

    # Kill any active render subprocess if running
    try:
        from omnicast.api.render_routes import cancel_render
        killed = cancel_render(channel_id)
        if killed:
            logger.info("Killed active render subprocess on cancel", channel_id=channel_id)
    except Exception as exc:
        logger.warning("Failed to kill render subprocess on cancel", error=str(exc))

    clear_active_job(channel_id)
    write_pipeline_event(channel_id, "cancelled", "cancelled", extra={"reason": "operator_cancel"})
    append_live_log(channel_id, {"type": "cancelled", "msg": "⛔ Job cancelled by operator"})
    return {"status": "cancelled", "channel_id": channel_id}


@app.post("/api/run/{channel_id}/script")
async def trigger_channel_script(
    channel_id: str,
    background_tasks: BackgroundTasks,
    topic: str | None = None,
    payload: dict | None = Body(default=None),
):
    """Trigger phase-2 script generation. Optional ?topic= overrides auto-select.
    Optional JSON body {topic, desc, audience} from the Create-Video form lets the
    operator steer the script (topic, idea brief, target audience)."""
    channel_file = CHANNELS_DIR / f"{channel_id}.json"
    if not channel_file.exists():
        raise HTTPException(status_code=404, detail=f"Channel '{channel_id}' not found")

    state = read_pipeline_state()
    active = state.get("active_jobs", [])
    if any(j.get("channel_id") == channel_id for j in active):
        return JSONResponse({"status": "already_running"}, status_code=409)

    body = payload or {}
    eff_topic = topic or (str(body.get("topic")).strip() if body.get("topic") else None)
    overrides = {"desc": body.get("desc", ""), "audience": body.get("audience", "")}
    background_tasks.add_task(_run_channel_phase2, channel_id, eff_topic or None, overrides)
    return {"status": "started", "channel_id": channel_id, "phase": "script_generation", "topic": eff_topic}


@app.get("/api/discovery/{channel_id}")
async def get_discovery(channel_id: str):
    """Return Phase 1 discovery results (topic queues).

    First checks output/runs/{channel_id}/ for phase1_discovery.json files.
    Falls back to pipeline_state.json recent_results for newer runs that save
    topic_queue directly in pipeline events.
    """
    topics: list[dict] = []

    # --- Source 1: runs/ directory (old run_pipeline.py format) ---
    runs_dir = OUTPUT_DIR / "runs" / channel_id
    if runs_dir.exists():
        for run_dir in sorted(runs_dir.iterdir(), reverse=True):
            disc_file = run_dir / "phase1_discovery.json"
            if not disc_file.exists():
                continue
            try:
                d = json.loads(disc_file.read_text(encoding="utf-8"))
                queue = d.get("topic_queue") or []
                if not queue and d.get("topic"):
                    queue = [{"title": d["topic"], "score": d.get("best_score", 0),
                              "audience_segment": d.get("audience", ""),
                              "pain_point": d.get("pain_point", ""),
                              "content_angle": d.get("content_angle", "")}]
                topics.append({
                    "run_id": run_dir.name,
                    "saved_at": d.get("saved_at", ""),
                    "topic_queue": queue,
                    "best_score": d.get("best_score", 0),
                    "source": "runs_dir",
                })
            except Exception:
                pass

    # --- Source 2: pipeline_state.json recent_results (new API server format) ---
    if not topics:
        pipeline = read_pipeline_state()
        seen_ts: set[str] = set()
        for event in pipeline.get("recent_results", []):
            if (event.get("channel_id") == channel_id
                    and event.get("phase") == "discovery"
                    and event.get("status") == "completed"):
                ts = event.get("ts", "")
                if ts in seen_ts:
                    continue
                seen_ts.add(ts)
                queue = event.get("topic_queue") or []
                if not queue and event.get("topic"):
                    queue = [{"title": event["topic"], "score": event.get("score", 0),
                              "audience_segment": "", "pain_point": "", "content_angle": ""}]
                topics.append({
                    "run_id": ts,
                    "saved_at": ts,
                    "topic_queue": queue,
                    "best_score": event.get("score", 0),
                    "source": "pipeline_state",
                })

    return {"topics": topics, "channel_id": channel_id}


@app.get("/api/topics/{channel_id}")
async def list_topics(channel_id: str):
    """Persistent Topic Vault for a channel (queued/used/skipped). This is the
    durable store automation pulls from — survives pipeline-event churn."""
    from omnicast.vault import db as vault_db
    VAULT_DB = OUTPUT_DIR / "vault.db"
    vault_db.init_db(VAULT_DB)
    rows = vault_db.list_topics(channel_id=channel_id, path=VAULT_DB)
    return {
        "channel_id": channel_id,
        "counts": vault_db.count_topics(channel_id, VAULT_DB),
        "topics": [
            {"topic_id": t.topic_id, "title": t.title, "score": t.score,
             "status": t.status.value, "rank": t.rank,
             "audience_segment": t.audience_segment, "pain_point": t.pain_point,
             "content_angle": t.content_angle, "source_url": t.source_url,
             "discovered_at": t.discovered_at, "used_at": t.used_at,
             "used_video_id": t.used_video_id}
            for t in rows
        ],
    }


@app.post("/api/competitor-intel/{channel_id}")
async def learn_competitor_intel(channel_id: str):
    """Scan the channel's competitors and (re)learn title + thumbnail playbooks
    for its niche. Needs youtube_api_key + competitor_handles in the channel."""
    from omnicast.config.channel import ChannelProfileLoader
    from omnicast.analytics import competitor_intel
    if not (CHANNELS_DIR / f"{channel_id}.json").exists():
        raise HTTPException(404, f"Channel '{channel_id}' not found")
    channel = await ChannelProfileLoader(CHANNELS_DIR).load(channel_id)
    res = await competitor_intel.learn_for_channel(channel)
    if not res:
        raise HTTPException(
            422, "Nothing learned — check youtube_api_key + competitor_handles in the channel.")
    return res


@app.post("/api/music/harvest/{channel_id}")
async def harvest_competitor_music(channel_id: str, mood: str = "ambient",
                                   download: bool = True):
    """Find the FREE BGM competitors credit in their video descriptions and pull
    it from the ORIGINAL royalty-free source (legal). Auto-downloads known direct
    sources (Incompetech); lists the rest for manual add."""
    from omnicast.config.channel import ChannelProfileLoader
    from omnicast.config.settings import get_settings
    from omnicast.analytics import competitor_intel
    _impl_root = str(_ROOT)
    if _impl_root not in sys.path:
        sys.path.insert(0, _impl_root)
    import music_harvester
    settings = get_settings()
    if not settings.youtube_api_key:
        raise HTTPException(412, "youtube_api_key not configured.")
    if not (CHANNELS_DIR / f"{channel_id}.json").exists():
        raise HTTPException(404, f"Channel '{channel_id}' not found")
    channel = await ChannelProfileLoader(CHANNELS_DIR).load(channel_id)
    # Mining BGM credits out of descriptions makes no causal claim about why a
    # video did well, so the flat view-sorted pool is fine here (unlike the
    # playbook learner, which needs the winner/control cohort).
    vids = await competitor_intel._all_competitor_videos(channel, settings.youtube_api_key, top_n=20)
    vid_ids = [v.get("video_id") for v in vids if v.get("video_id")]
    credits = music_harvester.harvest(vid_ids, settings.youtube_api_key)
    saved = music_harvester.auto_fetch(credits, mood=mood) if download else []
    manual = [c for c in credits if not any("incompetech" in u for u in c.get("urls", []))]
    return {"channel_id": channel_id, "credits_found": len(credits),
            "downloaded": saved, "manual_sources": manual[:30]}


@app.get("/api/competitor-intel/{niche}")
async def get_competitor_intel(niche: str):
    """View the learned competitor playbooks (title + thumbnail) for a niche."""
    from omnicast.vault import db as vault_db
    VAULT_DB = OUTPUT_DIR / "vault.db"
    vault_db.init_db(VAULT_DB)
    ci = vault_db.get_competitor_intel(niche.lower(), VAULT_DB)
    if not ci:
        return {"niche": niche, "learned": False}
    try:
        cohort_meta = json.loads(ci.cohort_meta) if ci.cohort_meta else {}
    except Exception:
        cohort_meta = {}
    return {"niche": ci.niche, "learned": True, "title_playbook": ci.title_playbook,
            "thumbnail_playbook": ci.thumbnail_playbook, "sample_titles": ci.sample_titles,
            "sample_count": ci.sample_count,
            # Surfaced, not buried: a caller must be able to see whether these
            # playbooks were learned against a control group.
            "is_comparable": cohort_meta.get("is_comparable"),
            "comparability": cohort_meta.get("comparability"),
            "control_coverage": cohort_meta.get("control_coverage"),
            # §4.5 — the unified dossier is the artifact a human should read:
            # every field labelled measured/inferred/assumed/missing, and every
            # recommendation traceable to the field it rests on.
            "dossier": cohort_meta.get("dossier"),
            "production_blueprint": cohort_meta.get("production_blueprint"),
            "schedule": cohort_meta.get("schedule"),
            "audience_signals": cohort_meta.get("audience_signals"),
            "cohort": cohort_meta, "updated_at": ci.updated_at}


@app.get("/api/dedup/check")
async def dedup_check(channel_id: str, title: str):
    """Has this topic already been produced/published in the system? Returns
    duplicate flag + severity (block/warn/ok) + matching videos."""
    return _check_topic_duplication(channel_id, title)


@app.post("/api/topics/{channel_id}/{topic_id}/{action}")
async def topic_action(channel_id: str, topic_id: str, action: str,
                       background_tasks: BackgroundTasks, force: bool = False):
    """Operate on a vault topic: skip | requeue | script.
    - skip/requeue: flip status.
    - script: mark used + trigger Phase-2 script generation for its title."""
    from omnicast.vault import db as vault_db
    from omnicast.vault.models import TopicStatus
    from datetime import datetime, timezone
    VAULT_DB = OUTPUT_DIR / "vault.db"
    vault_db.init_db(VAULT_DB)
    rows = {t.topic_id: t for t in vault_db.list_topics(channel_id=channel_id, path=VAULT_DB)}
    topic = rows.get(topic_id)
    if not topic:
        raise HTTPException(404, f"Topic '{topic_id}' not found for {channel_id}")

    if action == "skip":
        vault_db.set_topic_status(topic_id, TopicStatus.SKIPPED, VAULT_DB)
        return {"status": "skipped", "topic_id": topic_id}
    if action == "requeue":
        vault_db.set_topic_status(topic_id, TopicStatus.QUEUED, VAULT_DB)
        return {"status": "queued", "topic_id": topic_id}
    if action == "script":
        if not (CHANNELS_DIR / f"{channel_id}.json").exists():
            raise HTTPException(404, f"Channel '{channel_id}' not found")
        state = read_pipeline_state()
        if any(j.get("channel_id") == channel_id for j in state.get("active_jobs", [])):
            return JSONResponse({"status": "already_running"}, status_code=409)
        # Content-duplication guard: block a literal reupload, warn on cross-channel
        # reuse. `force=true` overrides the warning (operator's call).
        dup = _check_topic_duplication(channel_id, topic.title)
        if dup["severity"] == "block" and not force:
            return JSONResponse(
                {"status": "duplicate_blocked", "dedup": dup,
                 "message": "Topic này đã đăng trên chính kênh này. Chặn để tránh reused content."},
                status_code=409)
        if dup["severity"] == "warn" and not force:
            return JSONResponse(
                {"status": "duplicate_warning", "dedup": dup,
                 "message": "Topic tương tự đã dùng ở kênh khác (rủi ro reused content). "
                            "Gửi lại với force=true để vẫn tạo."},
                status_code=409)
        vault_db.mark_topic_used(topic_id, datetime.now(timezone.utc).isoformat(), None, VAULT_DB)
        background_tasks.add_task(_run_channel_phase2, channel_id, topic.title)
        return {"status": "started", "phase": "script_generation",
                "channel_id": channel_id, "topic": topic.title}
    raise HTTPException(400, f"Unknown action '{action}' (skip|requeue|script)")


# ─── Auto-Pilot: end-to-end automation (P5) ──────────────────────────────────
# One cycle per channel: ensure topics (discover) → pick next → script → render
# → (QA in render) → optional upload. Channel CREATION stays manual by design.

_auto_state: dict = {"running": False, "channel": None, "step": "idle",
                     "log": [], "started": None, "cycles": []}


def _auto_log(msg: str) -> None:
    import time as _t
    _auto_state["log"].append(f"[{_t.strftime('%H:%M:%S')}] {msg}")
    _auto_state["log"] = _auto_state["log"][-100:]


async def _auto_cycle_task(channel_ids: list[str], do_upload: bool, beat_words: int,
                           shorts: bool = False):
    """Run one full content cycle for each channel sequentially."""
    import asyncio as _aio
    from datetime import datetime, timezone
    from omnicast.vault import db as vault_db
    VAULT_DB = OUTPUT_DIR / "vault.db"
    _auto_state.update({"running": True, "started": datetime.now(timezone.utc).isoformat(),
                        "cycles": [], "log": []})
    try:
        for cid in channel_ids:
            cyc = {"channel": cid, "steps": {}, "topic": None, "video": None, "upload": None}
            _auto_state.update({"channel": cid, "step": "discovery"})
            try:
                vault_db.init_db(VAULT_DB)
                # 1) Ensure a queued topic exists; discover if the queue is empty.
                nx = vault_db.get_next_topic(cid, VAULT_DB)
                if not nx:
                    _auto_log(f"{cid}: no queued topic → Phase 1 discovery")
                    await _run_channel_phase1(cid)
                    nx = vault_db.get_next_topic(cid, VAULT_DB)
                cyc["steps"]["discovery"] = "done"
                if not nx:
                    cyc["steps"]["topic"] = "none"
                    _auto_log(f"{cid}: still no topic after discovery — skip")
                    _auto_state["cycles"].append(cyc); continue
                cyc["topic"] = nx.title

                # 1b) Dedup guard — never auto-produce a topic already published
                # (same channel) or near-duplicate published elsewhere.
                dup = _check_topic_duplication(cid, nx.title)
                if dup["severity"] == "block":
                    vault_db.set_topic_status(nx.topic_id,
                                              __import__("omnicast.vault.models", fromlist=["TopicStatus"]).TopicStatus.SKIPPED, VAULT_DB)
                    cyc["steps"]["dedup"] = "blocked_skipped"
                    _auto_log(f"{cid}: topic duplicate (block) → skipped '{nx.title[:40]}'")
                    _auto_state["cycles"].append(cyc); continue
                if dup["severity"] == "warn":
                    cyc["steps"]["dedup"] = "warn_crosschannel"
                    _auto_log(f"{cid}: ⚠ cross-channel similar topic — proceeding")

                # 2) Script (Phase 2). Marks the topic used on completion.
                _auto_state["step"] = "script"
                _auto_log(f"{cid}: scripting '{nx.title[:50]}'")
                script_result = await _run_channel_phase2(cid, nx.title)
                cyc["steps"]["script"] = "done"

                # 3) Render (subprocess) — wait for completion.
                _auto_state["step"] = "render"
                from omnicast.api import render_routes as rr
                script_path = Path(str((script_result or {}).get("script_path") or ""))
                if not script_path.exists():
                    script_path = None
                if not script_path:
                    cyc["steps"]["render"] = "no_script"; _auto_state["cycles"].append(cyc); continue
                # Policy gate — skip render of a non-compliant script (don't waste Flow).
                _pv = rr._script_compliance(script_path)
                if _pv:
                    cyc["steps"]["render"] = "policy_blocked"; cyc["policy"] = _pv
                    _auto_log(f"{cid}: script vi phạm policy → skip render ({'; '.join(_pv)})")
                    _auto_state["cycles"].append(cyc); continue
                # Versioned per-channel output (no overwrite; per-channel status).
                import time as _t
                _slug = script_path.parent.name if script_path.parent.name != cid else script_path.stem
                _chdir = rr.OUT_DIR / cid
                _chdir.mkdir(parents=True, exist_ok=True)
                _sfx = "_shorts" if shorts else ""
                out_mp4 = _chdir / f"{_slug[:50]}_{_t.strftime('%Y%m%d_%H%M%S')}{_sfx}.mp4"
                cmd = [sys.executable, "-X", "utf8", str(rr.RENDER_SCRIPT),
                       "--script", str(script_path), "--channel", cid,
                       "--images", "flow", "--beat-words", str(beat_words),
                       "--subtitles",  # clean word-synced captions, no title card
                       "--out", str(out_mp4)]
                if shorts:
                    cmd.append("--shorts")
                env = dict(os.environ); env.setdefault("FLOW_NEW_PROJECT", "1")
                _auto_log(f"{cid}: rendering → {out_mp4.name}")
                proc = subprocess.Popen(cmd, cwd=str(rr.IMPL_ROOT), env=env,
                                        creationflags=rr._NO_WINDOW)
                rr._proc[cid] = proc
                set_active_job(cid, "render")  # show in dashboard while rendering
                rc = await _aio.to_thread(proc.wait)
                clear_active_job(cid)
                rr._proc.pop(cid, None)
                cyc["steps"]["render"] = "done" if rc == 0 else f"exit_{rc}"
                if rc != 0 or not out_mp4.exists():
                    _auto_log(f"{cid}: render failed (rc={rc})")
                    _auto_state["cycles"].append(cyc); continue
                cyc["video"] = out_mp4.name

                # 4) Upload (optional, gated on authorization).
                if do_upload:
                    _auto_state["step"] = "upload"
                    try:
                        mgr = rr._yt_oauth()
                        if mgr.has_token(cid):
                            res = await rr.upload_video(cid, video=None, privacy="private")
                            cyc["upload"] = res.get("status"); cyc["steps"]["upload"] = "done"
                            _auto_log(f"{cid}: uploaded ({res.get('url')})")
                        else:
                            cyc["steps"]["upload"] = "not_authorized"
                            _auto_log(f"{cid}: upload skipped — not authorized")
                    except Exception as ue:
                        cyc["steps"]["upload"] = "failed"; _auto_log(f"{cid}: upload error {ue}")
            except Exception as exc:
                cyc["steps"]["error"] = str(exc)[:160]
                _auto_log(f"{cid}: ERROR {exc}")
            _auto_state["cycles"].append(cyc)
    finally:
        _auto_state.update({"running": False, "step": "idle", "channel": None})
        _auto_log("auto-pilot finished")


@app.post("/api/auto/run")
async def auto_run(background_tasks: BackgroundTasks, channel_id: str | None = None,
                   upload: bool = False, beat_words: int = 35):
    """Start the auto-pilot for one channel (channel_id) or ALL channels.
    Runs discover→topic→script→render→(QA)→optional upload per channel.
    Channel creation is NOT automated (manual by design)."""
    if _auto_state["running"]:
        raise HTTPException(409, "Auto-pilot already running")
    if channel_id:
        if not (CHANNELS_DIR / f"{channel_id}.json").exists():
            raise HTTPException(404, f"Channel '{channel_id}' not found")
        targets = [channel_id]
    else:
        targets = [c.get("channel_id") for c in _all_channels() if c.get("channel_id")]
    if not targets:
        raise HTTPException(400, "No channels to run")
    background_tasks.add_task(_auto_cycle_task, targets, upload, beat_words)
    return {"status": "started", "channels": targets, "upload": upload}


@app.get("/api/auto/status")
async def auto_status():
    """Live auto-pilot state (running flag, current channel/step, per-cycle log)."""
    return _auto_state


@app.get("/api/scripts/{channel_id}")
async def list_scripts(channel_id: str):
    """List all saved script variants for a channel, including per-scene data and debate rounds.

    Handles two layouts:
      - New: output/scripts/{channel_id}/{topic_slug}/variant_*.json
      - Old: output/scripts/{channel_id}/variant_*.json  (flat, no topic subdir)
    """
    scripts_dir = OUTPUT_DIR / "scripts" / channel_id

    def _load_from_dir(scan_dir: Path, topic_slug: str) -> list[dict]:
        """Load all variant JSON files from a single directory."""
        results = []
        # Debate log: latest debate_*.json in same dir
        debate_rounds: list[dict] = []
        debate_files = sorted(scan_dir.glob("debate_*.json"), reverse=True)
        if debate_files:
            try:
                dl = json.loads(debate_files[0].read_text(encoding="utf-8"))
                debate_rounds = dl.get("rounds", [])
            except Exception:
                pass

        for f in sorted(scan_dir.glob("variant_*.json"), reverse=True):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                variant_id = data.get("variant_id", f.stem)
                variant_rounds = [r for r in debate_rounds if r.get("variant_id") == variant_id]
                results.append({
                    "file": f.name,
                    "topic_slug": topic_slug,
                    "topic": data.get("topic", topic_slug),
                    "variant_id": variant_id,
                    "score": data.get("score"),
                    "approved": data.get("approved"),
                    "hook": data.get("hook", ""),
                    "outro": data.get("outro", ""),
                    "scenes": data.get("scenes", []),
                    "debate_rounds": variant_rounds,
                    "channel_id": channel_id,
                    "saved_at": f.stat().st_mtime,
                })
            except Exception:
                pass
        return results

    scripts = []

    # New products tree: products/{channel}/{run}/variants/variant_*.json
    try:
        from omnicast.storage import products as _products
        for pd in _products.iter_products(channel_id):
            vdir = _products.variants_dir(pd)
            if vdir.exists():
                scripts.extend(_load_from_dir(vdir, pd.name))
    except Exception:
        pass

    # Legacy flat layout: variant_*.json directly in scripts_dir
    scripts.extend(_load_from_dir(scripts_dir, channel_id))

    # Legacy subdir layout: topic_slug/ folders
    if scripts_dir.exists():
        for topic_dir in sorted(scripts_dir.iterdir(), reverse=True):
            if topic_dir.is_dir():
                scripts.extend(_load_from_dir(topic_dir, topic_dir.name))

    # Sort newest first by mtime
    scripts.sort(key=lambda s: s["saved_at"], reverse=True)
    return {"scripts": scripts, "channel_id": channel_id}


@app.get("/api/run/{channel_id}/log")
async def get_live_log(channel_id: str):
    """Live agent event log for an active (or recently completed) run."""
    return {"events": read_live_log(channel_id), "channel_id": channel_id}


@app.post("/api/run/{channel_id}/images")
async def trigger_channel_images(
    channel_id: str,
    background_tasks: BackgroundTasks,
    script_json: str | None = None,
    max_scenes: int = 0,
    backend: str = "browser",  # "browser" (Gemini Pro web) | "api" (Imagen 4 API)
):
    """Trigger phase-3 image generation for a channel.

    backend=browser  → CloakBrowser + Gemini Pro web (free, uses Pro subscription)
    backend=api      → Imagen 4 via Gemini API ($0.03/image, needs GOOGLE_API_KEY)

    Optionally pass ?script_json=<absolute_path> to target a specific file.
    Pass ?max_scenes=N to cap scenes (0 = all).
    """
    channel_file = CHANNELS_DIR / f"{channel_id}.json"
    if not channel_file.exists():
        raise HTTPException(status_code=404, detail=f"Channel '{channel_id}' not found")

    settings = _get_app_settings()

    if backend == "api" and not settings.google_api_key:
        raise HTTPException(
            status_code=400,
            detail="GOOGLE_API_KEY not configured. Add to .env or use backend=browser.",
        )

    if backend == "browser":
        from omnicast.media.browser_imagen import PROFILE_DIR
        if not PROFILE_DIR.exists():
            raise HTTPException(
                status_code=400,
                detail=(
                    "Browser profile not found. Run setup first:\n"
                    "python -c \"import asyncio; from omnicast.media.browser_imagen "
                    "import setup_profile; asyncio.run(setup_profile())\""
                ),
            )

    state = read_pipeline_state()
    active = state.get("active_jobs", [])
    if any(j.get("channel_id") == channel_id and j.get("phase") == "image_generation"
           for j in active):
        return JSONResponse({"status": "already_running"}, status_code=409)

    # Resolve script JSON path if not provided
    if not script_json:
        # Preferred: newest product's chosen-variant JSON (products/.../variants/).
        try:
            from omnicast.storage import products as _products
            for pd in _products.iter_products(channel_id):
                meta = _products.read_meta(pd)
                bv = meta.get("best_variant")
                vdir = _products.variants_dir(pd)
                jsons = (sorted(vdir.glob(f"variant_{bv}_*.json"), reverse=True) if bv else []) \
                    or sorted(vdir.glob("variant_*.json"), reverse=True)
                if jsons:
                    script_json = str(jsons[0])
                    break
        except Exception:
            pass
    if not script_json:
        for event in reversed(state.get("recent_results", [])):
            if (event.get("channel_id") == channel_id
                    and event.get("phase") == "script_generation"
                    and event.get("status") == "completed"):
                topic = event.get("topic", "")
                if topic:
                    import re as _re
                    slug = _re.sub(r"[^\w]+", "_", topic.lower()).strip("_")[:50]
                    folder = OUTPUT_DIR / "scripts" / channel_id / slug
                    if folder.exists():
                        jsons = sorted(folder.glob("*.json"), reverse=True)
                        if jsons:
                            script_json = str(jsons[0])
                break

    if not script_json:
        raise HTTPException(
            status_code=404,
            detail="No script JSON found. Run phase-2 (script generation) first.",
        )

    background_tasks.add_task(
        _run_channel_phase3,
        channel_id,
        script_json,
        max_scenes or None,
        backend,
    )
    return {
        "status": "started",
        "channel_id": channel_id,
        "phase": "image_generation",
        "backend": backend,
        "script_json": script_json,
    }


# ─── Background Tasks ────────────────────────────────────────────────────────

def _current_stage(channel_id: str) -> str:
    """Best-effort lookup: which stage was the job in when it crashed?

    Used to annotate error-log entries so the operator can see "failed at
    Clustering with Claude Haiku" rather than just "failed".
    """
    try:
        st = read_pipeline_state()
        for job in st.get("active_jobs", []):
            if job.get("channel_id") == channel_id:
                return job.get("stage") or job.get("phase") or ""
    except Exception:
        pass
    return ""


async def _run_niche_discovery():
    """Run niche discovery and save results."""
    set_active_job("__niche_discovery__", "niche_scan")
    write_pipeline_event("__niche_discovery__", "niche_scan", "started")
    clear_live_log("__niche_discovery__")  # fresh feed for this scan's realtime events

    # Bridge granular scanner/discoverer sub-steps → live_log so the office can
    # narrate, in realtime, exactly what each agent is doing (per query searched,
    # per channel sampled, per niche scored). Mirror the key fields into the
    # active-job stage/detail/pct so the right-panel progress stays in sync.
    _NICHE_PCT = {"niche_search": 15, "niche_stats": 35, "niche_filter": 45,
                  "niche_sample": 55, "niche_cluster": 70, "niche_scored": 85}

    def _niche_event(e: dict) -> None:
        append_live_log("__niche_discovery__", e)
        t = e.get("type", "")
        pct = _NICHE_PCT.get(t)
        if t == "niche_sample" and e.get("total"):
            # ramp 55→68 across sampling, with real measured ETA
            pct = 55 + int(13 * e.get("done", 0) / max(1, e.get("total", 1)))
        if pct is not None:
            eta = e.get("eta_s")
            detail = {
                "niche_search": f"Quét query {e.get('q_idx')}/{e.get('q_total')} · {e.get('total_channels',0)} kênh",
                "niche_stats": f"Lấy thống kê {e.get('fetched',0)} kênh",
                "niche_filter": f"Lọc còn {e.get('candidates',0)} kênh tiềm năng",
                "niche_sample": f"Phân tích kênh {e.get('done',0)}/{e.get('total',0)}" + (f" · còn ~{eta}s" if eta else ""),
                "niche_cluster": f"Gom nhóm {e.get('channels',0)} kênh → tìm ngách",
                "niche_scored": f"Đã chấm {e.get('n',0)} ngách",
            }.get(t, "")
            set_active_job_progress("__niche_discovery__", stage=t, pct=pct, detail=detail)

    set_active_job_progress(
        "__niche_discovery__",
        stage="Loading seed queries",
        pct=5,
        detail="Đọc bộ truy vấn T0–T5",
    )
    try:
        from omnicast.config.settings import get_settings
        from omnicast.capabilities.llm_factory import create_llm
        from omnicast.discovery.niche_scanner import NicheScanner
        from omnicast.agents.niche_discoverer import NicheDiscovererAgent

        from omnicast.discovery.key_rotator import YouTubeKeyRotator

        settings = get_settings()
        scanner = NicheScanner(rotator=YouTubeKeyRotator(settings.youtube_key_pool))

        set_active_job_progress(
            "__niche_discovery__",
            stage="Searching YouTube",
            pct=15,
            detail="Bắt đầu quét YouTube theo seed queries",
        )
        channels = await scanner.scan(progress_cb=_niche_event)

        set_active_job_progress(
            "__niche_discovery__",
            stage="Clustering with DeepSeek",
            pct=65,
            detail=f"{len(channels)} kênh → LLM gom nhóm & chấm điểm",
        )
        llm       = create_llm(default_provider="deepseek", model=settings.deepseek_chat_model)
        flash_llm = create_llm(default_provider="deepseek", model=settings.deepseek_flash_model)
        agent = NicheDiscovererAgent(llm=llm, flash_llm=flash_llm)
        niches = await agent.discover(channels, top_n=15, progress_cb=_niche_event)

        set_active_job_progress(
            "__niche_discovery__",
            stage="Saving results",
            pct=90,
            detail=f"Lưu {len(niches)} ngách vào kho",
        )

        from omnicast.agents.channel_builder import _detect_market as _dm
        niche_dicts = []
        for n in niches:
            _market = _dm({"niche_name": n.niche_name, "niche_id": n.niche_id,
                           "audience_description": n.audience_description,
                           "why_opportunity": n.why_opportunity}, fallback="US")
            niche_dicts.append({
                "niche_id": n.niche_id,
                "niche_name": n.niche_name,
                "category": n.category,
                "market": _market,
                "audience_description": n.audience_description,
                "pain_points": n.pain_points,
                "content_triggers": n.content_triggers,
                "demand_score": n.demand_score,
                "gap_score": n.gap_score,
                "rpm_score": n.rpm_score,
                "specificity_score": n.specificity_score,
                "total_score": n.total_score,
                "estimated_rpm": n.estimated_rpm,
                "example_channels": n.example_channels,
                "breakout_titles": n.breakout_titles,
                "why_opportunity": n.why_opportunity,
                # Per-channel competitor evidence (name, subs, outlier, views,
                # videos, monetized/faceless flags) — drives the niche card's
                # "kênh nào làm ngách này" detail.
                "evidence": getattr(n, "evidence", []) or [],
            })

        niche_dicts = _dedupe_niches_vs_vault(niche_dicts)

        # Momentum cross-scan (N2): so với snapshot trước khi ghi đè — niche lặp
        # lại với điểm tăng = đang tăng tốc. Fail-safe: lỗi không làm gãy scan.
        try:
            import re as _re
            _prev_path = _ROOT / "output" / "niche_results.json"
            _prev = {}
            if _prev_path.exists():
                _old = json.loads(_prev_path.read_text(encoding="utf-8"))
                for _n in (_old.get("niches") or []):
                    _t = frozenset(_re.findall(r"[a-z0-9]+", str(_n.get("niche_name") or "").lower()))
                    if _t:
                        _prev[_t] = float(_n.get("total_score") or 0)
            for _n in niche_dicts:
                _t = set(_re.findall(r"[a-z0-9]+", str(_n.get("niche_name") or "").lower()))
                _m = None
                for _pt, _ps in _prev.items():
                    if len(_t & _pt) / max(1, len(_t | _pt)) >= 0.5:
                        _m = _ps; break
                if _m is None:
                    _n["momentum"] = "new"
                else:
                    _d = round(float(_n.get("total_score") or 0) - _m, 1)
                    _n["momentum"] = "rising" if _d > 0 else "cooling" if _d < 0 else "flat"
                    _n["momentum_delta"] = _d
        except Exception:
            pass

        write_niche_results(niche_dicts, len(channels))

        # Auto-save every discovered niche to the vault (upsert, dedup by id) so
        # the vault ACCUMULATES across scans — niche_results.json only holds the
        # latest scan, but the vault keeps every unique niche ever found. Skip
        # same-theme duplicates already merged into an existing vault niche.
        try:
            from omnicast.vault import db as vault_db
            from omnicast.vault.models import NicheRecord, NicheStatus
            from omnicast.agents.channel_builder import _detect_market
            from datetime import datetime, timezone
            VDB = OUTPUT_DIR / "vault.db"
            vault_db.init_db(VDB)
            now_iso = datetime.now(timezone.utc).isoformat()
            saved = 0
            skipped_dup = 0
            for niche in niche_dicts:
                nid = niche.get("niche_id")
                # Honor the anti-dilution filter: _dedupe_niches_vs_vault already
                # flagged same-theme near-duplicates (an equivalent niche exists in
                # the vault or earlier in this batch). Saving them anyway is exactly
                # what diluted the vault with near-identical niches — so skip them.
                if niche.get("_merged"):
                    skipped_dup += 1
                    continue
                if not nid or vault_db.get_niche(nid, VDB):
                    continue  # already in vault (exact-id dedup)
                score = niche.get("total_score", niche.get("current_health", 0))
                vault_db.upsert_niche(NicheRecord(
                    niche_id=nid, niche_name=niche.get("niche_name", nid),
                    market=_detect_market(niche, fallback="US"),
                    status=NicheStatus.WATCHING, original_score=score,
                    current_health=score, saved_at=now_iso, last_checked=None,
                    evidence_channel_ids=niche.get("example_channels", []),
                    seed_queries=[], niche_data=niche,
                ), VDB)
                saved += 1
            logger.info("Auto-saved niches to vault", new=saved,
                        scanned=len(niche_dicts), skipped_duplicates=skipped_dup)
            # Write success event to pipeline logs so it shows up in "Hoạt động gần đây"
            write_pipeline_event(
                "__niche_discovery__", "niche_scan", "completed",
                extra={"scanned_niches": len(niche_dicts), "new_niches": saved,
                       "skipped_duplicates": skipped_dup}
            )
        except Exception as _vexc:
            logger.warning("Vault auto-save failed", error=str(_vexc))

    except Exception as exc:
        tb = traceback.format_exc()
        # 1) full traceback into the error-log surface (operator can inspect from dashboard)
        append_error(
            channel_id="__niche_discovery__",
            phase="niche_scan",
            stage=_current_stage("__niche_discovery__"),
            message=str(exc),
            traceback_str=tb,
        )
        # 2) recent-results entry so the failure is also visible in the activity feed
        write_pipeline_event(
            "__niche_discovery__", "niche_scan", "failed",
            extra={"error": str(exc)[:200]},
        )
    finally:
        clear_active_job("__niche_discovery__")


def _check_topic_duplication(channel_id: str, title: str) -> dict:
    """Guard against re-using a topic already produced/published in the system —
    YouTube flags substantially similar content ('reused content'), especially
    across channels. Scans the published-video ledger + used topics across ALL
    channels by theme-token similarity.

    Returns {duplicate, severity, matches}. severity:
      block — same channel exact/near-duplicate already published (literal reupload)
      warn  — cross-channel near-duplicate published/used (reused-content risk)
      ok    — clear
    """
    from omnicast.vault import db as vault_db
    VAULT_DB = OUTPUT_DIR / "vault.db"
    vault_db.init_db(VAULT_DB)
    norm = " ".join((title or "").lower().split())
    nt = _theme_tokens(title)
    matches: list[dict] = []

    def sim(other: str) -> float:
        ot = _theme_tokens(other)
        if not nt or not ot:
            return 0.0
        return len(nt & ot) / min(len(nt), len(ot))

    # 1) Published ledger (real reused-content risk).
    for pv in vault_db.list_published(path=VAULT_DB):
        s = 1.0 if " ".join(pv.title.lower().split()) == norm else sim(pv.title)
        if s >= 0.7:
            matches.append({
                "scope": "same_channel" if pv.channel_id == channel_id else "cross_channel",
                "channel_id": pv.channel_id, "title": pv.title,
                "youtube_video_id": pv.youtube_video_id, "status": pv.status,
                "similarity": round(s, 2), "source": "published",
            })
    # 2) Used topics (already scripted/rendered — avoid wasting effort + dup).
    for t in vault_db.list_topics(status=None, path=VAULT_DB):
        if t.status.value != "used":
            continue
        s = 1.0 if " ".join(t.title.lower().split()) == norm else sim(t.title)
        if s >= 0.7:
            matches.append({
                "scope": "same_channel" if t.channel_id == channel_id else "cross_channel",
                "channel_id": t.channel_id, "title": t.title,
                "youtube_video_id": t.used_video_id or "", "status": "topic_used",
                "similarity": round(s, 2), "source": "topic",
            })

    severity = "ok"
    if any(m["scope"] == "same_channel" and m["source"] == "published" for m in matches):
        severity = "block"
    elif matches:
        severity = "warn"
    return {"duplicate": bool(matches), "severity": severity,
            "title": title, "channel_id": channel_id,
            "matches": sorted(matches, key=lambda m: -m["similarity"])[:10]}


def _dedupe_niches_vs_vault(niche_dicts: list[dict]) -> list[dict]:
    """Annotate discovered niches that duplicate an existing vault niche's theme
    (anti-dilution). Same-theme duplicates get `_duplicate_of` + `_merged` flags so
    the UI can fold them into the existing niche instead of listing near-identical
    niches. Also dedupes within the discovered batch itself."""
    try:
        from omnicast.vault import db as vault_db
        VAULT_DB = OUTPUT_DIR / "vault.db"
        vault_db.init_db(VAULT_DB)
        vault_niches = vault_db.list_niches(path=VAULT_DB)
    except Exception:
        vault_niches = []

    def toks(n_name: str, cat: str, aud: str) -> set[str]:
        return _theme_tokens(n_name) | _theme_tokens(aud)

    vault_themes = [
        (v.niche_id, (v.niche_data.get("category") or "").lower(),
         toks(v.niche_name, v.niche_data.get("category", ""),
              v.niche_data.get("audience_description", "")))
        for v in vault_niches
    ]
    seen_themes: list[tuple[str, set[str]]] = []  # (niche_id, tokens) in this batch
    out: list[dict] = []
    for n in niche_dicts:
        cat = (n.get("category") or "").lower()
        nt = toks(n.get("niche_name", ""), n.get("category", ""),
                  n.get("audience_description", ""))
        dup_of = None
        # vs vault
        for vid, vcat, vt in vault_themes:
            if cat and vcat and cat != vcat:
                continue
            if nt and vt and len(nt & vt) / min(len(nt), len(vt)) >= 0.6:
                dup_of = vid
                break
        # vs earlier in this batch
        if not dup_of:
            for sid, st in seen_themes:
                if nt and st and len(nt & st) / min(len(nt), len(st)) >= 0.6:
                    dup_of = sid
                    break
        if dup_of:
            n = {**n, "_duplicate_of": dup_of, "_merged": True}
        seen_themes.append((n.get("niche_id", ""), nt))
        out.append(n)
    return out


def _theme_tokens(text: str) -> set[str]:
    """Significant lowercase tokens for theme overlap (drops stopwords/short)."""
    stop = {"the", "and", "for", "with", "your", "you", "how", "what", "why",
            "best", "top", "us", "uk", "guide", "tips", "to", "of", "in", "on",
            "a", "an", "&", "channel", "that", "this", "these", "those", "will",
            "are", "was", "from", "can", "get", "make", "now", "new", "about"}
    toks = {t for t in __import__("re").sub(r"[^a-z0-9 ]", " ", (text or "").lower()).split()
            if len(t) >= 3 and t not in stop}
    return toks


def _find_channel_for_niche(record, channels_dir):
    """Find an existing channel that already covers this niche's theme.
    Returns (cfg_dict, file_path) or None. Match = same broad niche/category
    AND the niche already assigned OR strong title/sub_niche token overlap."""
    if not channels_dir.exists():
        return None
    category = (record.niche_data.get("category") or "").lower()
    niche_toks = _theme_tokens(record.niche_name) | _theme_tokens(
        record.niche_data.get("audience_description", ""))
    best = None
    best_overlap = 0.0
    for file in sorted(channels_dir.glob("*.json")):
        try:
            cfg = json.loads(file.read_text(encoding="utf-8"))
        except Exception:
            continue
        # Already assigned this exact niche → idempotent match.
        if any(n.get("niche_id") == record.niche_id for n in cfg.get("niches", [])):
            return cfg, file
        ch_cat = (cfg.get("niche") or "").lower()
        if category and ch_cat and category != ch_cat:
            continue  # different broad niche → never merge
        ch_toks = _theme_tokens(cfg.get("name", "")) | _theme_tokens(cfg.get("sub_niche", ""))
        if not niche_toks or not ch_toks:
            continue
        # Coverage of the smaller token set — how much the two themes overlap.
        overlap = len(niche_toks & ch_toks) / min(len(niche_toks), len(ch_toks))
        if overlap >= 0.5 and overlap > best_overlap:
            best, best_overlap = (cfg, file), overlap
    return best


def _assign_niche_to_channel(cfg: dict, cfile, record) -> list[dict]:
    """Append the niche to a channel's `niches` list (dedup) and persist. Returns
    the updated niches list."""
    from datetime import datetime, timezone
    niches = list(cfg.get("niches", []))
    if not any(n.get("niche_id") == record.niche_id for n in niches):
        niches.append({
            "niche_id": record.niche_id,
            "niche_name": record.niche_name,
            "assigned_at": datetime.now(timezone.utc).isoformat(),
        })
        cfg["niches"] = niches
        cfile.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
    return niches


def _autosave_discovered_niche(niche_id: str, vault_db_path):
    """Find a niche by id in the latest discovery results and persist it to the
    vault, returning the new NicheRecord. None if not found in results."""
    import json
    from datetime import datetime, timezone
    from omnicast.vault import db as vault_db
    from omnicast.vault.models import NicheRecord, NicheStatus
    from omnicast.agents.channel_builder import _detect_market

    cache_path = _ROOT / "output" / "niche_results.json"
    if not cache_path.exists():
        return None
    try:
        cache = json.loads(cache_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    niche = next((n for n in cache.get("niches", [])
                  if n.get("niche_id") == niche_id), None)
    if not niche:
        return None
    score = niche.get("total_score", niche.get("current_health", 0))
    record = NicheRecord(
        niche_id=niche["niche_id"], niche_name=niche["niche_name"],
        market=_detect_market(niche, fallback="US"), status=NicheStatus.WATCHING,
        original_score=score, current_health=score,
        saved_at=datetime.now(timezone.utc).isoformat(), last_checked=None,
        evidence_channel_ids=niche.get("example_channels", []), seed_queries=[],
        niche_data=niche,
    )
    vault_db.upsert_niche(record, vault_db_path)
    return vault_db.get_niche(niche_id, vault_db_path)


async def _vault_save_all_task():
    """Save all niches from cache to vault."""
    import json
    from omnicast.vault import db as vault_db
    from omnicast.vault.models import NicheRecord, NicheStatus
    from datetime import datetime, timezone
    VAULT_DB = _ROOT / "output" / "vault.db"
    cache_path = _ROOT / "output" / "niche_results.json"
    vault_db.init_db(VAULT_DB)
    cache = json.loads(cache_path.read_text(encoding="utf-8"))
    niches = cache.get("niches", [])
    
    from omnicast.agents.channel_builder import _detect_market
    for niche in niches:
        if vault_db.get_niche(niche["niche_id"], VAULT_DB):
            continue

        example_channels = niche.get("example_channels", [])
        score = niche.get("total_score", niche.get("current_health", 0))
        market = _detect_market(niche, fallback="US")

        record = NicheRecord(
            niche_id=niche["niche_id"], niche_name=niche["niche_name"],
            market=market, status=NicheStatus.WATCHING,
            original_score=score, current_health=score,
            saved_at=datetime.now(timezone.utc).isoformat(), last_checked=None,
            evidence_channel_ids=example_channels, seed_queries=[], niche_data=niche,
        )
        vault_db.upsert_niche(record, VAULT_DB)


async def _vault_health_check_task():
    """Health check all watching niches."""
    from omnicast.vault import db as vault_db
    from omnicast.vault.models import NicheStatus, HealthLog
    from omnicast.vault.health import check_all as health_check_all
    from omnicast.config.settings import get_settings
    from omnicast.discovery.key_rotator import YouTubeKeyRotator
    from datetime import datetime, timezone
    VAULT_DB = _ROOT / "output" / "vault.db"
    vault_db.init_db(VAULT_DB)
    settings = get_settings()
    key_pool = settings.youtube_key_pool
    if not key_pool:
        return
    rotator = YouTubeKeyRotator(key_pool)
    records = [r for r in vault_db.list_niches(path=VAULT_DB) if r.status not in (NicheStatus.ARCHIVED, NicheStatus.ACTIVE)]
    if not records:
        return
    results = await health_check_all(records, rotator)
    now_iso = datetime.now(timezone.utc).isoformat()
    for result in results:
        record = vault_db.get_niche(result.niche_id, VAULT_DB)
        if record:
            niche_data = dict(record.niche_data)
            niche_data["_last_health_notes"] = result.notes
            record = record.__class__(**{**record.__dict__, "niche_data": niche_data})
            vault_db.upsert_niche(record, VAULT_DB)
        vault_db.update_status(result.niche_id, result.new_status, result.new_score, VAULT_DB)
        vault_db.update_last_checked(result.niche_id, now_iso, VAULT_DB)
        status_change = f"{result.old_status.value}→{result.new_status.value}" if result.old_status != result.new_status else None
        vault_db.insert_log(HealthLog(
            log_id=None, niche_id=result.niche_id, scan_date=now_iso,
            new_videos_count=result.new_videos_count, avg_new_vpd=result.avg_new_vpd,
            dedicated_competitors=result.dedicated_competitors, micro_outlier_found=result.micro_outlier_found,
            health_score=result.new_score, status_change=status_change, notes="; ".join(result.notes),
        ), VAULT_DB)


async def _run_channel_phase1(channel_id: str):
    """Run Phase 1 (topic discovery) for a channel."""
    set_active_job(channel_id, "discovery")
    write_pipeline_event(channel_id, "discovery", "started")
    set_active_job_progress(
        channel_id,
        stage="Loading channel profile",
        pct=10,
        detail="Resolving channel JSON + niche config",
    )
    try:
        from omnicast.pipeline.models import StepStatus
        from omnicast.pipeline.runner import PipelineRunner

        set_active_job_progress(
            channel_id,
            stage="Pipeline runner discovery",
            pct=25,
            detail="Running omnicast.discovery via PipelineRunner",
        )
        step_result = await PipelineRunner(db_path=OUTPUT_DIR / "vault.db").run_single_step(
            "discovery",
            "omnicast.discovery",
            {"channel_id": channel_id},
            pipeline_id="api_channel_phase1",
            timeout_seconds=300,
        )
        if step_result.status != StepStatus.SUCCESS:
            raise RuntimeError(step_result.error or "pipeline discovery failed")

        outputs = step_result.outputs
        topic = str(outputs.get("topic") or "")
        score = int(outputs.get("score") or 0)
        topic_queue = list(outputs.get("topic_queue") or [])

        set_active_job_progress(
            channel_id,
            stage="Writing pipeline event",
            pct=95,
            detail=f"Persisting completed event (score={score})",
        )
        write_pipeline_event(
            channel_id, "discovery", "completed",
            topic=topic, score=score,
            extra={"topic_queue": topic_queue},
        )

        try:
            from omnicast.vault import db as vault_db
            from omnicast.vault.models import TopicRecord, TopicStatus
            from datetime import datetime, timezone
            VAULT_DB = OUTPUT_DIR / "vault.db"
            vault_db.init_db(VAULT_DB)
            now_iso = datetime.now(timezone.utc).isoformat()
            for q in topic_queue:
                title = q.get("title", "") if isinstance(q, dict) else str(q)
                if not title:
                    continue
                # Junk guard: a queue entry with no score AND no brief metadata is a
                # raw scraped title (often a verbatim competitor title) — producing it
                # risks near-duplicate content. Don't persist those to the vault.
                _q_score = int((q.get("score", 0) if isinstance(q, dict) else 0) or 0)
                _q_angle = (q.get("content_angle", "") if isinstance(q, dict) else "")
                _q_pain = (q.get("pain_point", "") if isinstance(q, dict) else "")
                if _q_score <= 0 and not (_q_angle or _q_pain):
                    continue
                vault_db.upsert_topic(TopicRecord(
                    topic_id=vault_db.make_topic_id(channel_id, title),
                    channel_id=channel_id, title=title,
                    score=_q_score,
                    status=TopicStatus.QUEUED,
                    discovered_at=now_iso,
                    rank=int((q.get("rank", 0) if isinstance(q, dict) else 0) or 0),
                    audience_segment=(q.get("audience_segment", "") if isinstance(q, dict) else ""),
                    pain_point=(q.get("pain_point", "") if isinstance(q, dict) else ""),
                    content_angle=(q.get("content_angle", "") if isinstance(q, dict) else ""),
                    source_url=(q.get("source_url", "") if isinstance(q, dict) else ""),
                ), VAULT_DB)
        except Exception as _texc:
            append_error(channel_id=channel_id, phase="discovery",
                         stage="topic_vault_persist", message=str(_texc),
                         traceback_str=traceback.format_exc())
        return

        from omnicast.config.channel import ChannelProfileLoader
        from omnicast.config.niches import get_niche_config
        from omnicast.config.settings import get_settings
        from omnicast.capabilities.llm_factory import create_llm
        from omnicast.discovery.orchestrator import DiscoveryOrchestrator
        from omnicast.agents.channel_architect import ChannelArchitectAgent

        settings = get_settings()
        loader = ChannelProfileLoader(CHANNELS_DIR)
        channel = await loader.load(channel_id)
        niche_cfg = get_niche_config(channel.niche.value, channel.sub_niche)

        set_active_job_progress(
            channel_id,
            stage="Discovery scan",
            pct=25,
            detail="YouTube + Reddit + News + Trends + Podcast in parallel",
        )
        orchestrator = DiscoveryOrchestrator.for_channel(channel)
        result = await orchestrator.run()

        all_raw = []
        for src in result.source_results:
            if src.success:
                all_raw.extend(src.topics)

        # SSOT: TopicScorer admits, ChannelArchitect ranks. This path used to
        # hand the Architect every raw topic and discard the scoring entirely,
        # while the orchestrator path honoured the same lanes — one policy,
        # applied on one path and skipped on the other.
        from omnicast.discovery import topic_router as _router

        _admission = _router.admit(result.scored_topics, all_raw)
        all_raw = _admission.admitted
        for _note in _admission.notes:
            logger.info("topic router", channel=channel_id, note=_note)

        topic = ""
        score = 0
        topic_queue: list[dict] = []

        if all_raw:
            set_active_job_progress(
                channel_id,
                stage="Channel-Architect LLM",
                pct=70,
                detail=f"Ranking top-5 from {len(all_raw)} raw topics",
            )
            llm = create_llm(default_provider="deepseek", model=settings.deepseek_flash_model)
            architect = ChannelArchitectAgent(llm=llm)
            opps = await architect.analyze(all_raw, channel, niche_cfg, top_n=5)
            # SSOT note: on THIS path ChannelArchitectAgent — not TopicScorer —
            # decides which topic gets produced. Recording only the scorer's
            # lane would calibrate a decision nobody makes, so the shadow corpus
            # is stamped with what the real router actually picked.
            try:
                from omnicast.discovery import shadow_log as _shadow

                if orchestrator.shadow_rows:
                    _shadow.mark_selected(
                        orchestrator.shadow_rows,
                        [o.title for o in opps],
                        decided_by="channel_architect",
                    )
                    _shadow.append_rows(
                        [{**r, "phase": "post_router"} for r in orchestrator.shadow_rows])
            except Exception as _sl_exc:  # telemetry must never break a run
                logger.warning("shadow selection not recorded", error=str(_sl_exc))
            if opps:
                best = opps[0]
                topic = best.title
                score = best.total_score
                # Save all top-5 as content queue for future scripts
                topic_queue = [
                    {
                        "rank": i + 1,
                        "title": o.title,
                        "score": o.total_score,
                        "audience_segment": o.audience_segment,
                        "pain_point": o.pain_point,
                        "content_angle": o.content_angle,
                        "source_url": o.source_video_url,
                    }
                    for i, o in enumerate(opps)
                ]

        set_active_job_progress(
            channel_id,
            stage="Writing pipeline event",
            pct=95,
            detail=f"Persisting completed event (score={score})",
        )
        write_pipeline_event(
            channel_id, "discovery", "completed",
            topic=topic, score=score,
            extra={"topic_queue": topic_queue},
        )

        # Persist every discovered topic to the Topic Vault so automation can pull
        # the next unused one later (pipeline_state.recent_results is capped at 20
        # events and would otherwise evict these). Dedup by stable topic_id.
        try:
            from omnicast.vault import db as vault_db
            from omnicast.vault.models import TopicRecord, TopicStatus
            from datetime import datetime, timezone
            VAULT_DB = OUTPUT_DIR / "vault.db"
            vault_db.init_db(VAULT_DB)
            now_iso = datetime.now(timezone.utc).isoformat()
            for q in topic_queue:
                title = q.get("title", "")
                if not title:
                    continue
                # Junk guard (same rule as phase-1 persist): no score + no brief
                # metadata = raw scraped title → skip, don't pollute the vault.
                if int(q.get("score", 0) or 0) <= 0 and not (
                        q.get("content_angle") or q.get("pain_point")):
                    continue
                vault_db.upsert_topic(TopicRecord(
                    topic_id=vault_db.make_topic_id(channel_id, title),
                    channel_id=channel_id, title=title,
                    score=int(q.get("score", 0) or 0), status=TopicStatus.QUEUED,
                    discovered_at=now_iso, rank=int(q.get("rank", 0) or 0),
                    audience_segment=q.get("audience_segment", ""),
                    pain_point=q.get("pain_point", ""),
                    content_angle=q.get("content_angle", ""),
                    source_url=q.get("source_url", ""),
                ), VAULT_DB)
        except Exception as _texc:
            append_error(channel_id=channel_id, phase="discovery",
                         stage="topic_vault_persist", message=str(_texc),
                         traceback_str=traceback.format_exc())

        # Learn competitor title + thumbnail playbooks for this niche (best-effort).
        try:
            from omnicast.analytics import competitor_intel
            await competitor_intel.learn_for_channel(channel)
        except Exception as _cexc:
            logger.warning("competitor intel skipped", error=str(_cexc))

    except Exception as exc:
        tb = traceback.format_exc()
        append_error(
            channel_id=channel_id,
            phase="discovery",
            stage=_current_stage(channel_id),
            message=str(exc),
            traceback_str=tb,
        )
        write_pipeline_event(channel_id, "discovery", "failed", extra={"error": str(exc)[:200]})
    finally:
        clear_active_job(channel_id)


async def _run_channel_phase2(channel_id: str, topic: str | None = None,
                              overrides: dict | None = None):
    """Run Phase 2 (script generation) for a channel.

    Uses last discovered topic from pipeline events if topic not provided.
    `overrides` (from the Create-Video form) may carry operator-supplied
    `audience` and `desc` that take precedence over the channel/topic defaults.
    """
    _ovr = overrides or {}
    _ovr_aud = str(_ovr.get("audience") or "").strip()
    _ovr_desc = str(_ovr.get("desc") or "").strip()
    set_active_job(channel_id, "script_generation")
    clear_live_log(channel_id)
    append_live_log(channel_id, {"type": "phase_start", "msg": "Phase 2: script generation started"})
    write_pipeline_event(channel_id, "script_generation", "started")
    set_active_job_progress(channel_id, stage="Loading channel profile", pct=5,
                            detail="Resolving channel JSON + niche config")
    try:
        from omnicast.pipeline.models import StepStatus
        from omnicast.pipeline.runner import PipelineRunner

        queued_topic: dict | None = None
        topics_done = [
            e.get("topic", "")
            for e in read_pipeline_state().get("recent_results", [])
            if e.get("channel_id") == channel_id
            and e.get("phase") == "script_generation"
            and e.get("status") == "completed"
            and e.get("topic")
        ]
        if not topic:
            try:
                from omnicast.vault import db as _vdb
                _VDB = OUTPUT_DIR / "vault.db"
                _vdb.init_db(_VDB)
                _nx = _vdb.get_next_topic(channel_id, _VDB)
                if _nx and _nx.title not in topics_done:
                    topic = _nx.title
                    queued_topic = {
                        "title": _nx.title,
                        "score": _nx.score,
                        "audience_segment": _nx.audience_segment,
                        "pain_point": _nx.pain_point,
                        "content_angle": _nx.content_angle,
                    }
            except Exception:
                pass
        # Topic was given explicitly (operator picked it in the vault / typed it).
        # Look up its vault record so the writer still receives the FULL brief
        # (audience/pain_point/content_angle) instead of a bare title.
        if topic and queued_topic is None:
            try:
                from omnicast.vault import db as _vdb2
                _VDB2 = OUTPUT_DIR / "vault.db"
                _vdb2.init_db(_VDB2)
                _rec = next((t for t in _vdb2.list_topics(channel_id=channel_id, path=_VDB2)
                             if t.title.strip().lower() == topic.strip().lower()), None)
                if _rec:
                    queued_topic = {
                        "title": _rec.title, "score": _rec.score,
                        "audience_segment": _rec.audience_segment,
                        "pain_point": _rec.pain_point,
                        "content_angle": _rec.content_angle,
                    }
            except Exception:
                pass
        if not topic:
            for event in reversed(read_pipeline_state().get("recent_results", [])):
                if (event.get("channel_id") == channel_id
                        and event.get("phase") == "discovery"
                        and event.get("status") == "completed"):
                    queue = event.get("topic_queue", [])
                    unused = [
                        q for q in queue
                        if (q.get("title", "") if isinstance(q, dict) else str(q)) not in topics_done
                    ]
                    if unused:
                        queued_topic = unused[0] if isinstance(unused[0], dict) else {"title": str(unused[0])}
                        topic = queued_topic["title"]
                    elif queue:
                        queued_topic = queue[0] if isinstance(queue[0], dict) else {"title": str(queue[0])}
                        topic = queued_topic["title"]
                    else:
                        topic = event.get("topic", "")
                    break

        if not topic:
            from omnicast.config.channel import ChannelProfileLoader
            channel = await ChannelProfileLoader(CHANNELS_DIR).load(channel_id)
            topic = f"5 {channel.niche.value.title()} Mistakes That Cost You Thousands"

        set_active_job_progress(channel_id, stage="Pipeline runner script", pct=20,
                                detail=f"Running omnicast.script for {topic[:60]}")
        step_inputs = {
            "channel_id": channel_id,
            "topic": topic,
            "audience": _ovr_aud or ((queued_topic or {}).get("audience_segment", "")),
            "pain_point": (queued_topic or {}).get("pain_point", ""),
            "content_angle": (queued_topic or {}).get("content_angle", ""),
            "operator_desc": _ovr_desc,
        }
        step_result = await PipelineRunner(db_path=OUTPUT_DIR / "vault.db").run_single_step(
            "script",
            "omnicast.script",
            step_inputs,
            pipeline_id="api_channel_phase2",
            timeout_seconds=3900,  # 2100 timed out on the heavier debate/polish flow
        )
        if step_result.status != StepStatus.SUCCESS:
            raise RuntimeError(step_result.error or "pipeline script failed")

        best_score = int(step_result.outputs.get("score") or 0)
        # NOTE: the "completed" event (with score AND cost_usd) is written by
        # _step_script itself now — writing it here too duplicated history rows.
        try:
            from omnicast.vault import db as _vdb
            from datetime import datetime as _dt, timezone as _tz
            _VDB = OUTPUT_DIR / "vault.db"
            _vdb.mark_topic_used(_vdb.make_topic_id(channel_id, topic),
                                 _dt.now(_tz.utc).isoformat(), None, _VDB)
        except Exception:
            pass
        append_live_log(channel_id, {
            "type": "phase_complete",
            "msg": f"Phase 2 complete via PipelineRunner (score={best_score})",
        })
        logger.info("Phase 2 complete via PipelineRunner",
                    channel_id=channel_id, score=best_score,
                    script_path=step_result.outputs.get("script_path", ""))
        return dict(step_result.outputs)

        from omnicast.config.channel import ChannelProfileLoader
        from omnicast.config.niches import get_niche_config
        from omnicast.config.settings import get_settings
        from omnicast.capabilities.llm_factory import create_llm
        from omnicast.models.script import TopicBrief, TopicSource
        from omnicast.agents.writer import WriterAgent
        from omnicast.agents.critic import CriticAgent
        from omnicast.agents.thinking import ThinkingAgent
        from omnicast.agents.compliance import ComplianceChecker
        from omnicast.agents.evolution import EvolutionAgent
        from omnicast.agents.visual_director import VisualDirectorAgent
        from omnicast.agents.orchestrator import DebateOrchestrator, DebateConfig
        from omnicast.services.budget import BudgetManager

        settings = get_settings()
        loader = ChannelProfileLoader(CHANNELS_DIR)
        channel = await loader.load(channel_id)
        niche_cfg = get_niche_config(channel.niche.value, channel.sub_niche)

        # Resolve topic + build channel memory (topics done, next teaser)
        queued_topic: dict | None = None
        topics_done: list[str] = []
        next_topic: str = ""

        pipeline = read_pipeline_state()

        # Collect all topics already scripted for this channel
        topics_done = [
            e.get("topic", "")
            for e in pipeline.get("recent_results", [])
            if e.get("channel_id") == channel_id
            and e.get("phase") == "script_generation"
            and e.get("status") == "completed"
            and e.get("topic")
        ]
        scripts_done = len(topics_done)

        # Prefer the durable Topic Vault (survives event churn). Highest-scoring
        # queued topic that hasn't been scripted yet.
        if not topic:
            try:
                from omnicast.vault import db as _vdb
                _VDB = OUTPUT_DIR / "vault.db"
                _vdb.init_db(_VDB)
                _nx = _vdb.get_next_topic(channel_id, _VDB)
                if _nx and _nx.title not in topics_done:
                    topic = _nx.title
                    queued_topic = {"title": _nx.title, "score": _nx.score,
                                    "audience_segment": _nx.audience_segment,
                                    "pain_point": _nx.pain_point,
                                    "content_angle": _nx.content_angle}
            except Exception:
                pass

        if not topic:
            # Fallback: last discovery event with topic_queue (older runs).
            for event in reversed(pipeline.get("recent_results", [])):
                if (event.get("channel_id") == channel_id
                        and event.get("phase") == "discovery"
                        and event.get("status") == "completed"):
                    queue = event.get("topic_queue", [])
                    # Skip already-scripted topics
                    unused = [q for q in queue if q["title"] not in topics_done]
                    if unused:
                        queued_topic = unused[0]
                        topic = queued_topic["title"]
                        # Next topic = second unused in queue (for outro teaser)
                        if len(unused) > 1:
                            next_topic = unused[1]["title"]
                    elif queue:
                        queued_topic = queue[0]
                        topic = queued_topic["title"]
                    else:
                        topic = event.get("topic", "")
                    break

        if not topic:
            topic = f"5 {channel.niche.value.title()} Mistakes That Cost You Thousands"

        set_active_job_progress(channel_id, stage="Building topic brief", pct=10,
                                detail=f"Topic: {topic[:60]}")

        brief = TopicBrief(
            title=topic,
            niche=channel.niche,
            market=channel.market,
            source=TopicSource.MANUAL,
            angle="pain_hook",
            target_duration_min=channel.target_duration_min,
            brand_voice=channel.brand_voice,
            channel_id=channel.channel_id,
            sub_niche=channel.sub_niche,
            competitor_intel_required=bool(
                getattr(channel, "competitor_intel_required", False)),
            key_points=([f"Operator brief: {_ovr_desc}"] if _ovr_desc else []) + [
                niche_cfg.hook_examples[0][:80] if niche_cfg.hook_examples else "",
                f"Key insight from {niche_cfg.proof_sources[0]}" if niche_cfg.proof_sources else "",
                f"Insider angle: {niche_cfg.insider_angle}",
            ],
            # Operator-supplied audience wins; else topic-queue metadata.
            target_audience=_ovr_aud or (queued_topic["audience_segment"] if queued_topic else ""),
            pain_point=queued_topic["pain_point"] if queued_topic else "",
            content_angle=queued_topic["content_angle"] if queued_topic else "",
            source_urls=[queued_topic["source_url"]] if queued_topic and queued_topic.get("source_url") else [],
            # Channel memory: what's done, what's next
            topics_done=topics_done,
            next_topic=next_topic,
        )

        set_active_job_progress(channel_id, stage="Generating script variants", pct=20,
                                detail="Writer Agent producing 2 variants (≈60s)")

        llm_claude = create_llm(default_provider="anthropic")
        llm_pro    = create_llm(default_provider="deepseek", model=settings.deepseek_pro_model)
        llm_flash  = create_llm(default_provider="deepseek", model=settings.deepseek_flash_model)

        def _live_cb(event: dict) -> None:
            append_live_log(channel_id, event)

        orchestrator = DebateOrchestrator(
            writer=WriterAgent(llm=llm_pro),
            critic=CriticAgent(llm=llm_pro),
            thinker=ThinkingAgent(llm=llm_flash),
            compliance=ComplianceChecker(llm=llm_flash),
            budget=BudgetManager(daily_budget_usd=settings.daily_llm_budget_usd),
            config=DebateConfig(
                max_rounds=7,
                convergence_delta=3,
                approval_threshold=70,
                run_tournament=True,
                run_evolution=True,
            ),
            evolution=EvolutionAgent(llm=llm_claude),
            visual_director=VisualDirectorAgent(llm=llm_flash),
            event_callback=_live_cb,
        )

        results = await orchestrator.run(brief, num_variants=2, channel=channel)

        set_active_job_progress(channel_id, stage="Saving scripts", pct=90,
                                detail=f"Writing {len(results)} variant(s) to disk")

        # One self-contained product folder per run (variants + debate + compliance
        # + canonical script.txt all live together). See omnicast.storage.products.
        from omnicast.storage import products as _products
        product_dir = _products.new_product_dir(channel_id, topic)
        scripts_dir = _products.variants_dir(product_dir)  # variants/*.txt|json land here

        best_score = 0
        for r in results:
            d = r.final_draft
            # Plain text — VO only (human readable)
            txt = d.hook + "\n\n"
            for seg in (d.segments or []):
                txt += f"[{seg.heading}]\n{seg.content}\n\n"
            txt += d.outro
            base = f"variant_{r.variant_id}_score{r.final_score}"
            (scripts_dir / f"{base}.txt").write_text(txt, encoding="utf-8")

            # Full JSON — VO + visual_prompt + sfx per scene (for media pipeline)
            scenes_data = []
            for seg in (d.segments or []):
                for scene in (seg.scenes or []):
                    scenes_data.append({
                        "segment": seg.heading,
                        "voiceover": scene.voiceover,
                        "visual_prompt": scene.visual_prompt,
                        "sfx": scene.sfx,
                        "duration_s": scene.duration_s,
                    })
            script_json = {
                "variant_id": r.variant_id,
                "score": r.final_score,
                "approved": r.approved,
                "hook": d.hook,
                "outro": d.outro,
                "scenes": scenes_data,
                "channel_id": channel_id,
                "topic": topic,
            }
            import json as _json
            (scripts_dir / f"{base}.json").write_text(
                _json.dumps(script_json, indent=2, ensure_ascii=False), encoding="utf-8"
            )

            if r.final_score > best_score:
                best_score = r.final_score

        # Save debate log alongside scripts (dashboard reads this for agent activity view)
        debate_log: list[dict] = []
        for r in results:
            for rd in (r.rounds or []):
                fb = rd.feedback
                debate_log.append({
                    "variant_id": r.variant_id,
                    "round_number": rd.round_number,
                    "score": fb.total_score if fb else 0,
                    "voiceover_score": fb.voiceover_score if fb else 0,
                    "production_score": fb.production_score if fb else 0,
                    "approved": fb.approved if fb else False,
                    "score_delta": rd.score_delta,
                    "rejection_reasons": fb.rejection_reasons if fb else [],
                    "specific_fixes": fb.specific_fixes if fb else [],
                    "visual_fixes": fb.visual_fixes if fb else [],
                    "exit_reason": r.exit_reason,
                })
        _ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        (scripts_dir / f"debate_{_ts}.json").write_text(
            _json.dumps({"rounds": debate_log, "topic": topic, "ts": _ts}, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        best = max(results, key=lambda r: (r.approved, r.final_score)) if results else None

        try:
            if best is not None:
                best_vo = sum(len((sc.voiceover or "").split())
                              for seg in (best.final_draft.segments or [])
                              for sc in (seg.scenes or []))
                _TARGET_VO = 1300
                if best_vo < _TARGET_VO:
                    from omnicast.capabilities.llm_factory import create_llm
                    from omnicast.config.settings import get_settings as _gs
                    _s = _gs()
                    _btxt = scripts_dir / f"variant_{best.variant_id}_score{best.final_score}.txt"
                    _cur = _btxt.read_text(encoding="utf-8") if _btxt.exists() else ""
                    if _cur:
                        _exp = create_llm(default_provider="deepseek", model=_s.deepseek_chat_model)
                        _pr = (f"Expand this YouTube script to AT LEAST {_TARGET_VO} spoken "
                               f"words (currently ~{best_vo}) by INSERTING additional scenes "
                               "(more data points, concrete examples, short mini-stories, "
                               "objection+rebuttal) into the EXISTING 'SCENES:' JSON blocks. "
                               "Keep the exact HOOK/SEGMENT/OUTRO structure + JSON format, "
                               "each \"vo\" 18-25 words, no scam/demonetize words. Output the "
                               f"FULL expanded script ONLY.\n\n{_cur}")
                        _r = await _exp.complete(
                            system="You expand video scripts while preserving their exact format.",
                            messages=[{"role": "user", "content": _pr[:16000]}],
                            max_tokens=15000, temperature=0.4)
                        if _r.content and len(_r.content.split()) > len(_cur.split()) * 1.1:
                            _btxt.write_text(_r.content, encoding="utf-8")
                            set_active_job_progress(channel_id, stage="Expanding to 8-min length",
                                                    pct=95, detail=f"VO {best_vo}→~{_TARGET_VO} words")
                            logger.info("Length guard expanded best script",
                                        channel_id=channel_id, from_words=best_vo)

                            # Parse back the expanded content to update the .json file and best.final_draft
                            try:
                                expanded_draft = orchestrator.writer._parse_draft(_r.content, best.variant_id, topic)
                                best = best.model_copy(update={"final_draft": expanded_draft})

                                _bjson = scripts_dir / f"variant_{best.variant_id}_score{best.final_score}.json"
                                scenes_data = []
                                for sc in (expanded_draft.hook_scenes or []):
                                    scenes_data.append({
                                        "segment": "HOOK",
                                        "voiceover": sc.voiceover,
                                        "visual_prompt": sc.visual_prompt,
                                        "sfx": sc.sfx,
                                        "duration_s": sc.duration_s,
                                    })
                                for seg in (expanded_draft.segments or []):
                                    for sc in (seg.scenes or []):
                                        scenes_data.append({
                                            "segment": seg.heading,
                                            "voiceover": sc.voiceover,
                                            "visual_prompt": sc.visual_prompt,
                                            "sfx": sc.sfx,
                                            "duration_s": sc.duration_s,
                                        })
                                for sc in (expanded_draft.outro_scenes or []):
                                    scenes_data.append({
                                        "segment": "OUTRO",
                                        "voiceover": sc.voiceover,
                                        "visual_prompt": sc.visual_prompt,
                                        "sfx": sc.sfx,
                                        "duration_s": sc.duration_s,
                                    })
                                script_json = {
                                    "variant_id": best.variant_id,
                                    "score": best.final_score,
                                    "approved": best.approved,
                                    "hook": expanded_draft.hook,
                                    "outro": expanded_draft.outro,
                                    "scenes": scenes_data,
                                    "channel_id": channel_id,
                                    "topic": topic,
                                }
                                _bjson.write_text(_json.dumps(script_json, indent=2, ensure_ascii=False), encoding="utf-8")
                                logger.info("Length guard successfully synced both .txt and .json files", channel_id=channel_id)
                            except Exception as _pexc:
                                logger.warning("Length guard failed to parse or write expanded JSON", error=str(_pexc))
        except Exception as _lexc:
            logger.warning("Length guard expand failed", error=str(_lexc))

        # Promote the chosen (possibly expanded) variant to the canonical product
        # script.txt + write the manifest so render/upload/list all resolve here.
        try:
            if best is not None:
                _bt = scripts_dir / f"variant_{best.variant_id}_score{best.final_score}.txt"
                if _bt.exists():
                    _products.script_path(product_dir).write_text(
                        _bt.read_text(encoding="utf-8"), encoding="utf-8")
                _products.write_meta(
                    product_dir, channel=channel_id, topic=topic, slug=product_dir.name,
                    stage="script", script="script.txt",
                    best_variant=best.variant_id, score=best.final_score)
        except Exception as _mexc:
            logger.warning("Product manifest write failed", error=str(_mexc))

        # POLICY GATE AT SCRIPT TIME — catch unusable content (scam/misleading,
        # demonetization triggers) BEFORE wasting a render. Write a sidecar flag
        # the render/auto step reads to refuse a non-compliant script.
        policy_violations: list[str] = []
        try:
            from omnicast.upload.compliance import ComplianceChecker
            best_txt = ""
            if best is not None:
                bd = best.final_draft
                best_txt = (bd.hook or "") + " " + " ".join(
                    (seg.content or "") for seg in (bd.segments or [])) + " " + (bd.outro or "")
            policy_violations = ComplianceChecker.check_text(topic, best_txt)
            (product_dir / "_compliance.json").write_text(
                _json.dumps({"topic": topic, "violations": policy_violations,
                             "compliant": not policy_violations,
                             "checked_at": datetime.utcnow().isoformat()},
                            ensure_ascii=False), encoding="utf-8")
            if policy_violations:
                append_error(channel_id=channel_id, phase="script_generation",
                             stage="policy_gate",
                             message="Script vi phạm policy: " + "; ".join(policy_violations),
                             traceback_str="")
        except Exception as _pexc:
            logger.warning("Script policy gate failed", error=str(_pexc))

        write_pipeline_event(channel_id, "script_generation", "completed",
                             topic=topic, score=best_score,
                             extra={"policy_violations": policy_violations,
                                    "compliant": not policy_violations})
        # Mark the Topic Vault entry used so automation moves to the next topic.
        try:
            from omnicast.vault import db as _vdb
            from datetime import datetime as _dt, timezone as _tz
            _VDB = OUTPUT_DIR / "vault.db"
            _vdb.mark_topic_used(_vdb.make_topic_id(channel_id, topic),
                                 _dt.now(_tz.utc).isoformat(), None, _VDB)
        except Exception:
            pass
        logger.info("Phase 2 complete", channel_id=channel_id, variants=len(results),
                    best_score=best_score, approved=best.approved if best else False)

    except Exception as exc:
        tb = traceback.format_exc()
        append_error(channel_id=channel_id, phase="script_generation",
                     stage=_current_stage(channel_id), message=str(exc), traceback_str=tb)
        write_pipeline_event(channel_id, "script_generation", "failed",
                             extra={"error": str(exc)[:200]})
        raise
    finally:
        clear_active_job(channel_id)


async def _run_channel_phase3(
    channel_id: str,
    script_json_path: str,
    max_scenes: int | None = None,
    backend: str = "browser",
):
    """Run Phase 3 image generation for a channel.

    backend=browser → CloakBrowser + Gemini Pro web (free)
    backend=api     → Imagen 4 via Gemini API ($0.03/image)
    """
    set_active_job(channel_id, "image_generation")
    write_pipeline_event(channel_id, "image_generation", "started",
                         extra={"script_json": script_json_path, "backend": backend})
    set_active_job_progress(channel_id, stage="Loading script JSON", pct=5,
                            detail=str(script_json_path))
    try:
        import json as _json
        from omnicast.config.settings import get_settings

        settings = get_settings()
        data = _json.loads(Path(script_json_path).read_text(encoding="utf-8"))
        scenes = data.get("scenes", [])
        n = min(len(scenes), max_scenes) if max_scenes else len(scenes)
        topic = data.get("topic", "")

        if backend == "browser":
            from omnicast.media.browser_imagen import generate_images_for_script_browser
            set_active_job_progress(
                channel_id,
                stage="Generating images (Gemini web)",
                pct=10,
                detail=f"{n} scenes via Gemini Pro — sequential, ~{n * 20}s",
            )
            results = await generate_images_for_script_browser(
                script_json_path=script_json_path,
                headless=True,
                max_scenes=max_scenes,
            )
            cost_per_image = 0.0

        else:
            from omnicast.media.imagen4 import generate_images_for_script
            dry_run = settings.is_dry_run
            set_active_job_progress(
                channel_id,
                stage="Generating images (Imagen 4 API)",
                pct=10,
                detail=f"{n} scenes × $0.03 = ~${n * 0.03:.2f}",
            )
            results = await generate_images_for_script(
                script_json_path=script_json_path,
                google_api_key=settings.google_api_key,
                dry_run=dry_run,
                max_scenes=max_scenes,
            )
            cost_per_image = 0.03

        done    = sum(1 for r in results if r["status"] == "done")
        failed  = sum(1 for r in results if r["status"] == "failed")
        skipped = sum(1 for r in results if r["status"] == "skipped")
        cost_usd = round(done * cost_per_image, 3)

        set_active_job_progress(channel_id, stage="Saving results", pct=95,
                                detail=f"done={done} failed={failed} skipped={skipped}")

        write_pipeline_event(
            channel_id, "image_generation", "completed",
            topic=topic,
            score=0,
            extra={
                "script_json": script_json_path,
                "backend": backend,
                "images_done": done,
                "images_failed": failed,
                "images_skipped": skipped,
                "cost_usd": cost_usd,
                "images_dir": str(Path(script_json_path).parent / "images"),
            },
        )
        logger.info(
            "Phase 3 complete",
            channel_id=channel_id,
            backend=backend,
            done=done,
            failed=failed,
            cost_usd=cost_usd,
        )

    except Exception as exc:
        tb = traceback.format_exc()
        append_error(channel_id=channel_id, phase="image_generation",
                     stage=_current_stage(channel_id), message=str(exc), traceback_str=tb)
        write_pipeline_event(channel_id, "image_generation", "failed",
                             extra={"error": str(exc)[:200]})
    finally:
        clear_active_job(channel_id)


# ── Web UI (new OmniCast Engine standalone interface) ───────────────────────────
# Mounted LAST so it never shadows the /api/* routes above. Serves the React
# (in-browser babel) single-page app at "/", with its assets/fonts/jsx modules.
import os
_WEBUI_V1_DIR = Path(__file__).parent / ".legacy" / "webui"
_WEBUI_V2_DIR = Path(__file__).parent / "webui_v2"

_use_v1 = os.environ.get("OMNICAST_UI") == "v1"
if not _use_v1 and _WEBUI_V2_DIR.is_dir():
    _WEBUI_DIR = _WEBUI_V2_DIR
else:
    _WEBUI_DIR = _WEBUI_V1_DIR

# office_app (pixel-art Văn phòng, Vite build riêng) sống trong webui v1 và trước
# đây được serve nhờ mount "/" của v1. Khi "/" là webui_v2, phải mount riêng —
# nếu không iframe /office_app/index.html trong Studio sẽ 404.
_OFFICE_APP_DIR = _WEBUI_V1_DIR / "office_app"
if _WEBUI_DIR is _WEBUI_V2_DIR and _OFFICE_APP_DIR.is_dir():
    app.mount("/office_app", StaticFiles(directory=str(_OFFICE_APP_DIR), html=True),
              name="office_app")

# Mobile UI (mobile/ Vite build → webui_mobile). Mount TRƯỚC mount "/" catch-all.
# Điện thoại trong LAN mở http://<ip>:8767/m (Add to Home Screen) trong lúc chờ APK.
_WEBUI_MOBILE_DIR = Path(__file__).parent / "webui_mobile"
if _WEBUI_MOBILE_DIR.is_dir():
    app.mount("/m", StaticFiles(directory=str(_WEBUI_MOBILE_DIR), html=True),
              name="webui_mobile")

if _WEBUI_DIR.is_dir():
    # Serve the SPA shell (index.html) with `no-store` so the desktop WebView2 never
    # holds a cached index that points at a hashed bundle a later rebuild has deleted
    # (emptyOutDir wipes old assets) → stale shell → 404 JS → blank window. Hashed
    # assets under /assets stay immutable-cacheable via the StaticFiles mount below.
    from fastapi.responses import FileResponse as _FileResponse

    _V2_INDEX = _WEBUI_DIR / "index.html"

    @app.get("/", include_in_schema=False)
    async def _spa_index():
        return _FileResponse(str(_V2_INDEX), headers={"Cache-Control": "no-store"})

    app.mount("/", StaticFiles(directory=str(_WEBUI_DIR), html=True), name="webui")
