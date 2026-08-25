"""CapCut TTS provider — API path + fallback resolution.

The catalog names ByteDance speaker ids. With CAPCUT_TTS_ENABLED (default on)
`generate` calls CapCut's common_task API (vendored SDK). Fallbacks still map
to Volcengine/Edge when the API is off or fails.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from omnicast.media.providers.registry import get_tts_provider
from omnicast.media.providers.tts_capcut import (
    CapCutTTSProvider,
    api_enabled,
    extract_speech_urls,
    load_sdk_catalog,
)
from omnicast.media.voice_router import VoiceSpec


def test_provider_is_registered_under_capcut():
    assert get_tts_provider("capcut").id == "capcut"


def test_vietnamese_female_fallback_is_edge_when_no_volcengine_keys(monkeypatch):
    monkeypatch.delenv("VOLCENGINE_TTS_APPID", raising=False)
    monkeypatch.delenv("VOLCENGINE_TTS_ACCESS_TOKEN", raising=False)
    assert CapCutTTSProvider.resolve_fallback("BV074_streaming") == "edge:vi-VN-HoaiMyNeural"


def test_prefixed_id_fallback_resolves_too(monkeypatch):
    monkeypatch.delenv("VOLCENGINE_TTS_APPID", raising=False)
    monkeypatch.delenv("VOLCENGINE_TTS_ACCESS_TOKEN", raising=False)
    assert (
        CapCutTTSProvider.resolve_fallback("capcut:BV074_streaming")
        == "edge:vi-VN-HoaiMyNeural"
    )


def test_voice_without_an_equivalent_refuses_instead_of_substituting(monkeypatch):
    monkeypatch.delenv("VOLCENGINE_TTS_APPID", raising=False)
    monkeypatch.delenv("VOLCENGINE_TTS_ACCESS_TOKEN", raising=False)
    # Character voices have no legal stand-in; quietly handing back some
    # unrelated narrator would be worse than failing.
    with pytest.raises(RuntimeError, match="no Volcengine/Edge fallback"):
        CapCutTTSProvider.resolve_fallback("en_us_ghostface")


def test_unknown_speaker_id_is_rejected():
    with pytest.raises(RuntimeError, match="no Volcengine/Edge fallback|Unknown"):
        CapCutTTSProvider.resolve_fallback("not_a_real_speaker_xyz")


def test_sdk_catalog_ships_with_vendor():
    voices = load_sdk_catalog()
    assert len(voices) >= 100
    ids = {v["voice_type"] for v in voices}
    assert "BV074_streaming" in ids
    assert "BV421_vivn_streaming" in ids


def test_models_include_sdk_voices():
    ids = {m.id for m in CapCutTTSProvider().models}
    assert "BV074_streaming" in ids
    assert "BV421_vivn_streaming" in ids


def test_every_fallbackable_curated_model_resolves_to_a_parseable_spec(monkeypatch):
    monkeypatch.delenv("VOLCENGINE_TTS_APPID", raising=False)
    monkeypatch.delenv("VOLCENGINE_TTS_ACCESS_TOKEN", raising=False)
    from omnicast.media.capcut_voices import curated_catalog

    for voice in curated_catalog():
        if not voice.get("edge_fallback") and voice["speaker_id"] not in CapCutTTSProvider._VOLCENGINE_EQUIVALENT:
            continue
        spec = VoiceSpec.parse(CapCutTTSProvider.resolve_fallback(voice["speaker_id"]))
        assert spec.provider and spec.voice


def test_spec_parses_as_a_voice_router_chain_entry():
    spec = VoiceSpec.parse("capcut:BV074_streaming")
    assert spec.provider == "capcut"
    assert spec.voice == "BV074_streaming"


def test_extract_speech_urls_from_succeed_payload():
    payload = {
        "audio_subtitles": [
            {
                "speech_url": "https://cdn.example/a.mp3",
                "duration": 1000,
                "speaker_id": "BV074_streaming",
            }
        ],
        "scene": "text_to_speech",
    }
    resp = {
        "data": {
            "tasks": [
                {
                    "status": "succeed",
                    "payload": json.dumps(payload),
                }
            ]
        }
    }
    assert extract_speech_urls(resp) == ["https://cdn.example/a.mp3"]


def test_api_enabled_default_on(monkeypatch):
    monkeypatch.delenv("CAPCUT_TTS_ENABLED", raising=False)
    assert api_enabled() is True
    monkeypatch.setenv("CAPCUT_TTS_ENABLED", "0")
    assert api_enabled() is False


@pytest.mark.asyncio
async def test_generate_uses_api_when_enabled(tmp_path, monkeypatch):
    monkeypatch.setenv("CAPCUT_TTS_ENABLED", "1")
    out = tmp_path / "out.mp3"
    fake_audio = b"ID3" + b"\x00" * 200

    def _fake_synth(text, *, voice, output_path, rate="1.0", timeout=None):
        Path(output_path).write_bytes(fake_audio)
        return str(output_path)

    with patch(
        "omnicast.media.providers.tts_capcut.synthesize_via_capcut_api",
        side_effect=_fake_synth,
    ) as mock_api:
        path = await CapCutTTSProvider().generate(
            "Xin chào",
            model="BV074_streaming",
            output_path=str(out),
        )
    assert path == str(out)
    assert out.read_bytes() == fake_audio
    mock_api.assert_called_once()
    assert mock_api.call_args.kwargs["voice"] == "BV074_streaming"


@pytest.mark.asyncio
async def test_generate_falls_back_to_edge_when_api_disabled(tmp_path, monkeypatch):
    monkeypatch.setenv("CAPCUT_TTS_ENABLED", "0")
    monkeypatch.delenv("VOLCENGINE_TTS_APPID", raising=False)
    monkeypatch.delenv("VOLCENGINE_TTS_ACCESS_TOKEN", raising=False)
    out = tmp_path / "out.wav"

    edge = MagicMock()

    async def _edge_gen(text, *, model=None, voice_clone_path=None, output_path, **kw):
        Path(output_path).write_bytes(b"RIFFxxxxWAVEfmt ")
        return str(output_path)

    edge.generate = _edge_gen
    # signature filter needs a real function signature
    edge.generate.__signature__ = None  # type: ignore[attr-defined]

    with patch(
        "omnicast.media.providers.registry.get_tts_provider",
        return_value=edge,
    ):
        # _supported_prosody inspects signature — give a clean async fn
        async def generate(text, *, model=None, voice_clone_path=None, output_path, rate="+0%", pitch="+0Hz", volume="+0%"):
            Path(output_path).write_bytes(b"RIFFxxxxWAVEfmt ")
            return str(output_path)

        edge.generate = generate
        path = await CapCutTTSProvider().generate(
            "hello",
            model="BV074_streaming",
            output_path=str(out),
        )
    assert Path(path).exists()
