"""Job Engine models (M0).

Pydantic models + enums for the generic background-job layer that all pipelines
(script→voice→render→thumbnail→publish) run on top of. See SPEC_M0_NenMong.md.

M0 is additive-only: these models back the new vault tables (jobs/job_steps/
checkpoints/assets/worker_slots/events) and do NOT change existing production
behaviour until the runner is wired through the Job Engine (PR4/PR5).
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"
    WAITING_APPROVAL = "waiting_approval"  # used by HITL gate in M1


class StepStatus(str, Enum):
    """Mirrors pipeline.models.StepStatus + TIMEOUT (M0 extension)."""
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"
    TIMEOUT = "timeout"


class ResourceClass(str, Enum):
    """Maps a job to a RabbitMQ resource-class queue (jobs.<rc>) whose consumer
    prefetch == worker slots → bounded concurrency (anti-OOM)."""
    CPU = "cpu"
    GPU = "gpu"
    NET = "net"


class AssetState(str, Enum):
    ACTIVE = "active"
    ORPHANED = "orphaned"
    DELETED = "deleted"


class JobSpec(BaseModel):
    """What a caller submits to the Job Engine."""
    job_id: str
    type: str                                  # "pipeline" | "render" | "upload" | "tts" ...
    resource_class: ResourceClass = ResourceClass.CPU
    priority: int = Field(default=3, ge=1, le=9)
    payload: dict[str, Any] = Field(default_factory=dict)
    parent_job_id: str | None = None


class WorkerSlots(BaseModel):
    """STATIC config a worker reads at startup to set its QoS prefetch per
    resource class. Not updated in realtime (RabbitMQ requeues on crash)."""
    worker_id: str
    slots_gpu: int = 0
    slots_cpu: int = 4
    slots_net: int = 8
