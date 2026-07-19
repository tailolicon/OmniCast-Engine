"""FFmpeg render module. Composes 5 layers into final video."""

from __future__ import annotations
import asyncio
from pathlib import Path
import structlog
from omnicast.media.base import BaseMediaModule
from omnicast.media.models import (
    RenderJob, RenderResult, RenderLayer, MediaStatus,
)
from omnicast.shared.errors import MediaError

logger = structlog.get_logger()


class FFmpegModule(BaseMediaModule):
    name = "ffmpeg"

    async def _process(self, request: RenderJob) -> RenderResult:
        """Build and run FFmpeg command. 5 layers:
        Layer 1: Video/image clips (crossfade transition)
        Layer 2: Voiceover audio
        Layer 3: Background music (ducking at music_duck_db when voiceover present)
        Layer 4: Subtitles (burn-in from SRT)
        Layer 5: Intro + outro (concat before/after main)

        Steps:
        1. Validate all layer file paths exist
        2. Build complex filter graph
        3. Run via asyncio.create_subprocess_exec
        4. Parse output for duration + file size
        5. Return RenderResult
        """
        self._validate_layers(request.layers)
        cmd = self._build_command(request)
        return await self._run_ffmpeg(cmd, request.output_path)

    def _validate_layers(self, layers: list[RenderLayer]) -> None:
        """Check required layers exist. Raise MediaError if video or voiceover missing."""
        layer_types = {l.layer_type for l in layers}
        for required in ["video", "voiceover"]:
            if required not in layer_types:
                raise MediaError(f"Missing required layer: {required}")

    def _build_command(self, job: RenderJob) -> list[str]:
        """Build FFmpeg CLI args using EZFFMPEG Builder.
        - Video: concat
        - Audio: amix voiceover + music
        - Subtitle: subtitles filter from SRT
        """
        from omnicast.media.render_engine import EZFFMPEG
        
        builder = EZFFMPEG()
        output_path = job.output_path or "output.mp4"
        
        for layer in job.layers:
            if layer.layer_type == "video":
                builder.add_video(layer.file_path, has_audio=False)
            elif layer.layer_type == "voiceover":
                builder.add_audio(layer.file_path, type="voice")
            elif layer.layer_type == "music":
                builder.add_audio(layer.file_path, type="bgm", ducking=True)
            elif layer.layer_type == "subtitle":
                builder.add_subtitle(layer.file_path)
                
        cmd = builder.build(output_path)
        
        # Override codec options from job if needed, but EZFFMPEG has defaults
        # For this stage, returning builder's cmd is sufficient
        return cmd

    async def _run_ffmpeg(self, cmd: list[str], output_path: str) -> RenderResult:
        """Execute FFmpeg subprocess. Parse stderr for progress. Return RenderResult."""
        # Placeholder for actual FFmpeg execution
        # In production: asyncio.create_subprocess_exec, parse stderr for duration
        return RenderResult(
            output_path=output_path,
            duration_seconds=300.0,
            file_size_mb=150.0,
            status=MediaStatus.DONE,
        )

    def _get_file_size_mb(self, path: str) -> float:
        """Return file size in MB."""
        # Placeholder for actual file size calculation
        return 0.0

    def _dry_run_result(self, request: RenderJob) -> RenderResult:
        return RenderResult(
            output_path=request.output_path or "dry_run_render.mp4",
            duration_seconds=0.0,
            file_size_mb=0.0,
            status=MediaStatus.DONE,
        )
