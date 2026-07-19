# TASK_A: Upload Models + OAuth2 Manager

## Model: sonnet | Dependencies: Phase 1-4 complete

Add `UploadPipelineError(OmnicastError)` to `shared/errors.py`. Create `src/omnicast/upload/` package.

## Interface

### src/omnicast/upload/models.py

```python
"""Pydantic models for Upload Pipeline. All frozen, inherit OmnicastSchema."""

from __future__ import annotations
from datetime import datetime, timezone
from enum import StrEnum
from pydantic import Field
from omnicast.models.schemas import OmnicastSchema


class UploadStatus(StrEnum):
    PENDING = "pending"
    COMPLIANCE_CHECK = "compliance_check"
    SCHEDULED = "scheduled"
    UPLOADING = "uploading"
    PROCESSING = "processing"  # YouTube processing after upload
    PUBLISHED = "published"
    FAILED = "failed"
    REJECTED = "rejected"  # compliance gate failed


class ComplianceResult(OmnicastSchema):
    """Result from compliance gate."""
    passed: bool = False
    checks: dict[str, bool] = Field(default_factory=dict)
    # keys: ai_disclosure, no_misleading, no_copyright_music,
    #        ftc_disclosure, advertiser_friendly, not_children, cross_channel_unique
    violations: list[str] = Field(default_factory=list)
    checked_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def violation_count(self) -> int:
        return len(self.violations)


class UploadMetadata(OmnicastSchema):
    """Metadata for YouTube video upload."""
    title: str
    description: str
    tags: list[str] = Field(default_factory=list)
    category_id: str = "22"  # People & Blogs default
    language: str = "en"
    ai_disclosure: bool = True
    privacy_status: str = "private"  # private → scheduled → public
    publish_at: datetime | None = None
    made_for_kids: bool = False


class UploadRequest(OmnicastSchema):
    """Full upload request."""
    video_id: str
    channel_id: str
    video_path: str
    thumbnail_paths: list[str] = Field(default_factory=list)
    metadata: UploadMetadata
    compliance: ComplianceResult | None = None


class UploadResult(OmnicastSchema):
    """Result from YouTube upload."""
    youtube_video_id: str = ""
    channel_id: str = ""
    status: UploadStatus = UploadStatus.PUBLISHED
    published_at: datetime | None = None
    url: str = ""
    thumbnail_set: bool = False
    error: str | None = None


class ScheduleSlot(OmnicastSchema):
    """A scheduled upload time slot."""
    channel_id: str
    scheduled_at: datetime
    market: str = "US"
    is_prime_time: bool = True


class TokenStatus(StrEnum):
    VALID = "valid"
    EXPIRING_SOON = "expiring_soon"  # < 1 hour
    EXPIRED = "expired"
    REVOKED = "revoked"


class TokenHealth(OmnicastSchema):
    """OAuth2 token health status."""
    channel_id: str
    status: TokenStatus = TokenStatus.VALID
    expires_at: datetime | None = None
    scopes: list[str] = Field(default_factory=list)
    last_check: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    error: str | None = None


class UploadPipelineState(OmnicastSchema):
    """Tracks upload pipeline progress for one video."""
    video_id: str
    channel_id: str
    compliance: UploadStatus = UploadStatus.PENDING
    scheduling: UploadStatus = UploadStatus.PENDING
    upload: UploadStatus = UploadStatus.PENDING
    thumbnail: UploadStatus = UploadStatus.PENDING

    @property
    def all_done(self) -> bool:
        return all(
            s in (UploadStatus.PUBLISHED, UploadStatus.SCHEDULED)
            for s in [self.compliance, self.scheduling, self.upload, self.thumbnail]
        )

    @property
    def has_failure(self) -> bool:
        return any(
            s in (UploadStatus.FAILED, UploadStatus.REJECTED)
            for s in [self.compliance, self.scheduling, self.upload, self.thumbnail]
        )
```

### src/omnicast/upload/oauth.py

```python
"""OAuth2 token manager for YouTube Data API v3. Encrypted storage, proactive refresh."""

from __future__ import annotations
from datetime import datetime, timezone, timedelta
from pathlib import Path
import json
import structlog
from omnicast.upload.models import TokenHealth, TokenStatus
from omnicast.shared.errors import UploadPipelineError

logger = structlog.get_logger()


class OAuth2Manager:
    """Manage OAuth2 tokens per channel. Encrypted storage on NAS."""

    def __init__(self, token_dir: str, encryption_key: str | None = None) -> None:
        self.token_dir = Path(token_dir)
        self.encryption_key = encryption_key

    async def get_credentials(self, channel_id: str):
        """Load + decrypt OAuth2 credentials for channel.
        Auto-refresh if expiring within 1 hour.
        Raise UploadPipelineError if token expired/revoked.
        Returns google.oauth2.credentials.Credentials object.
        """
        ...

    async def store_token(self, channel_id: str, token_data: dict) -> None:
        """Encrypt and store token JSON to NAS/{token_dir}/{channel_id}.json.
        NEVER log token values — log channel_id only."""
        ...

    async def refresh_token(self, channel_id: str) -> None:
        """Force refresh OAuth2 token. Update stored encrypted file."""
        ...

    async def check_health(self, channel_id: str) -> TokenHealth:
        """Check token validity. Returns TokenHealth with status.
        Steps:
        1. Load credentials
        2. Check expiry time
        3. Verify scopes include youtube.upload
        4. Return health status
        """
        ...

    async def check_all_channels(self, channel_ids: list[str]) -> list[TokenHealth]:
        """Batch health check. Run every 6h."""
        results = []
        for cid in channel_ids:
            try:
                results.append(await self.check_health(cid))
            except Exception as exc:
                results.append(TokenHealth(
                    channel_id=cid, status=TokenStatus.REVOKED, error=str(exc)
                ))
        return results

    def generate_auth_url(self, channel_id: str) -> str:
        """Generate OAuth consent URL for re-authorization flow."""
        ...

    def _encrypt(self, data: bytes) -> bytes:
        """Encrypt token data. Uses Fernet symmetric encryption."""
        ...

    def _decrypt(self, data: bytes) -> bytes:
        """Decrypt token data."""
        ...
```

### src/omnicast/upload/__init__.py

```python
"""Upload Pipeline package."""
```

## DO NOT

- NEVER log token values, refresh tokens, or access tokens
- No actual Google API calls in tests — mock everything
- No YouTube upload logic — that's TASK_D
- No compliance checks — that's TASK_B
- Token encryption must use `cryptography.fernet`, not custom crypto
- store_token must create parent dirs if not exist

## Tests

### tests/unit/test_upload_models.py

```python
import pytest
from datetime import datetime, timezone
from pydantic import ValidationError
from omnicast.upload.models import (
    UploadStatus, TokenStatus,
    ComplianceResult, UploadMetadata, UploadRequest, UploadResult,
    ScheduleSlot, TokenHealth, UploadPipelineState,
)


class TestUploadStatus:
    def test_values(self):
        assert UploadStatus.PENDING == "pending"
        assert UploadStatus.REJECTED == "rejected"
        assert UploadStatus.PUBLISHED == "published"


class TestComplianceResult:
    def test_passed(self):
        c = ComplianceResult(passed=True, checks={"ai_disclosure": True, "no_copyright_music": True})
        assert c.passed
        assert c.violation_count == 0

    def test_failed(self):
        c = ComplianceResult(passed=False, violations=["Missing AI disclosure", "Copyright music detected"])
        assert not c.passed
        assert c.violation_count == 2

    def test_frozen(self):
        c = ComplianceResult()
        with pytest.raises(ValidationError):
            c.passed = True


class TestUploadMetadata:
    def test_defaults(self):
        m = UploadMetadata(title="Top 10 Tips", description="A great video")
        assert m.category_id == "22"
        assert m.ai_disclosure is True
        assert m.privacy_status == "private"
        assert m.made_for_kids is False

    def test_with_schedule(self):
        dt = datetime(2025, 6, 1, 14, 0, tzinfo=timezone.utc)
        m = UploadMetadata(title="X", description="Y", publish_at=dt)
        assert m.publish_at is not None


class TestUploadRequest:
    def test_create(self):
        meta = UploadMetadata(title="X", description="Y")
        r = UploadRequest(video_id="v1", channel_id="ch1", video_path="/tmp/final.mp4", metadata=meta)
        assert r.video_path == "/tmp/final.mp4"
        assert r.compliance is None
        assert r.thumbnail_paths == []


class TestUploadResult:
    def test_success(self):
        r = UploadResult(youtube_video_id="yt_abc123", channel_id="ch1", url="https://youtu.be/abc123")
        assert r.status == UploadStatus.PUBLISHED

    def test_failure(self):
        r = UploadResult(status=UploadStatus.FAILED, error="Quota exceeded")
        assert r.error is not None


class TestScheduleSlot:
    def test_create(self):
        dt = datetime(2025, 6, 1, 14, 0, tzinfo=timezone.utc)
        s = ScheduleSlot(channel_id="ch1", scheduled_at=dt, market="US")
        assert s.is_prime_time


class TestTokenHealth:
    def test_valid(self):
        t = TokenHealth(channel_id="ch1", status=TokenStatus.VALID, scopes=["youtube.upload"])
        assert t.status == TokenStatus.VALID

    def test_expired(self):
        t = TokenHealth(channel_id="ch1", status=TokenStatus.EXPIRED, error="Token revoked by user")
        assert t.error is not None


class TestUploadPipelineState:
    def test_initial(self):
        s = UploadPipelineState(video_id="v1", channel_id="ch1")
        assert not s.all_done
        assert not s.has_failure

    def test_all_done(self):
        s = UploadPipelineState(
            video_id="v1", channel_id="ch1",
            compliance=UploadStatus.PUBLISHED,
            scheduling=UploadStatus.SCHEDULED,
            upload=UploadStatus.PUBLISHED,
            thumbnail=UploadStatus.PUBLISHED,
        )
        assert s.all_done

    def test_rejected(self):
        s = UploadPipelineState(
            video_id="v1", channel_id="ch1",
            compliance=UploadStatus.REJECTED,
        )
        assert s.has_failure

    def test_frozen(self):
        s = UploadPipelineState(video_id="v1", channel_id="ch1")
        with pytest.raises(ValidationError):
            s.video_id = "v2"
```

### tests/unit/test_oauth.py

```python
import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from omnicast.upload.oauth import OAuth2Manager
from omnicast.upload.models import TokenHealth, TokenStatus
from omnicast.shared.errors import UploadPipelineError


@pytest.fixture
def oauth(tmp_path):
    return OAuth2Manager(token_dir=str(tmp_path), encryption_key="test-key-32-bytes-long-enough!!")


class TestOAuth2ManagerHealth:
    @pytest.mark.asyncio
    async def test_check_health_valid(self, oauth):
        with patch.object(oauth, "get_credentials", new_callable=AsyncMock) as mock_creds:
            mock_cred = MagicMock()
            mock_cred.valid = True
            mock_cred.expired = False
            mock_cred.scopes = {"https://www.googleapis.com/auth/youtube.upload"}
            mock_cred.expiry = None
            mock_creds.return_value = mock_cred
            health = await oauth.check_health("ch1")
            assert health.status == TokenStatus.VALID

    @pytest.mark.asyncio
    async def test_check_health_expired(self, oauth):
        with patch.object(oauth, "get_credentials", new_callable=AsyncMock,
                           side_effect=UploadPipelineError("Token expired")):
            health = await oauth.check_health("ch1")
            assert health.status in (TokenStatus.EXPIRED, TokenStatus.REVOKED)

    @pytest.mark.asyncio
    async def test_check_all_channels(self, oauth):
        valid = TokenHealth(channel_id="ch1", status=TokenStatus.VALID)
        expired = TokenHealth(channel_id="ch2", status=TokenStatus.EXPIRED, error="expired")
        with patch.object(oauth, "check_health", new_callable=AsyncMock, side_effect=[valid, expired]):
            results = await oauth.check_all_channels(["ch1", "ch2"])
            assert len(results) == 2
            assert results[0].status == TokenStatus.VALID
            assert results[1].status == TokenStatus.EXPIRED

    @pytest.mark.asyncio
    async def test_check_all_handles_exceptions(self, oauth):
        with patch.object(oauth, "check_health", new_callable=AsyncMock,
                           side_effect=RuntimeError("network")):
            results = await oauth.check_all_channels(["ch1"])
            assert len(results) == 1
            assert results[0].status == TokenStatus.REVOKED


class TestOAuth2ManagerStorage:
    @pytest.mark.asyncio
    async def test_store_and_load(self, oauth):
        # Test encrypt/decrypt roundtrip
        if oauth.encryption_key:
            data = b'{"access_token": "test", "refresh_token": "test2"}'
            encrypted = oauth._encrypt(data)
            assert encrypted != data
            decrypted = oauth._decrypt(encrypted)
            assert decrypted == data

    def test_generate_auth_url(self, oauth):
        url = oauth.generate_auth_url("ch1")
        assert isinstance(url, str)
        assert "oauth" in url.lower() or "auth" in url.lower() or url.startswith("http")


class TestOAuth2Manager:
    def test_token_dir_set(self, oauth, tmp_path):
        assert str(oauth.token_dir) == str(tmp_path)

    @pytest.mark.asyncio
    async def test_get_credentials_missing_token(self, oauth):
        with pytest.raises(UploadPipelineError):
            await oauth.get_credentials("nonexistent_channel")
```
