"""Provider credential pool with cooldown reporting."""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

from omnicast.shared.errors import QuotaExhausted
from omnicast.vault import db as vault_db
from omnicast.vault.models import CredentialRecord, UsageRecord


class KeyPool:
    """Acquire active credentials and cool down keys after provider failures."""

    def __init__(self, db_path: Path | None = None, cooldown_seconds: int = 900) -> None:
        self.db_path = db_path
        self.cooldown_seconds = cooldown_seconds
        vault_db.init_db(db_path)

    def acquire(self, provider_id: str, need: int = 1) -> CredentialRecord:
        now = datetime.now(timezone.utc)
        candidates = []
        for cred in vault_db.list_credentials(provider_id, self.db_path):
            if cred.status != "active":
                continue
            if cred.cooldown_until:
                try:
                    if datetime.fromisoformat(cred.cooldown_until) > now:
                        continue
                except ValueError:
                    continue
            candidates.append(cred)
        if not candidates:
            raise QuotaExhausted(f"No active credential available for provider '{provider_id}'")

        selected = sorted(candidates, key=lambda c: (c.priority, c.last_used_at or ""))[0]
        selected.last_used_at = now.isoformat()
        selected.updated_at = selected.last_used_at
        vault_db.upsert_credential(selected, self.db_path)
        return selected

    def report(
        self,
        credential: CredentialRecord,
        *,
        used: float = 0.0,
        status: str = "ok",
        capability: str = "",
        scope: str = "global",
        scope_id: str = "default",
        cost_usd: float = 0.0,
        raw: dict | None = None,
    ) -> None:
        now = datetime.now(timezone.utc)
        if status in {"429", "blocked", "error"}:
            credential.cooldown_until = (
                now + timedelta(seconds=self.cooldown_seconds)
            ).isoformat()
            credential.status = "blocked" if status == "blocked" else "active"
        credential.last_used_at = now.isoformat()
        credential.updated_at = credential.last_used_at
        vault_db.upsert_credential(credential, self.db_path)
        if used or cost_usd or status != "ok":
            usage_id = hashlib.sha256(
                f"{credential.credential_id}:{now.isoformat()}:{status}:{used}".encode()
            ).hexdigest()[:24]
            vault_db.insert_usage(
                UsageRecord(
                    usage_id=usage_id,
                    provider_id=credential.provider,
                    credential_id=credential.credential_id,
                    capability=capability,
                    scope=scope,
                    scope_id=scope_id,
                    units=used,
                    cost_usd=cost_usd,
                    status=status,
                    created_at=now.isoformat(),
                    raw=raw or {},
                ),
                self.db_path,
            )
