"""Cloudflare Access authentication for dashboard."""

from __future__ import annotations
import structlog
from typing import Any

logger = structlog.get_logger()


class CloudflareAuth:
    """Validate Cloudflare Access JWT from CF-Access-Jwt-Assertion header."""

    def __init__(self, team_domain: str, audience: str) -> None:
        self.team_domain = team_domain
        self.audience = audience

    def validate_token(self, token: str) -> dict[str, Any] | None:
        """Validate Cloudflare Access JWT token.
        Returns payload dict if valid, None otherwise.
        """
        # Placeholder for actual JWT validation
        # In production: use pyjwt to validate signature and claims
        if not token:
            return None
        # Mock validation - always return None for placeholder
        return None

    def get_user_email(self, token: str) -> str | None:
        """Extract user email from validated token."""
        payload = self.validate_token(token)
        if payload and "email" in payload:
            return payload["email"]
        return None


def require_auth() -> str | None:
    """Streamlit auth gate. Returns email or renders login error.
    In production: check CF-Access-Jwt-Assertion header from request context.
    DEV MODE: OMNICAST_DEV_AUTH=1 bypasses Cloudflare check for local testing.
    """
    import os
    if os.getenv("OMNICAST_DEV_AUTH", "0") == "1":
        return os.getenv("OMNICAST_DEV_EMAIL", "dev@localhost")
    # In production: get token from st.context.headers, validate, return email
    return None
