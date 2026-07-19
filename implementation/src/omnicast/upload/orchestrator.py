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
from omnicast.config.channel import ChannelProfile

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
        channel: ChannelProfile | None = None,
    ) -> tuple[UploadPipelineState, UploadResult | None]:
        """Execute full upload pipeline. Steps:
        1. Compliance gate → reject if failed → video to DLQ
        2. Schedule upload slot (rate limit + prime time) - use channel schedule if provided
        3. Upload via YouTube API
        4. Register thumbnail variants for A/B testing
        """
        if not self.uploader:
            raise UploadPipelineError("YouTubeUploader not configured")

        # Enhance metadata with channel profile if provided
        if channel and isinstance(channel, ChannelProfile):
            # Use channel's prime time hours for scheduling
            if not hasattr(self.scheduler, 'prime_time_hours'):
                self.scheduler.prime_time_hours = channel.prime_time_hours

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
