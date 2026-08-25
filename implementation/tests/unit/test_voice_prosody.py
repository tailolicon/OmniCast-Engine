"""Prosody reaches the providers that understand it — and only those."""

from __future__ import annotations

import pytest

from omnicast.media.voice_router import VoiceRouter, _supported_prosody


class EdgeLike:
    """Signature-compatible stand-in for the Edge provider."""

    def __init__(self):
        self.seen: dict = {}

    async def generate(self, text, *, model=None, voice_clone_path=None,
                       output_path="", rate="+0%", pitch="+0Hz",
                       volume="+0%") -> str:
        self.seen = {"rate": rate, "pitch": pitch, "volume": volume}
        return output_path


class KokoroLike:
    """Numeric `speed`, no SSML strings — the vocabulary mismatch that made a
    single shared prosody dict raise TypeError before it was filtered."""

    def __init__(self):
        self.seen: dict = {}

    async def generate(self, text, *, model=None, voice_clone_path=None,
                       output_path="", speed=1.0) -> str:
        self.seen = {"speed": speed}
        return output_path


class KwargsLike:
    async def generate(self, text, **kwargs) -> str:
        return kwargs.get("output_path", "")


class TestSupportedProsody:
    def test_edge_keys_pass_through(self):
        assert _supported_prosody(EdgeLike(), {"rate": "+8%"}) == {"rate": "+8%"}

    def test_unknown_key_is_dropped_not_raised(self):
        assert _supported_prosody(KokoroLike(), {"rate": "+8%"}) == {}

    def test_each_provider_gets_its_own_vocabulary(self):
        both = {"rate": "+8%", "speed": 1.2}
        assert _supported_prosody(EdgeLike(), both) == {"rate": "+8%"}
        assert _supported_prosody(KokoroLike(), both) == {"speed": 1.2}

    def test_var_keyword_provider_receives_everything(self):
        assert _supported_prosody(KwargsLike(), {"rate": "+8%"}) == {"rate": "+8%"}

    def test_no_prosody_means_no_kwargs(self):
        assert _supported_prosody(EdgeLike(), None) == {}
        assert _supported_prosody(EdgeLike(), {}) == {}


class TestRouterPlumbing:
    @pytest.mark.asyncio
    async def test_router_applies_prosody(self, monkeypatch, tmp_path):
        provider = EdgeLike()
        monkeypatch.setattr(
            "omnicast.media.providers.registry.get_tts_provider",
            lambda _id: provider,
        )
        await VoiceRouter().synthesize(
            "hello", ["edge:en-US-GuyNeural"], str(tmp_path / "a.wav"),
            prosody={"rate": "-6%", "pitch": "-2Hz"},
        )
        assert provider.seen["rate"] == "-6%"
        assert provider.seen["pitch"] == "-2Hz"

    @pytest.mark.asyncio
    async def test_default_still_neutral(self, monkeypatch, tmp_path):
        provider = EdgeLike()
        monkeypatch.setattr(
            "omnicast.media.providers.registry.get_tts_provider",
            lambda _id: provider,
        )
        await VoiceRouter().synthesize(
            "hello", ["edge:en-US-GuyNeural"], str(tmp_path / "a.wav"))
        assert provider.seen == {"rate": "+0%", "pitch": "+0Hz", "volume": "+0%"}
