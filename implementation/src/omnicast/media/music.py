"""Music module. Priority: YT Audio Library → Royalty-Free → ACE-Step → MusicGen fallback."""

from __future__ import annotations
import asyncio
from pathlib import Path
import structlog
from omnicast.media.base import BaseMediaModule
from omnicast.media.models import (
    MusicRequest, MusicResult, MusicSource, MediaStatus,
)
from omnicast.shared.errors import MediaError

logger = structlog.get_logger()


class MusicModule(BaseMediaModule):
    name = "music"

    async def _process(self, request: MusicRequest) -> MusicResult:
        """Try sources in priority order. First match wins. Steps:
        1. For each source in request.source_priority:
           - YT_AUDIO_LIB: search local cache NAS/assets/music/youtube_audio_lib/
           - ROYALTY_FREE: search NAS/assets/music/royalty_free/, verify license
           - ACE_STEP: generate via ComfyUI ACE-Step node
           - MUSICGEN: generate via AudioCraft subprocess
        2. Return first successful match
        3. If all fail → raise MediaError
        """
        for source in request.source_priority:
            try:
                result = await self._try_source(source, request)
                if result:
                    return result
            except Exception as exc:
                logger.warning("Music source failed", source=source, error=str(exc))
                continue
        raise MediaError("All music sources exhausted", details={"mood": request.mood})

    async def _try_source(self, source: MusicSource, request: MusicRequest) -> MusicResult | None:
        """Dispatch to source-specific handler."""
        if source == MusicSource.YT_AUDIO_LIB:
            return await self._search_yt_library(request)
        elif source == MusicSource.ROYALTY_FREE:
            return await self._search_royalty_free(request)
        elif source == MusicSource.ACE_STEP:
            return await self._generate_ace_step(request)
        elif source == MusicSource.MUSICGEN:
            return await self._generate_musicgen(request)
        return None

    async def _search_yt_library(self, request: MusicRequest) -> MusicResult | None:
        """Search cached YT Audio Library tracks by mood/genre/bpm. Return None if no match."""
        # Placeholder for actual YT Audio Library search
        # In production: search NAS/assets/music/youtube_audio_lib/ by mood/genre/bpm
        return None

    async def _search_royalty_free(self, request: MusicRequest) -> MusicResult | None:
        """Search royalty-free cache. Verify license metadata. Build attribution string."""
        # Placeholder for actual royalty-free search
        # In production: search NAS/assets/music/royalty_free/, verify license, build attribution
        return None

    async def _generate_ace_step(self, request: MusicRequest) -> MusicResult:
        """Generate via ACE-Step through ComfyUI. Returns generated track."""
        # Placeholder for actual ACE-Step generation
        # In production: call ComfyUI ACE-Step node with mood/genre/bpm parameters
        return MusicResult(
            audio_path=request.output_path or "ace_step_output.wav",
            source_used=MusicSource.ACE_STEP,
            duration_seconds=request.duration_seconds,
            bpm=request.bpm_range[0],
            license_info="AI-generated",
            attribution="",
            status=MediaStatus.DONE,
        )

    async def _generate_musicgen(self, request: MusicRequest) -> MusicResult:
        """Fallback: AudioCraft MusicGen subprocess."""
        # Placeholder for actual MusicGen generation
        # In production: call AudioCraft MusicGen via subprocess
        return MusicResult(
            audio_path=request.output_path or "musicgen_output.wav",
            source_used=MusicSource.MUSICGEN,
            duration_seconds=request.duration_seconds,
            bpm=request.bpm_range[0],
            license_info="AI-generated",
            attribution="",
            status=MediaStatus.DONE,
        )

    def _dry_run_result(self, request: MusicRequest) -> MusicResult:
        return MusicResult(
            audio_path=request.output_path or "dry_run_music.wav",
            source_used=request.source_priority[0] if request.source_priority else MusicSource.YT_AUDIO_LIB,
            duration_seconds=request.duration_seconds,
            bpm=request.bpm_range[0],
            license_info="dry_run",
            status=MediaStatus.DONE,
        )
