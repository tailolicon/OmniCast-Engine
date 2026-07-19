"""OmniCast Job Engine (M0 foundation).

Generic background-job layer all pipelines run on: jobs/steps/checkpoints/assets/
worker-slots/events in the vault.db SSOT, with resource-slot concurrency, an
in-process executor, checkpointed step runner, IStorage, asset GC, an event bus,
and a FastAPI v1 surface. Additive — wiring the existing content pipeline through
this lands in M1. See SPEC_M0_NenMong.md.

Note: `api` (FastAPI) and `rabbit` (aio_pika/orjson) are imported explicitly to
keep `import omnicast.jobengine` lightweight.
"""

from omnicast.jobengine.models import (
    JobSpec, JobStatus, StepStatus, ResourceClass, AssetState, WorkerSlots,
)
from omnicast.jobengine.idempotency import idempotency_key, canonical_inputs
from omnicast.jobengine.slots import SlotManager, SlotError
from omnicast.jobengine.events import EventBus
from omnicast.jobengine.engine import JobEngine, JobContext
from omnicast.jobengine.checkpoint import Step, run_checkpointed
from omnicast.jobengine.storage import IStorage, LocalDiskStorage
from omnicast.jobengine.assets import AssetService

__all__ = [
    "JobSpec", "JobStatus", "StepStatus", "ResourceClass", "AssetState", "WorkerSlots",
    "idempotency_key", "canonical_inputs",
    "SlotManager", "SlotError", "EventBus", "JobEngine", "JobContext",
    "Step", "run_checkpointed", "IStorage", "LocalDiskStorage", "AssetService",
]
