"""Volcengine (Doubao seed-tts-2.0) provider — the real ByteDance voice path.

The `capcut:` specs route here when credentials exist, and fall back to Edge
when they do not. That switch is the thing worth pinning: an operator with keys
must get the ByteDance voice, and one without must still get audio rather than
an exception.
"""

from __future__ import annotations

import pytest

from omnicast.media.providers.registry import get_tts_provider
from omnicast.media.providers.tts_capcut import CapCutTTSProvider
from omnicast.media.providers.tts_volcengine import (
    DEFAULT_SPEAKER,
    VolcengineTTSProvider,
    load_credentials,
)
from omnicast.media.voice_router import VoiceSpec


@pytest.fixture
def with_keys(monkeypatch):
    monkeypatch.setenv("VOLCENGINE_TTS_APPID", "test-app")
    monkeypatch.setenv("VOLCENGINE_TTS_ACCESS_TOKEN", "test-token")


@pytest.fixture
def without_keys(monkeypatch):
    monkeypatch.delenv("VOLCENGINE_TTS_APPID", raising=False)
    monkeypatch.delenv("VOLCENGINE_TTS_ACCESS_TOKEN", raising=False)
    # Settings may still carry a key; blank it so the test is deterministic.
    monkeypatch.setattr(
        "omnicast.media.providers.tts_volcengine.load_credentials",
        lambda: ("", ""),
    )


def test_provider_is_registered():
    assert get_tts_provider("volcengine").id == "volcengine"


def test_credentials_come_from_the_environment(with_keys):
    assert load_credentials() == ("test-app", "test-token")


@pytest.mark.asyncio
async def test_health_reports_missing_credentials(without_keys, monkeypatch):
    monkeypatch.delenv("VOLCENGINE_TTS_APPID", raising=False)
    monkeypatch.delenv("VOLCENGINE_TTS_ACCESS_TOKEN", raising=False)
    health = await VolcengineTTSProvider().health_check()
    assert health["healthy"] is False
    assert "VOLCENGINE_TTS_APPID" in health["detail"]


@pytest.mark.asyncio
async def test_generate_refuses_without_credentials(without_keys, tmp_path):
    from omnicast.media.providers.tts_volcengine import VolcengineCredentialsMissing

    with pytest.raises(VolcengineCredentialsMissing):
        await VolcengineTTSProvider().generate(
            "xin chào", output_path=str(tmp_path / "out.wav")
        )


def test_default_speaker_is_in_the_advertised_catalog():
    assert DEFAULT_SPEAKER in {m.id for m in VolcengineTTSProvider.models}


def test_full_seed_tts_catalog_is_loaded():
    from omnicast.media.providers.tts_volcengine import list_speakers, resolve_speaker

    speakers = list_speakers()
    # pyvideotrans doubao2.json ships 102 unique speaker ids.
    assert len(speakers) >= 100
    assert DEFAULT_SPEAKER in {s["speaker_id"] for s in speakers}
    assert resolve_speaker("Vivi 2.0") == DEFAULT_SPEAKER
    assert resolve_speaker(DEFAULT_SPEAKER) == DEFAULT_SPEAKER


def test_capcut_prefers_bytedance_when_keys_are_present(with_keys):
    # The point of the whole exercise: a real CapCut-family voice, not a stand-in.
    resolved = CapCutTTSProvider.resolve("BV074_streaming")
    assert resolved.startswith("volcengine:")
    assert VoiceSpec.parse(resolved).provider == "volcengine"


def test_capcut_falls_back_to_edge_without_keys(without_keys):
    assert CapCutTTSProvider.resolve("BV074_streaming") == "edge:vi-VN-HoaiMyNeural"


def test_every_volcengine_equivalent_names_a_known_speaker(with_keys):
    advertised = {m.id for m in VolcengineTTSProvider.models}
    for capcut_id, speaker in CapCutTTSProvider._VOLCENGINE_EQUIVALENT.items():
        resolved = CapCutTTSProvider.resolve(capcut_id)
        assert resolved == f"volcengine:{speaker}"
        assert speaker in advertised, f"{capcut_id} points at an unlisted speaker"
