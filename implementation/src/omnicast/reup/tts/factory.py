from __future__ import annotations

from pathlib import Path

from .base import TTSEngine
from .models import VoicePreset
from .sapi_engine import SapiTTSEngine
from .vieneu_engine import VieneuTTSEngine


def create_tts_engine(preset: VoicePreset, *, project_root: Path | None = None) -> TTSEngine:
    engine_name = preset.engine.strip().lower()
    if engine_name == "sapi":
        return SapiTTSEngine()
    if engine_name == "vieneu":
        return VieneuTTSEngine(project_root=project_root)

    # Anything else is treated as an OmniCast provider id (edge, capcut,
    # volcengine, kokoro, piper, chatterbox…). Without this the dub pipeline
    # could only ever use the two engines the upstream desktop app shipped.
    from omnicast.media.providers.registry import get_tts_provider

    from .router_engine import VoiceRouterTTSEngine

    try:
        get_tts_provider(engine_name)
    except Exception as exc:
        raise ValueError(
            f"Engine TTS chua duoc ho tro: {preset.engine} ({exc})"
        ) from exc
    return VoiceRouterTTSEngine(engine_name)
