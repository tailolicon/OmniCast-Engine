"""One place to ask for an API key, whichever way the operator supplied it.

Keys could arrive three ways and only two of them worked. `.env` feeds
`Settings`, and the API server also loads it into the environment. But the
Providers screen in the dashboard writes to the `credentials` table in
vault.db — and no runtime code ever read that table, so a key typed into the UI
saved successfully, showed "Đã có key", and then had no effect at all. Reup's
health check even reported `groq: false` while the row sat right there.

Lookup order: process environment, then `Settings`, then the vault.
"""

from __future__ import annotations

import os
from functools import lru_cache

# Vault credentials are keyed by provider; the other two sources by field name.
PROVIDER_ENV_VARS: dict[str, tuple[str, str]] = {
    # provider -> (environment variable, Settings field)
    "groq": ("GROQ_API_KEY", "groq_api_key"),
    "openai": ("OPENAI_API_KEY", "openai_api_key"),
    "deepseek": ("DEEPSEEK_API_KEY", "deepseek_api_key"),
    "anthropic": ("ANTHROPIC_API_KEY", "claude_api_key"),
    "gemini": ("GOOGLE_API_KEY", "google_api_key"),
    "youtube": ("YOUTUBE_API_KEY", "youtube_api_key"),
}


def _from_vault(provider: str) -> str:
    """The newest active secret stored for `provider`, or ''."""
    try:
        from omnicast.config.settings import get_settings
        from omnicast.services.credential_vault import CredentialVault
        from omnicast.storage.products import OUTPUT_DIR

        settings = get_settings()
        vault = CredentialVault(
            db_path=OUTPUT_DIR / "vault.db",
            # The UI encrypts with whatever key was configured at save time;
            # read it the same way, but tolerate its absence.
            encryption_key=os.environ.get("OMNICAST_CREDENTIAL_FERNET_KEY")
            or getattr(settings, "omnicast_credential_fernet_key", "")
            or None,
        )
        rows = [c for c in vault.list_safe(provider) if (c.get("status") or "active") == "active"]
        if not rows:
            return ""
        rows.sort(key=lambda c: str(c.get("updated_at") or c.get("created_at") or ""), reverse=True)
        return vault.get_secret(str(rows[0]["credential_id"])) or ""
    except Exception:
        # A missing Fernet key, a locked database, a provider with no row — none
        # of these should turn into a crash on a key lookup.
        return ""


def resolve_api_key(provider: str, *, override: str | None = None) -> str:
    """API key for `provider`: explicit override, env, Settings, then the vault."""
    if override:
        return override
    env_var, settings_field = PROVIDER_ENV_VARS.get(
        provider, (f"{provider.upper()}_API_KEY", f"{provider}_api_key")
    )
    from_env = os.environ.get(env_var, "").strip()
    if from_env:
        return from_env
    try:
        from omnicast.config.settings import get_settings

        from_settings = str(getattr(get_settings(), settings_field, "") or "").strip()
        if from_settings:
            return from_settings
    except Exception:
        pass
    return _from_vault(provider).strip()


def has_api_key(provider: str) -> bool:
    return bool(resolve_api_key(provider))


@lru_cache(maxsize=None)
def _cached(provider: str) -> str:
    return resolve_api_key(provider)
