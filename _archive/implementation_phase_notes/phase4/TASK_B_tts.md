# TASK_B: TTS Module

## Model: sonnet | Dependencies: TASK_A complete

Implement TTS module wrapping Kokoro (primary), XTTSv2 (voice cloning), Piper (fallback).

## Interface

### src/omnicast/media/tts.py

```python
"""TTS module. Wraps Kokoro-82M, XTTSv2, Piper via subprocess/library calls."""

from __future__ import annotations
import asyncio
from pathlib import Path
import structlog
from omnicast.media.base import BaseMediaModule
from omnicast.media.models import (
    TTSRequest, TTSResult, TTSEngine, MediaStatus,
)
from omnicast.shared.errors import MediaError

logger = structlog.get_logger()


class TTSModule(BaseMediaModule):
    name = "tts"

    async def _process(self, request: TTSRequest) -> TTSResult:
        """Route to engine based on request.engine. Steps:
        1. If voice_clone set → force XTTSv2
        2. Generate audio via selected engine
        3. Normalize to target_lufs (-14 LUFS default)
        4. Return TTSResult with path + duration
        """
        engine = request.engine
        if request.voice_clone:
            engine = TTSEngine.XTTSV2

        if engine == TTSEngine.KOKORO:
            return await self._kokoro(request)
        elif engine == TTSEngine.XTTSV2:
            return await self._xttsv2(request)
        elif engine == TTSEngine.PIPER:
            return await self._piper(request)
        raise MediaError(f"Unknown TTS engine: {engine}")

    async def _kokoro(self, request: TTSRequest) -> TTSResult:
        """Call Kokoro-82M. Use kokoro library: Pipeline → generate → save wav."""
        ...

    async def _xttsv2(self, request: TTSRequest) -> TTSResult:
        """Call XTTSv2 for voice cloning. Requires voice_clone path."""
        if not request.voice_clone:
            raise MediaError("XTTSv2 requires voice_clone path")
        ...

    async def _piper(self, request: TTSRequest) -> TTSResult:
        """Call Piper TTS via subprocess."""
        ...

    async def _normalize_lufs(self, audio_path: str, target_lufs: float) -> None:
        """FFmpeg loudnorm to target LUFS. In-place."""
        ...

    def _dry_run_result(self, request: TTSRequest) -> TTSResult:
        return TTSResult(
            audio_path=request.output_path or "dry_run_tts.wav",
            duration_seconds=len(request.text.split()) * 0.4,
            engine_used=request.engine,
            status=MediaStatus.DONE,
        )
```

## DO NOT

- No actual model weights loading in tests — mock all engine calls
- No direct `os.system()` — use `asyncio.create_subprocess_exec`
- No modifying models.py or base.py
- No music/image generation — TTS only
- `_normalize_lufs` must use FFmpeg subprocess, not inline audio math

## Tests

### tests/unit/test_tts.py

```python
import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from omnicast.media.tts import TTSModule
from omnicast.media.models import TTSRequest, TTSResult, TTSEngine, MediaStatus
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
def tts(mock_settings):
    with patch("omnicast.media.base.get_settings", return_value=mock_settings):
        return TTSModule()


@pytest.fixture
def tts_dry(dry_settings):
    with patch("omnicast.media.base.get_settings", return_value=dry_settings):
        return TTSModule()


class TestTTSDryRun:
    @pytest.mark.asyncio
    async def test_dry_run_returns_result(self, tts_dry):
        req = TTSRequest(text="Hello world test sentence")
        result = await tts_dry.process(req)
        assert isinstance(result, TTSResult)
        assert result.status == MediaStatus.DONE
        assert result.duration_seconds > 0

    @pytest.mark.asyncio
    async def test_dry_run_uses_output_path(self, tts_dry):
        req = TTSRequest(text="Hi", output_path="/tmp/custom.wav")
        result = await tts_dry.process(req)
        assert result.audio_path == "/tmp/custom.wav"

    @pytest.mark.asyncio
    async def test_dry_run_default_path(self, tts_dry):
        req = TTSRequest(text="Hi")
        result = await tts_dry.process(req)
        assert "dry_run" in result.audio_path


class TestTTSRouting:
    @pytest.mark.asyncio
    async def test_kokoro_default(self, tts):
        with patch.object(tts, "_kokoro", new_callable=AsyncMock) as mock_k:
            mock_k.return_value = TTSResult(engine_used=TTSEngine.KOKORO)
            result = await tts._process(TTSRequest(text="Hello"))
            mock_k.assert_called_once()
            assert result.engine_used == TTSEngine.KOKORO

    @pytest.mark.asyncio
    async def test_piper_route(self, tts):
        with patch.object(tts, "_piper", new_callable=AsyncMock) as mock_p:
            mock_p.return_value = TTSResult(engine_used=TTSEngine.PIPER)
            result = await tts._process(TTSRequest(text="Hi", engine=TTSEngine.PIPER))
            mock_p.assert_called_once()

    @pytest.mark.asyncio
    async def test_voice_clone_forces_xttsv2(self, tts):
        with patch.object(tts, "_xttsv2", new_callable=AsyncMock) as mock_x:
            mock_x.return_value = TTSResult(engine_used=TTSEngine.XTTSV2)
            result = await tts._process(
                TTSRequest(text="Hi", voice_clone="/path/to/voice.wav", engine=TTSEngine.KOKORO)
            )
            mock_x.assert_called_once()

    @pytest.mark.asyncio
    async def test_xttsv2_requires_voice_clone(self, tts):
        with pytest.raises(MediaError, match="voice_clone"):
            await tts._xttsv2(TTSRequest(text="Hi", engine=TTSEngine.XTTSV2))


class TestTTSModule:
    def test_name(self, tts):
        assert tts.name == "tts"

    @pytest.mark.asyncio
    async def test_process_wraps_errors(self, tts):
        with patch.object(tts, "_kokoro", new_callable=AsyncMock, side_effect=RuntimeError("fail")):
            with pytest.raises(RuntimeError):
                await tts.process(TTSRequest(text="Hi"))

    @pytest.mark.asyncio
    async def test_dry_run_duration_estimate(self, tts_dry):
        text = "one two three four five"
        result = await tts_dry.process(TTSRequest(text=text))
        assert result.duration_seconds == pytest.approx(5 * 0.4, abs=0.1)
```
