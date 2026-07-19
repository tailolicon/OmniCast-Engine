"""Edge-TTS provider — Microsoft neural voices, free, no API key.

Fills the gaps Kokoro can't cover (Korean, Vietnamese, German, Indonesian,
locale-specific English accents like en-AU/en-CA/en-IN) and adds hundreds of
extra neural voices for per-channel diversity.

Needs network. Writes a `.words.json` sidecar with exact word timings next to
the audio when word boundaries are available — the caption stage prefers these
over Whisper transcription (perfect sync, no misspelled numbers).
"""

from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path

from omnicast.media.providers.interfaces import ITTSProvider, ModelOption

_FEATURED = [
    ("en-US-GuyNeural", "Guy (US male)", "Energetic narrator"),
    ("en-US-AriaNeural", "Aria (US female)", "Conversational"),
    ("en-GB-RyanNeural", "Ryan (UK male)", "British narrator"),
    ("en-AU-NatashaNeural", "Natasha (AU female)", "Australian English"),
    ("en-CA-ClaraNeural", "Clara (CA female)", "Canadian English"),
    ("en-IN-NeerjaNeural", "Neerja (IN female)", "Indian English"),
    ("ko-KR-SunHiNeural", "SunHi (KR female)", "Korean — Kokoro gap"),
    ("ko-KR-InJoonNeural", "InJoon (KR male)", "Korean male"),
    ("vi-VN-HoaiMyNeural", "HoaiMy (VN female)", "Vietnamese"),
    ("vi-VN-NamMinhNeural", "NamMinh (VN male)", "Vietnamese male"),
    ("ja-JP-NanamiNeural", "Nanami (JP female)", "Japanese"),
    ("de-DE-KatjaNeural", "Katja (DE female)", "German — Kokoro gap"),
    ("id-ID-GadisNeural", "Gadis (ID female)", "Indonesian — Kokoro gap"),
]


class EdgeTTSProvider:
    """Microsoft Edge neural TTS. Voice ids are full locale names
    (``en-US-GuyNeural``). ``edge-tts --list-voices`` prints the catalog."""

    id = "edge"
    name = "Edge-TTS (Cloud, free)"
    models = [ModelOption(id=v, name=n, description=d) for v, n, d in _FEATURED]

    DEFAULT_VOICE = "en-US-GuyNeural"

    async def generate(
        self,
        text: str,
        *,
        model: str | None = None,
        voice_clone_path: str | None = None,  # unsupported
        output_path: str,
        rate: str = "+0%",
        pitch: str = "+0Hz",
    ) -> str:
        try:
            import edge_tts
        except ImportError as exc:
            raise RuntimeError(
                "edge-tts not installed. Run: pip install edge-tts"
            ) from exc

        voice = (model or self.DEFAULT_VOICE).strip()
        out = Path(output_path)
        # edge-tts streams mp3; write to a temp .mp3 then convert if .wav asked
        mp3_path = out if out.suffix.lower() == ".mp3" else out.with_suffix(".mp3.tmp")

        audio = bytearray()
        words: list[dict] = []
        comm = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch)
        async for chunk in comm.stream():
            t = chunk.get("type")
            if t == "audio":
                audio.extend(chunk["data"])
            elif t == "WordBoundary":
                start = chunk["offset"] / 1e7  # 100ns ticks → seconds
                words.append({
                    "start": start,
                    "end": start + chunk["duration"] / 1e7,
                    "text": chunk.get("text", ""),
                })

        if not audio:
            raise RuntimeError(f"edge-tts returned no audio (voice={voice})")
        mp3_path.write_bytes(bytes(audio))

        if mp3_path != out:
            # Convert to the requested container (usually .wav for FFmpeg mixing)
            proc = await asyncio.to_thread(
                subprocess.run,
                ["ffmpeg", "-y", "-i", str(mp3_path), "-ar", "24000", str(out)],
                capture_output=True, text=True,
            )
            mp3_path.unlink(missing_ok=True)
            if proc.returncode != 0:
                raise RuntimeError(f"ffmpeg mp3→{out.suffix} failed: {proc.stderr[-400:]}")

        if words:
            out.with_suffix(".words.json").write_text(
                json.dumps(words), encoding="utf-8")
        return str(out)
