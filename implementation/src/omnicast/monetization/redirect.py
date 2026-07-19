"""Trackable affiliate redirect service."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path

from omnicast.shared.errors import NotFoundError
from omnicast.vault import db as vault_db
from omnicast.vault.models import ClickRecord


class RedirectService:
    """Resolve placement ids into destination URLs while recording clicks."""

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path
        vault_db.init_db(db_path)

    def track_click(
        self,
        placement_id: str,
        *,
        referrer: str = "",
        user_agent: str = "",
        raw: dict | None = None,
    ) -> str:
        placement = vault_db.get_placement(placement_id, self.db_path)
        if not placement:
            raise NotFoundError(f"Placement not found: {placement_id}")
        now = datetime.now(timezone.utc).isoformat()
        click_id = hashlib.sha256(
            f"{placement_id}:{now}:{referrer}:{user_agent}".encode()
        ).hexdigest()[:24]
        vault_db.insert_click(
            ClickRecord(
                click_id=click_id,
                placement_id=placement_id,
                occurred_at=now,
                referrer=referrer,
                user_agent=user_agent,
                raw=raw or {},
            ),
            self.db_path,
        )
        return placement.destination_url
