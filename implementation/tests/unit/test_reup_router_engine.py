"""The bridge that lets a dub job use OmniCast's TTS providers.

Before it existed the reup factory knew only `vieneu` and `sapi`, so asking a
dub for a CapCut or Edge voice could not be honoured whatever the preset said.
"""

from __future__ import annotations

import pytest

from omnicast.reup.tts.factory import create_tts_engine
from omnicast.reup.tts.models import VoicePreset
from omnicast.reup.tts.router_engine import VoiceRouterTTSEngine
from omnicast.reup.tts.sapi_engine import SapiTTSEngine
from omnicast.reup.tts.vieneu_engine import VieneuTTSEngine


def _preset(engine: str, voice_id: str = "x", speed: float = 1.0) -> VoicePreset:
    return VoicePreset(
        voice_preset_id="p", name="p", engine=engine, voice_id=voice_id, speed=speed
    )


def test_native_engines_still_win():
    assert isinstance(create_tts_engine(_preset("vieneu")), VieneuTTSEngine)
    assert isinstance(create_tts_engine(_preset("sapi")), SapiTTSEngine)


@pytest.mark.parametrize("provider", ["edge", "capcut", "volcengine", "kokoro"])
def test_omnicast_providers_route_through_the_bridge(provider):
    engine = create_tts_engine(_preset(provider))
    assert isinstance(engine, VoiceRouterTTSEngine)


def test_unknown_engine_is_rejected():
    with pytest.raises(ValueError, match="chua duoc ho tro"):
        create_tts_engine(_preset("not-a-provider"))


def test_placeholder_voice_id_is_refused(tmp_path):
    # "default" is meaningful to VieNeu but meaningless to a router spec, and
    # silently synthesizing some arbitrary voice is how a dub ends up male.
    engine = VoiceRouterTTSEngine("edge")
    with pytest.raises(RuntimeError, match="explicit voice id"):
        engine.synthesize(
            text="xin chào",
            output_path=tmp_path / "o.wav",
            preset=_preset("edge", voice_id="default"),
        )


def test_prosody_offers_both_conventions(monkeypatch, tmp_path):
    # The router filters prosody by name only, so a float `volume` reached Edge
    # and failed with "volume must be str". Pace must go out as a numeric
    # `speed` AND an SSML `rate`, with volume left to the mixdown stage.
    captured: dict = {}

    class _Result:
        audio_path = str(tmp_path / "o.wav")

    class _Router:
        async def synthesize(self, text, specs, output_path, **kwargs):
            captured.update(specs=specs, prosody=kwargs.get("prosody"))
            import wave

            with wave.open(output_path, "wb") as handle:
                handle.setnchannels(1)
                handle.setsampwidth(2)
                handle.setframerate(24000)
                handle.writeframes(b"\0" * 4800)
            return _Result()

    monkeypatch.setattr("omnicast.media.voice_router.VoiceRouter", _Router)
    VoiceRouterTTSEngine("edge").synthesize(
        text="xin chào",
        output_path=tmp_path / "o.wav",
        preset=_preset("edge", voice_id="vi-VN-HoaiMyNeural", speed=0.93),
    )

    assert captured["specs"] == ["edge:vi-VN-HoaiMyNeural"]
    assert captured["prosody"]["speed"] == pytest.approx(0.93)
    assert captured["prosody"]["rate"] == "-7%"
    assert "volume" not in captured["prosody"], "mixdown owns voice level"


def test_neutral_speed_sends_no_rate(monkeypatch, tmp_path):
    captured: dict = {}

    class _Result:
        audio_path = str(tmp_path / "o.wav")

    class _Router:
        async def synthesize(self, text, specs, output_path, **kwargs):
            captured.update(prosody=kwargs.get("prosody"))
            import wave

            with wave.open(output_path, "wb") as handle:
                handle.setnchannels(1)
                handle.setsampwidth(2)
                handle.setframerate(24000)
                handle.writeframes(b"\0" * 2400)
            return _Result()

    monkeypatch.setattr("omnicast.media.voice_router.VoiceRouter", _Router)
    VoiceRouterTTSEngine("edge").synthesize(
        text="xin chào",
        output_path=tmp_path / "o.wav",
        preset=_preset("edge", voice_id="vi-VN-HoaiMyNeural", speed=1.0),
    )
    assert "rate" not in captured["prosody"]
