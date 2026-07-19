"""Shared types for capability-based execution."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable


CapabilityHandler = Callable[[dict], Awaitable[Any]]


@dataclass(frozen=True)
class Capability:
    capability_id: str
    kind: str
    provider_id: str
    model_id: str = ""
    runtime: str = "remote"
    cost_per_unit: float = 0.0
    min_vram_mb: int = 0
    fallback: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)


@dataclass(frozen=True)
class ResolvePolicy:
    prefer_provider_id: str | None = None
    fallback_chain: list[str] = field(default_factory=list)
    prefer_runtime: str | None = None
    max_cost_usd: float | None = None
    scope: str = "global"
    scope_id: str = "default"
    estimated_units: float = 1.0
    require_credential: bool = False


@dataclass(frozen=True)
class CapabilityResult:
    status: str
    value: Any = None
    capability: Capability | None = None
    cost_usd: float = 0.0
    raw: dict = field(default_factory=dict)
