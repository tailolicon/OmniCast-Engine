# TASK_B: Streamlit App Shell + Auth

## Model: sonnet | Dependencies: TASK_A complete

Streamlit multi-tab app entry point + Cloudflare Access auth middleware.

## Interface

### src/omnicast/dashboard/auth.py

```python
class CloudflareAuth:
    """Validate Cloudflare Access JWT from CF-Access-Jwt-Assertion header."""
    def __init__(self, team_domain: str, audience: str)
    def validate_token(self, token: str) -> dict | None
    def get_user_email(self, token: str) -> str | None

def require_auth() -> str | None:
    """Streamlit auth gate. Returns email or renders login error."""
```

### src/omnicast/dashboard/app.py

```python
"""Streamlit entry point. 7 tabs, auto-refresh 30s."""
# st.set_page_config → require_auth → tab selector → render tab
# Tabs: Home, Production, Channels, Infrastructure, DLQ, Tokens, Compliance
```

## DO NOT

- No business logic in app.py — delegate to data_service
- Auth must fail-closed (no token = no access)
- Auto-refresh interval configurable via settings

## Tests

### tests/unit/test_dashboard_auth.py

```python
import pytest
from unittest.mock import patch, MagicMock
from omnicast.dashboard.auth import CloudflareAuth


@pytest.fixture
def auth():
    return CloudflareAuth(
        team_domain="myteam.cloudflareaccess.com",
        audience="test-audience-id",
    )


class TestCloudflareAuth:
    def test_valid_token(self, auth):
        mock_payload = {"email": "user@example.com", "exp": 9999999999}
        with patch.object(auth, "validate_token", return_value=mock_payload):
            result = auth.validate_token("valid.jwt.token")
            assert result is not None
            assert result["email"] == "user@example.com"

    def test_invalid_token(self, auth):
        with patch.object(auth, "validate_token", return_value=None):
            result = auth.validate_token("invalid.token")
            assert result is None

    def test_get_user_email(self, auth):
        mock_payload = {"email": "admin@example.com"}
        with patch.object(auth, "validate_token", return_value=mock_payload):
            email = auth.get_user_email("valid.jwt.token")
            assert email == "admin@example.com"

    def test_get_email_invalid(self, auth):
        with patch.object(auth, "validate_token", return_value=None):
            email = auth.get_user_email("bad.token")
            assert email is None

    def test_fail_closed(self, auth):
        result = auth.validate_token("")
        assert result is None
```
