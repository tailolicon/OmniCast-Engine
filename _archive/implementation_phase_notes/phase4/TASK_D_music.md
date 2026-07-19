# TASK_D: Music Module

## Model: sonnet | Dependencies: TASK_A complete

Implement music module: search YouTube Audio Library → Royalty-Free → ACE-Step AI generation.

## Interface

### src/omnicast/media/music.py

```python
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
        ...

    async def _search_royalty_free(self, request: MusicRequest) -> MusicResult | None:
        """Search royalty-free cache. Verify license metadata. Build attribution string."""
        ...

    async def _generate_ace_step(self, request: MusicRequest) -> MusicResult:
        """Generate via ACE-Step through ComfyUI. Returns generated track."""
        ...

    async def _generate_musicgen(self, request: MusicRequest) -> MusicResult:
        """Fallback: AudioCraft MusicGen subprocess."""
        ...

    def _dry_run_result(self, request: MusicRequest) -> MusicResult:
        return MusicResult(
            audio_path=request.output_path or "dry_run_music.wav",
            source_used=request.source_priority[0] if request.source_priority else MusicSource.YT_AUDIO_LIB,
            duration_seconds=request.duration_seconds,
            bpm=request.bpm_range[0],
            license_info="dry_run",
            status=MediaStatus.DONE,
        )
```

## DO NOT

- No audio perturbation/modification of tracks — use as-is
- No actual file I/O in tests — mock everything
- No TTS/image/video logic
- No downloading from internet in production code — assume tracks cached in NAS
- Attribution string must be non-empty for ROYALTY_FREE source

## Tests

### tests/unit/test_music.py

```python
import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from omnicast.media.music import MusicModule
from omnicast.media.models import MusicRequest, MusicResult, MusicSource, MediaStatus
from omnicast.shared.errors import MediaError


@pytest.fixture
def mock_settings():
    s = MagicMock()
    s.is_dry_run = False
    return s


@pytest.fixture
def dry_settings():
    s = MagicMock()
    s.is_dry_run = True
    return s


@pytest.fixture
def music(mock_settings):
    with patch("omnicast.media.base.get_settings", return_value=mock_settings):
        return MusicModule()


@pytest.fixture
def music_dry(dry_settings):
    with patch("omnicast.media.base.get_settings", return_value=dry_settings):
        return MusicModule()


class TestMusicDryRun:
    @pytest.mark.asyncio
    async def test_dry_run_result(self, music_dry):
        req = MusicRequest(mood="epic", duration_seconds=120.0)
        result = await music_dry.process(req)
        assert isinstance(result, MusicResult)
        assert result.status == MediaStatus.DONE
        assert result.duration_seconds == 120.0

    @pytest.mark.asyncio
    async def test_dry_run_uses_first_priority(self, music_dry):
        req = MusicRequest(source_priority=[MusicSource.ROYALTY_FREE, MusicSource.ACE_STEP])
        result = await music_dry.process(req)
        assert result.source_used == MusicSource.ROYALTY_FREE

    @pytest.mark.asyncio
    async def test_dry_run_bpm(self, music_dry):
        req = MusicRequest(bpm_range=(100, 120))
        result = await music_dry.process(req)
        assert result.bpm == 100


class TestMusicPriorityChain:
    @pytest.mark.asyncio
    async def test_first_source_succeeds(self, music):
        yt_result = MusicResult(
            audio_path="/nas/music/track.wav", source_used=MusicSource.YT_AUDIO_LIB,
            duration_seconds=60.0, status=MediaStatus.DONE,
        )
        with patch.object(music, "_search_yt_library", new_callable=AsyncMock, return_value=yt_result):
            result = await music._process(MusicRequest())
            assert result.source_used == MusicSource.YT_AUDIO_LIB

    @pytest.mark.asyncio
    async def test_fallback_to_second(self, music):
        rf_result = MusicResult(
            audio_path="/nas/music/rf.wav", source_used=MusicSource.ROYALTY_FREE,
            duration_seconds=60.0, attribution="Artist - CC BY", status=MediaStatus.DONE,
        )
        with patch.object(music, "_search_yt_library", new_callable=AsyncMock, return_value=None), \
             patch.object(music, "_search_royalty_free", new_callable=AsyncMock, return_value=rf_result):
            result = await music._process(MusicRequest())
            assert result.source_used == MusicSource.ROYALTY_FREE

    @pytest.mark.asyncio
    async def test_fallback_to_ai(self, music):
        ace_result = MusicResult(
            audio_path="/tmp/gen.wav", source_used=MusicSource.ACE_STEP,
            duration_seconds=60.0, status=MediaStatus.DONE,
        )
        with patch.object(music, "_search_yt_library", new_callable=AsyncMock, return_value=None), \
             patch.object(music, "_search_royalty_free", new_callable=AsyncMock, return_value=None), \
             patch.object(music, "_generate_ace_step", new_callable=AsyncMock, return_value=ace_result):
            result = await music._process(MusicRequest())
            assert result.source_used == MusicSource.ACE_STEP

    @pytest.mark.asyncio
    async def test_all_fail_raises(self, music):
        with patch.object(music, "_try_source", new_callable=AsyncMock, return_value=None):
            with pytest.raises(MediaError, match="exhausted"):
                await music._process(MusicRequest())

    @pytest.mark.asyncio
    async def test_source_error_continues(self, music):
        ace_result = MusicResult(
            audio_path="/tmp/gen.wav", source_used=MusicSource.ACE_STEP,
            duration_seconds=60.0, status=MediaStatus.DONE,
        )
        with patch.object(music, "_search_yt_library", new_callable=AsyncMock, side_effect=RuntimeError("disk")), \
             patch.object(music, "_search_royalty_free", new_callable=AsyncMock, side_effect=RuntimeError("net")), \
             patch.object(music, "_generate_ace_step", new_callable=AsyncMock, return_value=ace_result):
            result = await music._process(MusicRequest())
            assert result.source_used == MusicSource.ACE_STEP


class TestMusicModule:
    def test_name(self, music):
        assert music.name == "music"

    @pytest.mark.asyncio
    async def test_try_source_dispatch(self, music):
        with patch.object(music, "_search_yt_library", new_callable=AsyncMock, return_value=None) as mock_yt:
            await music._try_source(MusicSource.YT_AUDIO_LIB, MusicRequest())
            mock_yt.assert_called_once()

        with patch.object(music, "_generate_ace_step", new_callable=AsyncMock, return_value=None) as mock_ace:
            await music._try_source(MusicSource.ACE_STEP, MusicRequest())
            mock_ace.assert_called_once()

    @pytest.mark.asyncio
    async def test_custom_priority(self, music):
        mg_result = MusicResult(
            audio_path="/tmp/mg.wav", source_used=MusicSource.MUSICGEN,
            duration_seconds=60.0, status=MediaStatus.DONE,
        )
        with patch.object(music, "_generate_musicgen", new_callable=AsyncMock, return_value=mg_result):
            result = await music._process(
                MusicRequest(source_priority=[MusicSource.MUSICGEN])
            )
            assert result.source_used == MusicSource.MUSICGEN
```
