"""Unified capability registry over existing provider registries."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from omnicast.capabilities.types import Capability, CapabilityHandler
from omnicast.llm.registry import list_llm_providers
from omnicast.media.providers.registry import list_providers as list_media_providers
from omnicast.vault import db as vault_db
from omnicast.vault.models import ModelRecord, ProviderRecord


class CapabilityRegistry:
    """Registers capability metadata and optional execution handlers."""

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path
        self._handlers: dict[str, CapabilityHandler] = {}
        vault_db.init_db(db_path)

    def register(self, capability: Capability, handler: CapabilityHandler | None = None) -> None:
        now = datetime.now(timezone.utc).isoformat()
        vault_db.upsert_provider(
            ProviderRecord(
                provider_id=capability.provider_id,
                name=capability.metadata.get("name", capability.provider_id),
                capability=capability.kind,
                priority=int(capability.metadata.get("priority", 100)),
                metadata=capability.metadata,
                created_at=now,
                updated_at=now,
            ),
            self.db_path,
        )
        vault_db.upsert_model(
            ModelRecord(
                model_id=capability.model_id or capability.provider_id,
                provider_id=capability.provider_id,
                capability=capability.kind,
                runtime=capability.runtime,
                cost_per_unit=capability.cost_per_unit,
                min_vram_mb=capability.min_vram_mb,
                fallback=capability.fallback,
                metadata=capability.metadata,
                created_at=now,
                updated_at=now,
            ),
            self.db_path,
        )
        if handler:
            self._handlers[capability.capability_id] = handler
            self._handlers[f"{capability.kind}:{capability.provider_id}:{capability.model_id or capability.provider_id}"] = handler

    def get_handler(self, capability_id: str) -> CapabilityHandler | None:
        return self._handlers.get(capability_id)

    def list_capabilities(self, kind: str | None = None) -> list[Capability]:
        persisted = [
            Capability(
                capability_id=f"{m.capability}:{m.provider_id}:{m.model_id}",
                kind=m.capability,
                provider_id=m.provider_id,
                model_id=m.model_id,
                runtime=m.runtime,
                cost_per_unit=m.cost_per_unit,
                min_vram_mb=m.min_vram_mb,
                fallback=m.fallback,
                metadata=m.metadata,
            )
            for m in vault_db.list_models(kind, path=self.db_path)
            if m.status == "active"
        ]
        discovered = [
            c for c in self.discover_existing() if kind is None or c.kind == kind
        ]
        if persisted:
            persisted_ids = {c.capability_id for c in persisted}
            return persisted + [c for c in discovered if c.capability_id not in persisted_ids]
        return discovered

    def discover_existing(self) -> list[Capability]:
        capabilities: list[Capability] = []
        capabilities.append(Capability(
            capability_id="text:anthropic",
            kind="text",
            provider_id="anthropic",
            model_id="anthropic",
            runtime="remote",
            metadata={"source": "llm.client.inline"},
        ))
        for provider_id in list_llm_providers():
            capabilities.append(Capability(
                capability_id=f"text:{provider_id}",
                kind="text",
                provider_id=provider_id,
                model_id=provider_id,
                # chatgpt_web is a loopback relay into a local browser — its
                # availability is a property of this machine, not a remote API.
                runtime="local" if provider_id in ("ollama", "chatgpt_web") else "remote",
                metadata={"source": "llm.registry"},
            ))
        for provider in list_media_providers():
            capabilities.append(Capability(
                capability_id=f"{provider.get('category')}:{provider.get('id')}",
                kind=str(provider.get("category") or ""),
                provider_id=str(provider.get("id") or ""),
                model_id=str(provider.get("id") or ""),
                runtime=str(provider.get("runtime") or ("browser" if provider.get("id") == "flow" else "remote")),
                cost_per_unit=float(provider.get("cost_per_unit") or 0.0),
                min_vram_mb=int(provider.get("min_vram_mb") or 0),
                metadata={**provider, "source": "media.providers.registry"},
            ))
        return capabilities
