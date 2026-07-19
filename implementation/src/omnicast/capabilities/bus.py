"""CapabilityBus orchestration with budget/key guards."""

from __future__ import annotations

from pathlib import Path

from omnicast.capabilities.registry import CapabilityRegistry
from omnicast.capabilities.types import CapabilityResult, ResolvePolicy
from omnicast.credentials.budget_guard import BudgetGuard
from omnicast.credentials.keypool import KeyPool
from omnicast.shared.errors import ConfigError


class CapabilityBus:
    """Run capability handlers through KeyPool and BudgetGuard."""

    def __init__(
        self,
        registry: CapabilityRegistry | None = None,
        *,
        db_path: Path | None = None,
        keypool: KeyPool | None = None,
        budget_guard: BudgetGuard | None = None,
    ) -> None:
        self.registry = registry or CapabilityRegistry(db_path)
        self.db_path = db_path
        self.keypool = keypool or KeyPool(db_path)
        self.budget_guard = budget_guard or BudgetGuard(db_path)

    async def run(
        self,
        capability: str,
        request: dict,
        *,
        policy: ResolvePolicy | None = None,
        on_progress=None,
    ) -> CapabilityResult:
        policy = policy or ResolvePolicy()
        candidates = self.registry.list_capabilities(capability)
        if policy.prefer_runtime:
            candidates.sort(key=lambda c: 0 if c.runtime == policy.prefer_runtime else 1)
        if not candidates:
            raise ConfigError(f"No capability registered for '{capability}'")
        selected = candidates[0]
        cost = float(request.get("estimated_cost_usd") or selected.cost_per_unit * policy.estimated_units)
        if policy.max_cost_usd is not None and cost > policy.max_cost_usd:
            raise ConfigError(f"Capability estimate ${cost:.4f} exceeds policy max ${policy.max_cost_usd:.4f}")
        self.budget_guard.check(policy.scope, policy.scope_id, cost)
        credential = None
        if policy.require_credential:
            credential = self.keypool.acquire(selected.provider_id)
        if on_progress:
            on_progress({"event": "capability.selected", "capability": selected.capability_id})
        handler = self.registry.get_handler(selected.capability_id)
        if handler is None:
            raise ConfigError(f"No handler registered for '{selected.capability_id}'")
        value = await handler(request)
        self.budget_guard.record(
            policy.scope,
            policy.scope_id,
            cost,
            provider_id=selected.provider_id,
            credential_id=credential.credential_id if credential else "",
            capability=selected.kind,
            units=policy.estimated_units,
            raw={"capability_id": selected.capability_id},
        )
        if credential:
            self.keypool.report(
                credential,
                used=policy.estimated_units,
                status="ok",
                capability=selected.kind,
                scope=policy.scope,
                scope_id=policy.scope_id,
                cost_usd=0.0,
            )
        return CapabilityResult(status="ok", value=value, capability=selected, cost_usd=cost)

    def resolve(self, capability: str, *, policy: ResolvePolicy | None = None):
        """Select a capability without executing it."""
        policy = policy or ResolvePolicy()
        chain = self.resolve_with_fallback(capability, policy=policy)
        if not chain:
            raise ConfigError(f"No capability registered for '{capability}'")
        selected = chain[0]
        cost = float(selected.cost_per_unit * policy.estimated_units)
        if policy.max_cost_usd is not None and cost > policy.max_cost_usd:
            raise ConfigError(f"Capability estimate ${cost:.4f} exceeds policy max ${policy.max_cost_usd:.4f}")
        return selected

    def resolve_with_fallback(
        self,
        capability: str,
        *,
        policy: ResolvePolicy | None = None,
    ) -> list:
        """Return an ordered fallback chain for a capability."""
        policy = policy or ResolvePolicy()
        from omnicast.runtime.router import RuntimeRouter

        targets = RuntimeRouter(self.registry, db_path=self.db_path).resolve(capability, policy)
        return [target.capability for target in targets]

    async def run_with_fallback(
        self,
        capability: str,
        request: dict,
        *,
        policy: ResolvePolicy | None = None,
        on_progress=None,
    ) -> CapabilityResult:
        """Run handlers in fallback order until one succeeds."""
        policy = policy or ResolvePolicy()
        errors: list[dict] = []
        for candidate in self.resolve_with_fallback(capability, policy=policy):
            handler = self.registry.get_handler(candidate.capability_id)
            if handler is None:
                errors.append({"capability_id": candidate.capability_id, "error": "missing_handler"})
                continue
            try:
                if on_progress:
                    on_progress({"event": "capability.selected", "capability": candidate.capability_id})
                value = await handler(request)
                return CapabilityResult(
                    status="ok",
                    value=value,
                    capability=candidate,
                    cost_usd=float(candidate.cost_per_unit * policy.estimated_units),
                    raw={"fallback_errors": errors},
                )
            except Exception as exc:
                errors.append({"capability_id": candidate.capability_id, "error": str(exc)})
        raise ConfigError(f"All providers failed for '{capability}': {errors}")
