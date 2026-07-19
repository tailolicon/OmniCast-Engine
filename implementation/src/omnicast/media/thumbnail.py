"""Thumbnail generation. ComfyUI for base image + PIL for text overlay. 3 variants A/B/C."""

from __future__ import annotations
import asyncio
from pathlib import Path
import structlog
from omnicast.media.base import BaseMediaModule
from omnicast.media.models import ThumbnailRequest, ThumbnailResult, MediaStatus
from omnicast.shared.errors import MediaError

logger = structlog.get_logger()


class ThumbnailModule(BaseMediaModule):
    name = "thumbnail"

    def __init__(self, comfyui_url: str = "http://127.0.0.1:8188") -> None:
        super().__init__()
        self.comfyui_url = comfyui_url

    async def _process(self, request: ThumbnailRequest) -> ThumbnailResult:
        """Generate thumbnail variants. Steps:
        1. Generate base image via ComfyUI (or use source_image)
        2. For each variant (A/B/C):
           - Vary color_palette tint, expression, text position
           - PIL overlay: title text with font + color from request
           - Save as 1280x720 JPEG
        3. Return list of paths, variant A as selected
        """
        # Placeholder for actual thumbnail generation
        # In production: generate base image via ComfyUI, overlay text with PIL
        paths = []
        for i in range(request.variants):
            variant_path = f"{request.output_dir or ''}/thumb_{chr(65+i)}.jpg"
            self._overlay_text(variant_path, request.title, request.font, 
                             request.color_palette[i % len(request.color_palette)], 
                             variant_path)
            paths.append(variant_path)
        
        return ThumbnailResult(
            paths=paths,
            selected_variant=paths[0] if paths else "",
            status=MediaStatus.DONE,
        )

    def _overlay_text(self, image_path: str, title: str, font: str,
                      color: str, output_path: str) -> None:
        """PIL: draw title text on image. Bold, outlined, positioned bottom-third."""
        # Placeholder for actual PIL text overlay
        # In production: PIL ImageDraw with font, stroke for outline
        pass

    def _dry_run_result(self, request: ThumbnailRequest) -> ThumbnailResult:
        paths = [f"dry_run_thumb_{chr(65+i)}.jpg" for i in range(request.variants)]
        return ThumbnailResult(
            paths=paths,
            selected_variant=paths[0] if paths else "",
            status=MediaStatus.DONE,
        )
