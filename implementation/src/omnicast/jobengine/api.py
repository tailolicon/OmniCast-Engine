"""FastAPI v1 surface for the Job Engine (M0, PR8).

Submit Job + Check Status + realtime events (SSE). The API never runs long work
synchronously by default (submit → background); pass ?wait=true to await inline
(used by tests / quick jobs). Mount via `create_app(engine)`.
"""

from __future__ import annotations

import json
import uuid as _uuid

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from omnicast.jobengine import store
from omnicast.jobengine.models import JobSpec, ResourceClass


class SubmitBody(BaseModel):
    type: str
    resource_class: ResourceClass = ResourceClass.CPU
    priority: int = 3
    payload: dict = {}
    job_id: str | None = None


def create_app(engine) -> FastAPI:
    app = FastAPI(title="OmniCast Job Engine API", version="1.0")

    @app.post("/api/v1/jobs")
    async def submit_job(body: SubmitBody, wait: bool = Query(False)):
        spec = JobSpec(job_id=body.job_id or _uuid.uuid4().hex, type=body.type,
                       resource_class=body.resource_class, priority=body.priority, payload=body.payload)
        if wait:
            try:
                await engine.execute(spec)
            except Exception:
                pass
        else:
            await engine.submit(spec)
        return {"job_id": spec.job_id}

    @app.get("/api/v1/jobs")
    async def list_jobs(status: str | None = None, limit: int = 50):
        return store.list_jobs(status=status, limit=limit, db_path=engine.db_path)

    @app.get("/api/v1/jobs/{job_id}")
    async def get_job(job_id: str):
        j = engine.status(job_id)
        if j is None:
            raise HTTPException(404, "job not found")
        return j

    @app.post("/api/v1/jobs/{job_id}/retry")
    async def retry_job(job_id: str):
        try:
            await engine.retry(job_id)
        except KeyError:
            raise HTTPException(404, "job not found")
        except Exception:
            pass
        return engine.status(job_id)

    @app.get("/api/v1/assets/{asset_id}")
    async def get_asset(asset_id: str):
        a = store.get_asset(asset_id, db_path=engine.db_path)
        if a is None:
            raise HTTPException(404, "asset not found")
        return a

    @app.get("/api/v1/events")
    async def events(since_id: int = 0, limit: int = 100):
        return store.list_events(since_id=since_id, limit=limit, db_path=engine.db_path)

    @app.get("/api/v1/events/stream")
    async def events_stream(job_id: str | None = None):
        async def gen():
            async for ev in engine.events.subscribe(job_id=job_id):
                yield f"data: {json.dumps(ev)}\n\n"
        return StreamingResponse(gen(), media_type="text/event-stream")

    @app.get("/api/v1/health")
    async def health():
        ok = True
        detail: dict = {}
        try:
            store.init_jobengine_schema(engine.db_path)
            detail["db"] = "ok"
        except Exception as e:
            ok = False
            detail["db"] = str(e)
        detail["handlers"] = sorted(engine._handlers.keys())
        detail["slots"] = {k.value: v for k, v in engine.slots.counts.items()}
        return {"ok": ok, **detail}

    return app
