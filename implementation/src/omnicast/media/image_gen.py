"""DEPRECATED — Image generation shell (was placeholder ComfyUI integration).

Use ``omnicast.media.providers.image_gemini`` (or any other provider via
``omnicast.media.providers.registry.get_image_provider``) instead.

Kept as a thin shell so legacy imports keep resolving and orchestrator
dry-run paths still work. The real ``_process`` raises to surface accidental
calls.
"""

from __future__ import annotations

from pathlib import Path

import structlog

from omnicast.media.base import BaseMediaModule
from omnicast.media.models import ImageGenRequest, ImageGenResult, MediaStatus
from omnicast.shared.errors import MediaError

logger = structlog.get_logger()

COMFYUI_DEFAULT_URL = "http://127.0.0.1:8188"


class ImageGenModule(BaseMediaModule):
    """DEPRECATED — kept for backward-compatible imports only."""

    name = "image_gen"

    def __init__(self, comfyui_url: str = COMFYUI_DEFAULT_URL) -> None:
        super().__init__()
        self.comfyui_url = comfyui_url

    async def _process(self, request: ImageGenRequest) -> ImageGenResult:
        raise MediaError(
            "ImageGenModule is deprecated. Use "
            "omnicast.media.providers.registry.get_image_provider() instead."
        )

    def _dry_run_result(self, request: ImageGenRequest) -> ImageGenResult:
        return ImageGenResult(
            image_path=request.output_path or "dry_run_image.png",
            backend_used=request.backend,
            seed=42,
            status=MediaStatus.DONE,
        )
