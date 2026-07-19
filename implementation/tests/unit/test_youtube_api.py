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
