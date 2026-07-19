# TASK_D: YouTube API Uploader

## Model: sonnet | Dependencies: TASK_A complete

Upload videos via YouTube Data API v3. videos.insert + thumbnails.set.

## Interface

### src/omnicast/upload/youtube_api.py

```python
"""YouTube Data API v3 uploader. videos.insert + thumbnails.set + videos.update."""

from __future__ import annotations
import asyncio
from pathlib import Path
import structlog
from omnicast.upload.models import (
    UploadRequest, UploadResult, UploadMetadata, UploadStatus,
)
from omnicast.upload.oauth import OAuth2Manager
from omnicast.config.settings import get_settings
from omnicast.shared.errors import UploadPipelineError

logger = structlog.get_logger()

YOUTUBE_API_QUOTA_COST = {
    "videos.insert": 1600,
    "thumbnails.set": 50,
    "videos.update": 50,
    "videos.list": 1,
}


class YouTubeUploader:
    """Upload video via YouTube Data API v3."""

    def __init__(self, oauth_manager: OAuth2Manager) -> None:
        self.oauth = oauth_manager

    async def upload(self, request: UploadRequest) -> UploadResult:
        """Full upload flow. Steps:
        1. Get OAuth2 credentials for channel
        2. Build video resource (title, description, tags, privacy, schedule)
        3. Call videos.insert with resumable upload
        4. Set thumbnail if paths provided
        5. Return UploadResult with youtube_video_id + url
        Dry-run: return mock UploadResult without API call.
        """
        settings = get_settings()
        if settings.is_dry_run:
            return self._dry_run_result(request)

        try:
            credentials = await self.oauth.get_credentials(request.channel_id)
            service = self._build_service(credentials)
            youtube_id = await self._insert_video(service, request)
            thumbnail_set = False
            if request.thumbnail_paths:
                thumbnail_set = await self._set_thumbnail(
                    service, youtube_id, request.thumbnail_paths[0]
                )
            url = f"https://youtu.be/{youtube_id}"
            logger.info("Upload complete", video_id=request.video_id,
                        youtube_id=youtube_id, channel_id=request.channel_id)
            return UploadResult(
                youtube_video_id=youtube_id,
                channel_id=request.channel_id,
                status=UploadStatus.PUBLISHED,
                url=url,
                thumbnail_set=thumbnail_set,
            )
        except Exception as exc:
            logger.error("Upload failed", video_id=request.video_id, error=str(exc))
            return UploadResult(
                channel_id=request.channel_id,
                status=UploadStatus.FAILED,
                error=str(exc),
            )

    def _build_service(self, credentials):
        """Build YouTube API service object using google-api-python-client."""
        ...

    async def _insert_video(self, service, request: UploadRequest) -> str:
        """Call videos.insert with resumable upload. Returns youtube_video_id.
        - MediaFileUpload with chunksize=256*1024, resumable=True
        - Retry on 5xx errors (max 3 retries)
        - body includes snippet (title, description, tags, categoryId)
                        + status (privacyStatus, publishAt, madeForKids)
        """
        ...

    async def _set_thumbnail(self, service, youtube_video_id: str,
                              thumbnail_path: str) -> bool:
        """Call thumbnails.set. Returns True on success."""
        ...

    async def update_metadata(self, channel_id: str, youtube_video_id: str,
                                metadata: UploadMetadata) -> bool:
        """Call videos.update to change title/description/tags post-upload."""
        ...

    def _dry_run_result(self, request: UploadRequest) -> UploadResult:
        return UploadResult(
            youtube_video_id=f"dry_run_{request.video_id}",
            channel_id=request.channel_id,
            status=UploadStatus.PUBLISHED,
            url=f"https://youtu.be/dry_run_{request.video_id}",
            thumbnail_set=bool(request.thumbnail_paths),
        )

    @staticmethod
    def estimate_quota_cost(has_thumbnail: bool = True) -> int:
        """Estimate quota cost for one upload."""
        cost = YOUTUBE_API_QUOTA_COST["videos.insert"]
        if has_thumbnail:
            cost += YOUTUBE_API_QUOTA_COST["thumbnails.set"]
        return cost
```

## DO NOT

- No actual YouTube API calls in tests — mock google-api-python-client
- No Playwright/browser automation — API only
- No modifying models.py, oauth.py, or compliance.py
- NEVER log OAuth tokens — log channel_id and youtube_video_id only
- Resumable upload must handle 5xx retries (max 3)
- Must check settings.is_dry_run before any API call

## Tests

### tests/unit/test_youtube_api.py

```python
import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from omnicast.upload.youtube_api import YouTubeUploader, YOUTUBE_API_QUOTA_COST
from omnicast.upload.models import (
    UploadRequest, UploadResult, UploadMetadata, UploadStatus,
)
from omnicast.upload.oauth import OAuth2Manager


@pytest.fixture
def mock_oauth():
    oauth = MagicMock(spec=OAuth2Manager)
    oauth.get_credentials = AsyncMock(return_value=MagicMock())
    return oauth


@pytest.fixture
def uploader(mock_oauth):
    return YouTubeUploader(oauth_manager=mock_oauth)


def _make_request(**kwargs):
    meta = UploadMetadata(title="Test Video", description="Made with AI assistance.")
    defaults = {
        "video_id": "v1",
        "channel_id": "ch1",
        "video_path": "/tmp/final.mp4",
        "metadata": meta,
    }
    defaults.update(kwargs)
    return UploadRequest(**defaults)


class TestYouTubeDryRun:
    @pytest.mark.asyncio
    async def test_dry_run_returns_result(self, uploader):
        mock_settings = MagicMock()
        mock_settings.is_dry_run = True
        with patch("omnicast.upload.youtube_api.get_settings", return_value=mock_settings):
            result = await uploader.upload(_make_request())
            assert result.status == UploadStatus.PUBLISHED
            assert "dry_run" in result.youtube_video_id

    @pytest.mark.asyncio
    async def test_dry_run_with_thumbnail(self, uploader):
        mock_settings = MagicMock()
        mock_settings.is_dry_run = True
        with patch("omnicast.upload.youtube_api.get_settings", return_value=mock_settings):
            result = await uploader.upload(_make_request(thumbnail_paths=["/tmp/thumb.jpg"]))
            assert result.thumbnail_set is True

    @pytest.mark.asyncio
    async def test_dry_run_no_api_calls(self, uploader, mock_oauth):
        mock_settings = MagicMock()
        mock_settings.is_dry_run = True
        with patch("omnicast.upload.youtube_api.get_settings", return_value=mock_settings):
            await uploader.upload(_make_request())
            mock_oauth.get_credentials.assert_not_called()


class TestYouTubeUpload:
    @pytest.mark.asyncio
    async def test_upload_success(self, uploader):
        mock_settings = MagicMock()
        mock_settings.is_dry_run = False
        with patch("omnicast.upload.youtube_api.get_settings", return_value=mock_settings), \
             patch.object(uploader, "_build_service", return_value=MagicMock()), \
             patch.object(uploader, "_insert_video", new_callable=AsyncMock, return_value="yt_abc123"), \
             patch.object(uploader, "_set_thumbnail", new_callable=AsyncMock, return_value=True):
            result = await uploader.upload(_make_request(thumbnail_paths=["/tmp/t.jpg"]))
            assert result.youtube_video_id == "yt_abc123"
            assert result.status == UploadStatus.PUBLISHED
            assert result.thumbnail_set is True

    @pytest.mark.asyncio
    async def test_upload_failure(self, uploader):
        mock_settings = MagicMock()
        mock_settings.is_dry_run = False
        with patch("omnicast.upload.youtube_api.get_settings", return_value=mock_settings), \
             patch.object(uploader, "_build_service", side_effect=RuntimeError("Auth failed")):
            # Should not raise, returns failed result
            result = await uploader.upload(_make_request())
            assert result.status == UploadStatus.FAILED
            assert result.error is not None

    @pytest.mark.asyncio
    async def test_upload_no_thumbnail(self, uploader):
        mock_settings = MagicMock()
        mock_settings.is_dry_run = False
        with patch("omnicast.upload.youtube_api.get_settings", return_value=mock_settings), \
             patch.object(uploader, "_build_service", return_value=MagicMock()), \
             patch.object(uploader, "_insert_video", new_callable=AsyncMock, return_value="yt_xyz"):
            result = await uploader.upload(_make_request())
            assert result.thumbnail_set is False


class TestQuotaCost:
    def test_with_thumbnail(self):
        cost = YouTubeUploader.estimate_quota_cost(has_thumbnail=True)
        assert cost == 1650

    def test_without_thumbnail(self):
        cost = YouTubeUploader.estimate_quota_cost(has_thumbnail=False)
        assert cost == 1600

    def test_quota_constants(self):
        assert YOUTUBE_API_QUOTA_COST["videos.insert"] == 1600
        assert YOUTUBE_API_QUOTA_COST["thumbnails.set"] == 50
```
