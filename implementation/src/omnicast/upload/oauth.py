"""OAuth2 token manager for YouTube Data API v3.

Per-channel refresh tokens stored as JSON under token_dir/<channel_id>.json
(optionally Fernet-encrypted). Credentials auto-refresh when expired. The
one-time consent flow lives in scripts/youtube_authorize.py (it writes the
token file this manager reads).
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

import structlog

from omnicast.shared.errors import UploadPipelineError
from omnicast.upload.models import TokenHealth, TokenStatus

logger = structlog.get_logger()

# Upload scope only — least privilege for an auto-publisher.
SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]

# Analytics read scopes — analytics/crawler.py needs these to pull watch time /
# retention / subscriber / revenue reports. Tokens authorized before these were
# added lack them: re-run scripts/youtube_authorize.py --analytics to re-consent.
ANALYTICS_SCOPES = [
    "https://www.googleapis.com/auth/yt-analytics.readonly",
    "https://www.googleapis.com/auth/yt-analytics-monetary.readonly",
]


class OAuth2Manager:
    """Manage OAuth2 tokens per channel (file-backed, optional encryption)."""

    def __init__(self, token_dir: str, encryption_key: str | None = None) -> None:
        self.token_dir = Path(token_dir)
        self.encryption_key = encryption_key or None

    def _token_path(self, channel_id: str) -> Path:
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in channel_id)
        return self.token_dir / f"{safe}.json"

    def _read_token(self, channel_id: str) -> dict | None:
        path = self._token_path(channel_id)
        if not path.exists():
            return None
        raw = path.read_bytes()
        if self.encryption_key:
            raw = self._decrypt(raw)
        return json.loads(raw.decode("utf-8"))

    def _write_token(self, channel_id: str, info: dict) -> None:
        self.token_dir.mkdir(parents=True, exist_ok=True)
        data = json.dumps(info, ensure_ascii=False).encode("utf-8")
        if self.encryption_key:
            data = self._encrypt(data)
        self._token_path(channel_id).write_bytes(data)

    def generate_auth_url(
        self,
        channel_id: str,
        *,
        client_id: str | None = None,
        redirect_uri: str = "urn:ietf:wg:oauth:2.0:oob",
    ) -> str:
        """Build a Google OAuth consent URL for manual YouTube authorization.

        The production path is still scripts/youtube_authorize.py, which runs an
        InstalledAppFlow and stores the resulting refresh token. This helper is
        useful for diagnostics/UI surfaces that need to show the consent target
        without reading or logging client-secret files.
        """
        params = {
            "client_id": client_id or os.getenv("OMNICAST_YOUTUBE_OAUTH_CLIENT_ID", "CLIENT_ID_REQUIRED"),
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": " ".join(SCOPES),
            "access_type": "offline",
            "prompt": "consent",
            "state": channel_id,
        }
        return "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params)

    def stored_scopes(self, channel_id: str) -> list[str]:
        """Scopes the stored token was actually granted ([] if no token)."""
        info = self._read_token(channel_id)
        if not info:
            return []
        raw = info.get("scopes") or info.get("scope") or []
        return raw.split() if isinstance(raw, str) else list(raw)

    async def get_credentials(self, channel_id: str, scopes: list[str] | None = None):
        """Load credentials for a channel and refresh if expired. Returns a
        google.oauth2.credentials.Credentials. Raises UploadPipelineError if no
        token is stored or the refresh fails (revoked/expired refresh token).

        `scopes` narrows/overrides the requested scopes (default: upload-only
        SCOPES). Requesting a scope the stored refresh token was never granted
        fails at refresh time — callers should check `stored_scopes()` first.
        """
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request

        info = self._read_token(channel_id)
        if not info:
            raise UploadPipelineError(
                f"No OAuth token for channel '{channel_id}'. Run "
                f"scripts/youtube_authorize.py --channel {channel_id} first."
            )
        creds = Credentials.from_authorized_user_info(info, scopes or SCOPES)
        if not creds.valid:
            if creds.expired and creds.refresh_token:
                try:
                    creds.refresh(Request())
                except Exception as exc:
                    raise UploadPipelineError(
                        f"Token refresh failed for '{channel_id}': {exc}"
                    ) from exc
                self._write_token(channel_id, json.loads(creds.to_json()))
            else:
                raise UploadPipelineError(
                    f"Token for '{channel_id}' invalid and not refreshable "
                    "(re-authorize required)."
                )
        return creds

    async def store_token(self, channel_id: str, token_data: dict) -> None:
        """Persist an authorized-user token dict. Never logs token values."""
        self._write_token(channel_id, token_data)
        logger.info("Token stored", channel_id=channel_id)

    async def refresh_token(self, channel_id: str) -> None:
        """Force a refresh and re-store. No-op return."""
        await self.get_credentials(channel_id)

    async def check_health(self, channel_id: str) -> TokenHealth:
        """Load + refresh + report token health (scopes, expiry)."""
        try:
            creds = await self.get_credentials(channel_id)
            expiry = getattr(creds, "expiry", None)
            exp = None
            if expiry:
                exp = expiry.replace(tzinfo=timezone.utc) if expiry.tzinfo is None else expiry
            status = TokenStatus.VALID
            if exp:
                secs = (exp - datetime.now(timezone.utc)).total_seconds()
                if secs < 3600:
                    status = TokenStatus.EXPIRING_SOON
            return TokenHealth(
                channel_id=channel_id, status=status, expires_at=exp,
                scopes=list(getattr(creds, "scopes", None) or SCOPES),
            )
        except UploadPipelineError as exc:
            return TokenHealth(
                channel_id=channel_id, status=TokenStatus.EXPIRED, error=str(exc)
            )

    async def check_all_channels(self, channel_ids: list[str]) -> list[TokenHealth]:
        results = []
        for cid in channel_ids:
            try:
                results.append(await self.check_health(cid))
            except Exception as exc:
                results.append(TokenHealth(
                    channel_id=cid, status=TokenStatus.REVOKED, error=str(exc)
                ))
        return results

    def has_token(self, channel_id: str) -> bool:
        return self._token_path(channel_id).exists()

    def _encrypt(self, data: bytes) -> bytes:
        if self.encryption_key:
            from cryptography.fernet import Fernet
            return Fernet(self.encryption_key.encode()).encrypt(data)
        return data

    def _decrypt(self, data: bytes) -> bytes:
        if self.encryption_key:
            from cryptography.fernet import Fernet
            return Fernet(self.encryption_key.encode()).decrypt(data)
        return data
