"""In-process Job Engine (M0, PR4).

Runs registered job handlers under resource-slot concurrency, persists job/step
state to vault.db, and emits progress events. Decision (SPEC_M0 §12): pipeline
steps run in-process (not one RabbitMQ job per step) — checkpointing handles
crash-resume. submit() schedules in the background; execute() awaits inline.
"""

from __future__ import annotations

import asyncio

from omnicast.jobengine import store
from omnicast.jobengine.models import JobSpec, JobStatus, ResourceClass
from omnicast.jobengine.slots import SlotManager
from omnicast.jobengine.events import EventBus


class JobContext:
    """Passed to a handler: identifies the job and exposes progress reporting."""

    def __init__(self, engine, spec):
        self.engine = engine
        self.spec = spec
        self.job_id = spec.job_id
        self.payload = spec.payload
        self.events = engine.events
        self.db_path = engine.db_path

    def progress(self, idx, total, name, state):
        store.upsert_step(self.job_id, idx, name, state, db_path=self.db_path)
        self.events.emit("job.step.progress", job_id=self.job_id,
                         idx=idx, total=total, name=name, state=state)


class JobEngine:
    def __init__(self, slots=None, events=None, db_path=None):
        self.slots = slots or SlotManager()
        self.events = events or EventBus(db_path=db_path)
        self.db_path = db_path
        self._handlers: dict = {}

    def register(self, job_type, handler):
        """handler: async (JobContext) -> result. Raises to mark the job failed."""
        self._handlers[job_type] = handler

    async def _run(self, spec):
        h = self._handlers.get(spec.type)
        if h is None:
            store.set_job_status(spec.job_id, JobStatus.FAILED,
                                 error=f"no handler for type '{spec.type}'",
                                 mark_finished=True, db_path=self.db_path)
            self.events.emit("job.finished", job_id=spec.job_id, status="failed", error="no handler")
            raise KeyError(f"no handler for type '{spec.type}'")
        store.set_job_status(spec.job_id, JobStatus.RUNNING, mark_started=True, db_path=self.db_path)
        self.events.emit("job.started", job_id=spec.job_id, type=spec.type)
        try:
            async with self.slots.acquire(spec.resource_class):
                result = await h(JobContext(self, spec))
            store.set_job_status(spec.job_id, JobStatus.SUCCESS, mark_finished=True, db_path=self.db_path)
            self.events.emit("job.finished", job_id=spec.job_id, status="success")
            return result
        except Exception as e:
            store.set_job_status(spec.job_id, JobStatus.FAILED, error=str(e)[:500],
                                 mark_finished=True, db_path=self.db_path)
            self.events.emit("job.finished", job_id=spec.job_id, status="failed", error=str(e)[:200])
            raise

    async def execute(self, spec):
        """Insert + run inline (await). Returns the handler result."""
        store.insert_job(spec, db_path=self.db_path)
        return await self._run(spec)

    async def submit(self, spec):
        """Insert + run in the background. Returns the job_id immediately."""
        store.insert_job(spec, db_path=self.db_path)
        asyncio.ensure_future(self._run_safe(spec))
        return spec.job_id

    async def _run_safe(self, spec):
        try:
            await self._run(spec)
        except Exception:
            pass

    def status(self, job_id):
        j = store.get_job(job_id, db_path=self.db_path)
        if j is None:
            return None
        j["steps"] = store.get_steps(job_id, db_path=self.db_path)
        return j

    async def retry(self, job_id):
        """Re-run an existing job (row reused; checkpointed steps skip completed work)."""
        j = store.get_job(job_id, db_path=self.db_path)
        if not j:
            raise KeyError(job_id)
        spec = JobSpec(job_id=job_id, type=j["type"],
                       resource_class=ResourceClass(j["resource_class"]),
                       priority=j["priority"], payload=j["payload"],
                       parent_job_id=j.get("parent_job_id"))
        store.set_job_status(job_id, JobStatus.QUEUED, attempt=(j.get("attempt") or 0) + 1, db_path=self.db_path)
        return await self._run(spec)
