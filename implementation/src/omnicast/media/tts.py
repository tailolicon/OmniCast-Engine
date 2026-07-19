"""TTS module — multi-source synthesis via VoiceRouter.

Routes 'provider:voice_id' specs (Kokoro local / Edge cloud / XTTSv2-F5
cloning) with an ordered fallback chain. No robotic fallback: if every
neural source fails the job fails loudly (quality gate, by design).
"""

from __future__ import annotations

import asyncio
import subprocess
import wave
from pathlib import Path

import structlog

from omnicast.media.base import BaseMediaModule
from omnicast.media.models import (
    TTSRequest, TTSResult, TTSEngine, MediaStatus,
)
from omnicast.media.voice_router import VoiceRouter, VoiceSpec
from omnicast.shared.errors import MediaError

logger = structlog.get_logger()


class TTSModule(BaseMediaModule):
    name = "tts"

    _router = VoiceRouter()

    async def _process(self, request: TTSRequest) -> TTSResult:
        """1. Build the voice chain (clone request forces clone provider first)
        2. VoiceRouter tries each source in order
        3. Loudness-normalize to target LUFS (real ffmpeg loudnorm)
        4. Return result with measured (not estimated) duration
        """
        chain: list[str] = []
        if request.voice_clone:
            chain.append(f"xttsv2:{request.voice_clone}")
        if request.voice_profile:
            chain.append(request.voice_profile)
        chain.extend(request.voice_fallback or [])
        if not chain:
            chain = ["kokoro:af_heart", "edge:en-US-AriaNeural"]

        output_path = request.output_path or "tts_output.wav"

        result = await self._router.synthesize(
            request.text,
            chain,
            output_path,
            voice_clone_path=request.voice_clone,
        )

        if request.target_lufs:
            await self._normalize_lufs(result.audio_path, request.target_lufs)

        duration = await asyncio.to_thread(_measure_duration, result.audio_path)
        if duration <= 0.0:  # container not probe-able → word estimate
            duration = len(request.text.split()) * 0.4

        try:
            engine_used = TTSEngine(result.spec.provider)
        except ValueError:
            engine_used = request.engine

        return TTSResult(
            audio_path=result.audio_path,
            duration_seconds=duration,
            engine_used=engine_used,
            status=MediaStatus.DONE,
        )

    async def _normalize_lufs(self, audio_path: str, target_lufs: float) -> None:
        """Two-file ffmpeg loudnorm to target LUFS (in-place via temp file).
        Non-fatal: a normalization failure logs a warning, audio stays usable."""
        src = Path(audio_path)
        tmp = src.with_suffix(".norm" + src.suffix)

        def _run() -> bool:
            proc = subprocess.run(
                ["ffmpeg", "-y", "-i", str(src),
                 "-af", f"loudnorm=I={target_lufs}:TP=-1.5:LRA=11",
                 "-ar", "24000", str(tmp)],
                capture_output=True, text=True,
            )
            return proc.returncode == 0

        try:
            ok = await asyncio.to_thread(_run)
            if ok and tmp.exists() and tmp.stat().st_size > 0:
                tmp.replace(src)
            else:
                tmp.unlink(missing_ok=True)
                logger.warning("loudnorm failed, keeping raw audio", path=audio_path)
        except FileNotFoundError:
            logger.warning("ffmpeg not found — skipping loudness normalization")

    def _dry_run_result(self, request: TTSRequest) -> TTSResult:
        return TTSResult(
            audio_path=request.output_path or "dry_run_tts.wav",
            duration_seconds=len(request.text.split()) * 0.4,
            engine_used=request.engine,
            status=MediaStatus.DONE,
        )


def _measure_duration(audio_path: str) -> float:
    """Real duration: wave header for .wav, ffprobe for anything else."""
    p = Path(audio_path)
    if not p.exists():
        return 0.0
    if p.suffix.lower() == ".wav":
        try:
            with wave.open(str(p), "rb") as w:
                rate = w.getframerate()
                return w.getnframes() / float(rate) if rate else 0.0
        except Exception:
            pass
    try:
        proc = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
             "-of", "csv=p=0", str(p)],
            capture_output=True, text=True,
        )
        return float(proc.stdout.strip()) if proc.returncode == 0 else 0.0
    except Exception:
        return 0.0
