"""DEPRECATED — Video generation shell (was placeholder Wan21 / Ken Burns).

Use ``omnicast.media.providers.video_gemini`` (or any other provider via
``omnicast.media.providers.registry.get_video_provider``) instead.

Kept as a thin shell so legacy imports keep resolving and orchestrator
dry-run paths still work. The real ``_process`` raises to surface accidental
calls.
"""

from __future__ import annotations

import structlog

from omnicast.media.base import BaseMediaModule
from omnicast.media.models import (
    MediaStatus,
    VideoGenBackend,
    VideoGenRequest,
    VideoGenResult,
)
from omnicast.shared.errors import MediaError

logger = structlog.get_logger()


class VideoGenModule(BaseMediaModule):
    """DEPRECATED — kept for backward-compatible imports only."""

    name = "video_gen"

    def __init__(self, comfyui_url: str = "http://127.0.0.1:8188") -> None:
        super().__init__()
        self.comfyui_url = comfyui_url

    async def _process(self, request: VideoGenRequest) -> VideoGenResult:
        raise MediaError(
            "VideoGenModule is deprecated. Use "
            "omnicast.media.providers.registry.get_video_provider() instead."
        )

    def _dry_run_result(self, request: VideoGenRequest) -> VideoGenResult:
        return VideoGenResult(
            video_path=request.output_path or "dry_run_video.mp4",
            duration_seconds=request.duration_seconds,
            backend_used=request.backend,
            status=MediaStatus.DONE,
        )
