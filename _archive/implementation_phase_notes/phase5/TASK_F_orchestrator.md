# TASK_F: Upload Pipeline Orchestrator

## Model: sonnet | Dependencies: TASK_A-E complete

Orchestrate: compliance check → schedule → upload → thumbnail A/B registration.

## Interface

### src/omnicast/upload/orchestrator.py

```python
"""Upload Pipeline Orchestrator. Compliance → Schedule → Upload → Thumbnail."""

from __future__ import annotations
import structlog
from omnicast.upload.models import (
    UploadPipelineState, UploadStatus, UploadRequest, UploadResult,
    UploadMetadata, ScheduleSlot,
)
from omnicast.upload.compliance import ComplianceChecker
from omnicast.upload.scheduler import UploadScheduler
from omnicast.upload.youtube_api import YouTubeUploader
from omnicast.upload.thumbnail import ThumbnailManager
from omnicast.models.enums import ChannelType
from omnicast.media.models import ContentFingerprint
from omnicast.shared.errors import UploadPipelineError

logger = structlog.get_logger()


class UploadPipelineOrchestrator:
    """Run full upload pipeline for one video."""

    def __init__(
        self,
        compliance: ComplianceChecker | None = None,
        scheduler: UploadScheduler | None = None,
        uploader: YouTubeUploader | None = None,
        thumbnail_mgr: ThumbnailManager | None = None,
    ) -> None:
        self.compliance = compliance or ComplianceChecker()
        self.scheduler = scheduler or UploadScheduler()
        self.uploader = uploader  # required, no default
        self.thumbnail_mgr = thumbnail_mgr

    async def run(
        self,
        video_id: str,
        channel_id: str,
        channel_type: ChannelType,
        video_path: str,
        metadata: UploadMetadata,
        thumbnail_paths: list[str] | None = None,
        market: str = "US",
        existing_fingerprints: list[ContentFingerprint] | None = None,
    ) -> tuple[UploadPipelineState, UploadResult | None]:
        """Execute full upload pipeline. Steps:
        1. Compliance gate → reject if failed → video to DLQ
        2. Schedule upload slot (rate limit + prime time)
        3. Upload via YouTube API
        4. Register thumbnail variants for A/B testing
        """
        if not self.uploader:
            raise UploadPipelineError("YouTubeUploader not configured")

        state = UploadPipelineState(video_id=video_id, channel_id=channel_id)

        # Step 1: Compliance
        request = UploadRequest(
            video_id=video_id,
            channel_id=channel_id,
            video_path=video_path,
            metadata=metadata,
            thumbnail_paths=thumbnail_paths or [],
        )

        compliance_result = self.compliance.check(request)
        request = request.model_copy(update={"compliance": compliance_result})

        if not compliance_result.passed:
            state = state.model_copy(update={"compliance": UploadStatus.REJECTED})
            logger.warning("Upload rejected by compliance", video_id=video_id,
                           violations=compliance_result.violations)
            return state, None

        state = state.model_copy(update={"compliance": UploadStatus.PUBLISHED})

        # Step 2: Schedule
        try:
            slot = self.scheduler.schedule(channel_id, channel_type, market=market)
            state = state.model_copy(update={"scheduling": UploadStatus.SCHEDULED})

            # Update metadata with scheduled time
            if slot.is_prime_time:
                metadata = metadata.model_copy(update={
                    "publish_at": slot.scheduled_at,
                    "privacy_status": "private",
                })
                request = request.model_copy(update={"metadata": metadata})
        except UploadPipelineError as exc:
            state = state.model_copy(update={"scheduling": UploadStatus.FAILED})
            logger.error("Scheduling failed", video_id=video_id, error=str(exc))
            return state, None

        # Step 3: Upload
        upload_result = await self.uploader.upload(request)

        if upload_result.status == UploadStatus.FAILED:
            state = state.model_copy(update={"upload": UploadStatus.FAILED})
            return state, upload_result

        state = state.model_copy(update={"upload": UploadStatus.PUBLISHED})
        self.scheduler.record_upload(channel_id)

        # Step 4: Thumbnail A/B registration
        if self.thumbnail_mgr and thumbnail_paths and upload_result.youtube_video_id:
            self.thumbnail_mgr.register_variants(
                upload_result.youtube_video_id, channel_id, thumbnail_paths
            )
            state = state.model_copy(update={"thumbnail": UploadStatus.PUBLISHED})
        else:
            state = state.model_copy(update={"thumbnail": UploadStatus.PUBLISHED})

        logger.info("Upload pipeline complete", video_id=video_id,
                     youtube_id=upload_result.youtube_video_id)

        return state, upload_result
```

## DO NOT

- No actual API calls in tests — mock all modules
- No modifying other upload modules
- Orchestrator must use model_copy() for state updates (immutable)
- Compliance failure must stop pipeline — no upload attempt
- Scheduling failure must stop pipeline — no upload attempt
- record_upload must be called after successful upload

## Tests

### tests/unit/test_upload_orchestrator.py

```python
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
```
