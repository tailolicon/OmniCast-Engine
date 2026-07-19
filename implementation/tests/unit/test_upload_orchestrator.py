import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from omnicast.upload.orchestrator import UploadPipelineOrchestrator
from omnicast.upload.models import (
    UploadPipelineState, UploadStatus, UploadResult,
    UploadMetadata, ComplianceResult, ScheduleSlot,
)
from omnicast.upload.compliance import ComplianceChecker
from omnicast.upload.scheduler import UploadScheduler
from omnicast.upload.youtube_api import YouTubeUploader
from omnicast.upload.thumbnail import ThumbnailManager
from omnicast.models.enums import ChannelType
from omnicast.shared.errors import UploadPipelineError
from datetime import datetime, timezone


@pytest.fixture
def metadata():
    return UploadMetadata(title="Test", description="Made with AI assistance.")


@pytest.fixture
def mock_compliance():
    c = MagicMock(spec=ComplianceChecker)
    c.check.return_value = ComplianceResult(
        passed=True, checks={"ai_disclosure": True, "not_targeting_children": True}
    )
    return c


@pytest.fixture
def mock_scheduler():
    s = MagicMock(spec=UploadScheduler)
    s.schedule.return_value = ScheduleSlot(
        channel_id="ch1",
        scheduled_at=datetime(2025, 6, 3, 15, 0, tzinfo=timezone.utc),
        market="US", is_prime_time=True,
    )
    s.record_upload = MagicMock()
    return s


@pytest.fixture
def mock_uploader():
    u = MagicMock(spec=YouTubeUploader)
    u.upload = AsyncMock(return_value=UploadResult(
        youtube_video_id="yt_abc", channel_id="ch1",
        status=UploadStatus.PUBLISHED, url="https://youtu.be/yt_abc",
    ))
    return u


@pytest.fixture
def mock_thumbnail():
    t = MagicMock(spec=ThumbnailManager)
    t.register_variants = MagicMock()
    return t


@pytest.fixture
def orch(mock_compliance, mock_scheduler, mock_uploader, mock_thumbnail):
    return UploadPipelineOrchestrator(
        compliance=mock_compliance, scheduler=mock_scheduler,
        uploader=mock_uploader, thumbnail_mgr=mock_thumbnail,
    )


class TestUploadOrchestratorHappyPath:
    @pytest.mark.asyncio
    async def test_full_pipeline(self, orch, metadata):
        state, result = await orch.run(
            video_id="v1", channel_id="ch1", channel_type=ChannelType.HUB,
            video_path="/tmp/final.mp4", metadata=metadata,
            thumbnail_paths=["/tmp/a.jpg", "/tmp/b.jpg"],
        )
        assert state.compliance == UploadStatus.PUBLISHED
        assert state.scheduling == UploadStatus.SCHEDULED
        assert state.upload == UploadStatus.PUBLISHED
        assert state.thumbnail == UploadStatus.PUBLISHED
        assert result is not None
        assert result.youtube_video_id == "yt_abc"

    @pytest.mark.asyncio
    async def test_records_upload(self, orch, metadata, mock_scheduler):
        await orch.run(
            video_id="v1", channel_id="ch1", channel_type=ChannelType.HUB,
            video_path="/tmp/final.mp4", metadata=metadata,
        )
        mock_scheduler.record_upload.assert_called_once_with("ch1")


class TestUploadOrchestratorCompliance:
    @pytest.mark.asyncio
    async def test_compliance_failure_stops(self, mock_compliance, mock_scheduler,
                                             mock_uploader, metadata):
        mock_compliance.check.return_value = ComplianceResult(
            passed=False, violations=["Missing AI disclosure"]
        )
        orch = UploadPipelineOrchestrator(
            compliance=mock_compliance, scheduler=mock_scheduler,
            uploader=mock_uploader,
        )
        state, result = await orch.run(
            video_id="v1", channel_id="ch1", channel_type=ChannelType.HUB,
            video_path="/tmp/final.mp4", metadata=metadata,
        )
        assert state.compliance == UploadStatus.REJECTED
        assert result is None
        mock_uploader.upload.assert_not_called()


class TestUploadOrchestratorScheduling:
    @pytest.mark.asyncio
    async def test_scheduling_failure_stops(self, mock_compliance, mock_scheduler,
                                              mock_uploader, metadata):
        mock_scheduler.schedule.side_effect = UploadPipelineError("Daily limit")
        orch = UploadPipelineOrchestrator(
            compliance=mock_compliance, scheduler=mock_scheduler,
            uploader=mock_uploader,
        )
        state, result = await orch.run(
            video_id="v1", channel_id="ch1", channel_type=ChannelType.HUB,
            video_path="/tmp/final.mp4", metadata=metadata,
        )
        assert state.scheduling == UploadStatus.FAILED
        assert result is None


class TestUploadOrchestratorUpload:
    @pytest.mark.asyncio
    async def test_upload_failure(self, mock_compliance, mock_scheduler,
                                    mock_uploader, metadata):
        mock_uploader.upload = AsyncMock(return_value=UploadResult(
            status=UploadStatus.FAILED, error="Quota exceeded"
        ))
        orch = UploadPipelineOrchestrator(
            compliance=mock_compliance, scheduler=mock_scheduler,
            uploader=mock_uploader,
        )
        state, result = await orch.run(
            video_id="v1", channel_id="ch1", channel_type=ChannelType.HUB,
            video_path="/tmp/final.mp4", metadata=metadata,
        )
        assert state.upload == UploadStatus.FAILED
        assert result is not None
        assert result.error is not None


class TestUploadOrchestratorNoUploader:
    @pytest.mark.asyncio
    async def test_no_uploader_raises(self, metadata):
        orch = UploadPipelineOrchestrator(uploader=None)
        with pytest.raises(UploadPipelineError, match="not configured"):
            await orch.run(
                video_id="v1", channel_id="ch1", channel_type=ChannelType.HUB,
                video_path="/tmp/final.mp4", metadata=metadata,
            )


class TestUploadOrchestratorState:
    @pytest.mark.asyncio
    async def test_state_immutable(self, orch, metadata):
        state, _ = await orch.run(
            video_id="v1", channel_id="ch1", channel_type=ChannelType.HUB,
            video_path="/tmp/final.mp4", metadata=metadata,
        )
        with pytest.raises(Exception):
            state.compliance = UploadStatus.PENDING
