"""Runtime fallback resolver."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from omnicast.capabilities.registry import CapabilityRegistry
from omnicast.capabilities.types import Capability, ResolvePolicy
from omnicast.runtime.probe import ResourceProbe


@dataclass(frozen=True)
class ResolvedTarget:
    capability: Capability
    runtime: str
    provider_id: str
    model_id: str
    reason: str
    skipped: list[dict] = field(default_factory=list)


class RuntimeRouter:
    """Resolve a sorted fallback chain for a capability."""

    def __init__(
        self,
        registry: CapabilityRegistry | None = None,
        *,
        db_path: Path | None = None,
        probe: ResourceProbe | None = None,
    ) -> None:
        self.registry = registry or CapabilityRegistry(db_path)
        self.probe = probe or ResourceProbe()

    def resolve(self, capability: str, policy: ResolvePolicy | None = None) -> list[ResolvedTarget]:
        policy = policy or ResolvePolicy()
        candidates = self.registry.list_capabilities(capability)
        runtime_rank = self._rank(policy.prefer_runtime)
        fallback_rank = {
            provider_id: idx
            for idx, provider_id in enumerate(policy.fallback_chain or [])
        }

        def _rank_candidate(candidate: Capability):
            preferred = 0 if policy.prefer_provider_id and candidate.provider_id == policy.prefer_provider_id else 1
            fallback = fallback_rank.get(candidate.provider_id, len(fallback_rank) + 1)
            return (preferred, fallback, runtime_rank(candidate.runtime), candidate.cost_per_unit)

        candidates = sorted(candidates, key=_rank_candidate)
        resolved: list[ResolvedTarget] = []
        skipped: list[dict] = []
        for candidate in candidates:
            if policy.max_cost_usd is not None and candidate.cost_per_unit > policy.max_cost_usd:
                skipped.append({
                    "capability_id": candidate.capability_id,
                    "reason": "cost_above_policy",
                })
                continue
            if not self.probe.can_run(candidate):
                skipped.append({
                    "capability_id": candidate.capability_id,
                    "reason": "insufficient_vram",
                    "min_vram_mb": candidate.min_vram_mb,
                })
                continue
            resolved.append(ResolvedTarget(
                capability=candidate,
                runtime=candidate.runtime,
                provider_id=candidate.provider_id,
                model_id=candidate.model_id,
                reason="preferred" if not resolved else "fallback",
                skipped=list(skipped),
            ))
        return resolved

    @staticmethod
    def _rank(prefer_runtime: str | None):
        base = {"local": 0, "remote": 1, "browser": 2}
        if prefer_runtime == "remote":
            base = {"remote": 0, "local": 1, "browser": 2}
        elif prefer_runtime == "browser":
            base = {"browser": 0, "remote": 1, "local": 2}
        return lambda runtime: base.get(runtime, 99)
