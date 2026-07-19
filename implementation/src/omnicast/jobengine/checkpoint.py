"""Checkpointed step runner (M0, PR5).

Runs a list of pipeline steps, skipping any whose idempotency key + saved output
still match — so a crash/retry re-runs ONLY the failed step instead of the whole
pipeline (no wasted LLM/voice/render spend). Generalises Flow's per-image retry.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Awaitable, Callable

from omnicast.jobengine import store
from omnicast.jobengine.idempotency import idempotency_key


@dataclass
class Step:
    name: str
    fn: Callable[[dict], Awaitable[tuple]]   # async (inputs) -> (output_ref | None, output_dict)
    inputs: dict = field(default_factory=dict)


async def run_checkpointed(job_id, steps, *, events=None, total=None, exists_fn=None, db_path=None):
    """Execute steps with checkpoint/skip. `exists_fn(output_ref)->bool` optionally
    re-validates that a checkpoint's output still exists (e.g. IStorage.exists)."""
    total = total if total is not None else len(steps)
    results = {}
    for i, st in enumerate(steps):
        key = idempotency_key(st.name, st.inputs)
        ck = store.get_checkpoint(job_id, st.name, db_path=db_path)
        valid = bool(ck) and ck["idempotency_key"] == key and (
            ck["output_ref"] is None or exists_fn is None or exists_fn(ck["output_ref"]))
        if valid:
            store.upsert_step(job_id, i, st.name, "skipped", db_path=db_path)
            if events:
                events.emit("job.step.progress", job_id=job_id, idx=i, total=total, name=st.name, state="skipped")
            results[st.name] = ck["output"]
            continue
        store.upsert_step(job_id, i, st.name, "running", mark_started=True, db_path=db_path)
        if events:
            events.emit("job.step.progress", job_id=job_id, idx=i, total=total, name=st.name, state="running")
        out_ref, out = await st.fn(st.inputs)
        store.save_checkpoint(job_id, st.name, key, out_ref, out, db_path=db_path)
        store.upsert_step(job_id, i, st.name, "success", mark_finished=True, db_path=db_path)
        if events:
            events.emit("job.step.progress", job_id=job_id, idx=i, total=total, name=st.name, state="success")
        results[st.name] = out
    return results
