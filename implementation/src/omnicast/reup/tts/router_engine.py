"""Let the reup pipeline use OmniCast's TTS providers.

The ported factory only knew its own two engines (`vieneu`, `sapi`), so the
whole OmniCast provider registry — Edge, CapCut, Volcengine, Kokoro, Piper,
Chatterbox — was unreachable from a dub job. That is why asking for a CapCut
voice could not be honoured no matter what the preset said.

A preset routes here by naming an OmniCast provider as its engine:

    engine="capcut",     voice_id="BV074_streaming"
    engine="edge",       voice_id="vi-VN-HoaiMyNeural"
    engine="volcengine", voice_id="zh_female_vv_uranus_bigtts"

Speed/volume ride along as prosody; the router drops whatever a given provider
does not accept rather than failing on an unknown keyword.
"""

from __future__ import annotations

import asyncio
import wave
from pathlib import Path

from .base import TTSEngine
from .models import SynthesisResult, VoicePreset


def _probe_wav(path: Path) -> tuple[int, int]:
    """Return (duration_ms, sample_rate) for a rendered clip."""
    with wave.open(str(path), "rb") as handle:
        frames, rate = handle.getnframes(), handle.getframerate()
    return (int(frames / rate * 1000) if rate else 0, rate)


class VoiceRouterTTSEngine(TTSEngine):
    """Bridge from reup's sync engine interface to OmniCast's async router."""

    def __init__(self, provider: str) -> None:
        self._provider = provider

    def synthesize(
        self,
        *,
        text: str,
        output_path: Path,
        preset: VoicePreset,
    ) -> SynthesisResult:
        from omnicast.media.voice_router import VoiceRouter

        voice = (preset.voice_id or "").strip()
        if not voice or voice == "default":
            raise RuntimeError(
                f"Provider {self._provider!r} needs an explicit voice id in the preset "
                f"(got {preset.voice_id!r})"
            )
        spec = f"{self._provider}:{voice}"

        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Providers disagree on how pace is expressed and the router only
        # filters prosody by *name*, not type — handing Edge a float `volume`
        # got as far as "volume must be str". So offer both conventions and let
        # each provider keep the one it declares: `speed` is numeric (Kokoro,
        # VieNeu), `rate` is an SSML percentage (Edge, Azure).
        #
        # Per-clip volume is deliberately not sent: the mixdown stage already
        # sets voice level, and the two would compound.
        pace = float(preset.speed or 1.0)
        prosody: dict[str, object] = {"speed": pace}
        if abs(pace - 1.0) > 0.001:
            prosody["rate"] = f"{round((pace - 1.0) * 100):+d}%"

        # The TTS stage runs synchronously on a worker thread, so there is no
        # loop to clash with; the check keeps the failure legible if that
        # assumption ever changes.
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            pass
        else:
            raise RuntimeError("reup TTS stages must run off the event loop")

        result = asyncio.run(
            VoiceRouter().synthesize(text, [spec], str(output_path), prosody=prosody)
        )

        rendered = Path(result.audio_path)
        if not rendered.is_file() or rendered.stat().st_size <= 44:
            raise RuntimeError(f"{spec} produced no audio")

        duration_ms, sample_rate = _probe_wav(rendered)
        return SynthesisResult(
            wav_path=rendered,
            duration_ms=duration_ms,
            sample_rate=sample_rate or preset.sample_rate,
            voice_id=voice,
        )
