"""Credential vault backed by SQLite, with optional Fernet encryption."""

from __future__ import annotations

import base64
import hashlib
from datetime import datetime, timezone
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from omnicast.shared.errors import ConfigError
from omnicast.vault import db as vault_db
from omnicast.vault.models import CredentialRecord


class CredentialVault:
    """Store provider credentials without leaking secret values to logs/API."""

    def __init__(self, db_path: Path | None = None, encryption_key: str | None = None) -> None:
        self.db_path = db_path
        self._fernet = Fernet(encryption_key.encode()) if encryption_key else None
        vault_db.init_db(db_path)

    def store_secret(
        self,
        *,
        provider: str,
        account_id: str,
        secret: str,
        label: str = "",
        scopes: list[str] | None = None,
        priority: int = 100,
    ) -> CredentialRecord:
        now = datetime.now(timezone.utc).isoformat()
        credential_id = self._credential_id(provider, account_id)
        secret_ref = self._encode_secret(secret)
        record = CredentialRecord(
            credential_id=credential_id,
            provider=provider,
            account_id=account_id,
            label=label or f"{provider}:{account_id}",
            secret_ref=secret_ref,
            scopes=scopes or [],
            priority=priority,
            created_at=now,
            updated_at=now,
        )
        existing = vault_db.get_credential(credential_id, self.db_path)
        if existing:
            record.created_at = existing.created_at
        vault_db.upsert_credential(record, self.db_path)
        return record

    def get_secret(self, credential_id: str) -> str:
        record = vault_db.get_credential(credential_id, self.db_path)
        if not record:
            raise ConfigError(f"Credential not found: {credential_id}")
        return self._decode_secret(record.secret_ref)

    def list_safe(self, provider: str | None = None) -> list[dict]:
        return [
            {
                "credential_id": c.credential_id,
                "provider": c.provider,
                "account_id": c.account_id,
                "label": c.label,
                "scopes": c.scopes,
                "status": c.status,
                "priority": c.priority,
                "cooldown_until": c.cooldown_until,
                "last_used_at": c.last_used_at,
                "created_at": c.created_at,
                "updated_at": c.updated_at,
                "encrypted": c.secret_ref.startswith("fernet:"),
            }
            for c in vault_db.list_credentials(provider, self.db_path)
        ]

    def _encode_secret(self, secret: str) -> str:
        raw = secret.encode("utf-8")
        if self._fernet:
            return "fernet:" + self._fernet.encrypt(raw).decode("utf-8")
        return "local:" + base64.urlsafe_b64encode(raw).decode("ascii")

    def _decode_secret(self, secret_ref: str) -> str:
        if secret_ref.startswith("fernet:"):
            if not self._fernet:
                raise ConfigError("Credential is encrypted but no Fernet key is configured")
            try:
                return self._fernet.decrypt(secret_ref.removeprefix("fernet:").encode()).decode("utf-8")
            except InvalidToken as exc:
                raise ConfigError("Credential decrypt failed") from exc
        if secret_ref.startswith("local:"):
            return base64.urlsafe_b64decode(secret_ref.removeprefix("local:").encode()).decode("utf-8")
        raise ConfigError("Unknown credential secret format")

    @staticmethod
    def _credential_id(provider: str, account_id: str) -> str:
        digest = hashlib.sha256(f"{provider}:{account_id}".encode("utf-8")).hexdigest()[:16]
        return f"{provider}_{digest}"
