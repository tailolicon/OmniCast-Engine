"""Single entry point for building an LLM client via the CapabilityBus (WO-2).

Domain code should ask for a text-capable client here instead of `LLMClient(provider=...)`
directly, so the RuntimeRouter (CapabilityBus.resolve for the `text` capability) can pick
provider/model per policy + fallback. Falls back to a direct LLMClient if the bus can't
resolve, so existing behavior is preserved when no capability config is present.
"""

from __future__ import annotations

from pathlib import Path


def create_llm(
    default_provider: str,
    model: str | None = None,
    db_path: Path | None = None,
    cli_effort: str | None = None,
    role: str = "",
):
    """Resolve the `text` capability, then build the existing LLMClient as adapter.

    Mirrors `pipeline.steps._llm_client` (the one call site already on the bus) so all
    call sites share one policy. `default_provider`/`model` are the caller's preference;
    the bus may override the provider (and model, when the resolved provider differs).
    """
    from omnicast.llm.client import LLMClient
    try:
        from omnicast.capabilities import CapabilityBus, ResolvePolicy

        cap = CapabilityBus(db_path=db_path).resolve(
            "text",
            policy=ResolvePolicy(prefer_provider_id=default_provider),
        )
        provider = cap.provider_id or default_provider
        selected_model = model
        if provider != default_provider and cap.model_id and cap.model_id != provider:
            selected_model = cap.model_id
        return LLMClient(
            provider=provider, model=selected_model,
            cli_effort=cli_effort, role=role,
        )
    except Exception:
        return LLMClient(
            provider=default_provider, model=model,
            cli_effort=cli_effort, role=role,
        )
