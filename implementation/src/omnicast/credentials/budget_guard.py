"""Vault-backed budget guard for global, campaign, and channel scopes."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path

from omnicast.shared.errors import QuotaExceeded
from omnicast.vault import db as vault_db
from omnicast.vault.models import BudgetRecord, UsageRecord


class BudgetGuard:
    """Enforce persistent spend limits stored in vault.db."""

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path
        vault_db.init_db(db_path)

    def set_budget(
        self,
        *,
        scope: str,
        scope_id: str,
        limit_usd: float,
        reset_at: str | None = None,
    ) -> BudgetRecord:
        now = datetime.now(timezone.utc).isoformat()
        existing = vault_db.get_budget(scope, scope_id, self.db_path)
        record = BudgetRecord(
            budget_id=existing.budget_id if existing else f"{scope}:{scope_id}",
            scope=scope,
            scope_id=scope_id,
            limit_usd=limit_usd,
            spent_usd=existing.spent_usd if existing else 0.0,
            reset_at=reset_at,
            created_at=existing.created_at if existing else now,
            updated_at=now,
        )
        vault_db.upsert_budget(record, self.db_path)
        return record

    def check(self, scope: str, scope_id: str, usd: float) -> None:
        budget = vault_db.get_budget(scope, scope_id, self.db_path)
        if not budget:
            return
        if budget.spent_usd + usd > budget.limit_usd:
            raise QuotaExceeded(
                f"Budget exceeded for {scope}:{scope_id}",
                {
                    "scope": scope,
                    "scope_id": scope_id,
                    "limit_usd": budget.limit_usd,
                    "spent_usd": budget.spent_usd,
                    "attempt_usd": usd,
                },
            )

    def record(
        self,
        scope: str,
        scope_id: str,
        usd: float,
        *,
        provider_id: str = "",
        credential_id: str = "",
        capability: str = "",
        units: float = 0.0,
        status: str = "ok",
        raw: dict | None = None,
    ) -> None:
        self.check(scope, scope_id, usd)
        vault_db.add_budget_spend(scope, scope_id, usd, self.db_path)
        now = datetime.now(timezone.utc).isoformat()
        usage_id = hashlib.sha256(
            f"{scope}:{scope_id}:{provider_id}:{now}:{usd}".encode()
        ).hexdigest()[:24]
        vault_db.insert_usage(
            UsageRecord(
                usage_id=usage_id,
                provider_id=provider_id,
                credential_id=credential_id,
                capability=capability,
                scope=scope,
                scope_id=scope_id,
                units=units,
                cost_usd=usd,
                status=status,
                created_at=now,
                raw=raw or {},
            ),
            self.db_path,
        )
