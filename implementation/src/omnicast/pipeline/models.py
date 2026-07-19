"""Pydantic models for the Kestra-lite pipeline spec and execution log."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


# ── Step types ────────────────────────────────────────────────────────────────

class StepStatus(str, Enum):
    PENDING   = "pending"
    RUNNING   = "running"
    SUCCESS   = "success"
    FAILED    = "failed"
    SKIPPED   = "skipped"


class ExecutionStatus(str, Enum):
    RUNNING   = "running"
    SUCCESS   = "success"
    FAILED    = "failed"
    CANCELLED = "cancelled"


# ── Spec models ───────────────────────────────────────────────────────────────

class RetrySpec(BaseModel):
    max_attempts: int = 1
    delay_seconds: float = 30.0
    backoff_multiplier: float = 2.0   # exponential: delay * multiplier^attempt


class StepSpec(BaseModel):
    id: str
    type: str                                      # e.g. "omnicast.discovery"
    depends_on: list[str] = Field(default_factory=list)
    condition: str | None = None                   # Jinja2 expression; falsy → SKIPPED
    retry: RetrySpec = Field(default_factory=RetrySpec)
    timeout_seconds: float = 600.0
    inputs: dict[str, Any] = Field(default_factory=dict)


class ScheduleSpec(BaseModel):
    cron: str                                      # APScheduler cron string
    channel_id: str | None = None                  # if set, injected into inputs
    do_upload: bool = False


class PipelineSpec(BaseModel):
    id: str
    name: str = ""
    description: str = ""
    schedule: ScheduleSpec | None = None
    steps: list[StepSpec]

    def step_order(self) -> list[str]:
        """Topological sort of step IDs based on depends_on edges."""
        from graphlib import TopologicalSorter
        graph: dict[str, set[str]] = {s.id: set(s.depends_on) for s in self.steps}
        ts = TopologicalSorter(graph)
        return list(ts.static_order())


# ── Result models ─────────────────────────────────────────────────────────────

class StepResult(BaseModel, arbitrary_types_allowed=True):
    step_id: str
    status: StepStatus
    started_at: datetime
    finished_at: datetime | None = None
    outputs: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    attempts: int = 1


class Execution(BaseModel):
    execution_id: str
    pipeline_id: str
    channel_id: str | None = None
    status: ExecutionStatus = ExecutionStatus.RUNNING
    started_at: datetime
    finished_at: datetime | None = None
    inputs: dict[str, Any] = Field(default_factory=dict)
    steps: dict[str, StepResult] = Field(default_factory=dict)
    error: str | None = None
