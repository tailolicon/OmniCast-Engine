"""Tests for the multi-source TTS stack (VoiceRouter + TTSModule).

Providers are mocked via the registry — no model downloads, no network.
"""

import pytest
from unittest.mock import patch, AsyncMock, MagicMock

from omnicast.media.tts import TTSModule
from omnicast.media.models import TTSRequest, TTSResult, TTSEngine, MediaStatus
from omnicast.media.voice_router import (
    VoiceRouter, VoiceSpec, resolve_channel_voice, pick_voice_for_new_channel,
)
from omnicast.shared.errors import MediaError


# ── Fixtures ──────────────────────────────────────────────────────────────────

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


def _provider(id_: str, ok: bool = True):
    """Mock ITTSProvider: succeeds (echo output_path) or always raises."""
    p = MagicMock()
    p.id = id_
    if ok:
        async def gen(text, *, model=None, voice_clone_path=None, output_path):
            return output_path
    else:
        async def gen(text, *, model=None, voice_clone_path=None, output_path):
            raise RuntimeError(f"{id_} down")
    p.generate = AsyncMock(side_effect=gen)
    return p


# ── VoiceSpec parsing ────────────────────────────────────────────────────────

class TestVoiceSpec:
    def test_parse_basic(self):
        s = VoiceSpec.parse("kokoro:af_heart")
        assert s.provider == "kokoro" and s.voice == "af_heart"

    def test_parse_edge_locale(self):
        s = VoiceSpec.parse("edge:ko-KR-SunHiNeural")
        assert s.provider == "edge" and s.voice == "ko-KR-SunHiNeural"

    def test_legacy_mapping(self):
        assert str(VoiceSpec.parse("kokoro_en_us_v1")) == "kokoro:af_heart"
        # Languages Kokoro doesn't have route to edge
        assert VoiceSpec.parse("kokoro_vi_v1").provider == "edge"
        assert VoiceSpec.parse("kokoro_de_v1").provider == "edge"

    def test_invalid_raises(self):
        with pytest.raises(ValueError):
            VoiceSpec.parse("not-a-spec")

    def test_roundtrip(self):
        assert str(VoiceSpec.parse("xttsv2:/refs/brand.wav")) == "xttsv2:/refs/brand.wav"


# ── Channel resolution ───────────────────────────────────────────────────────

class TestChannelResolution:
    def test_explicit_profile_plus_market_fallback(self):
        chain = resolve_channel_voice(
            {"voice_profile": "kokoro:am_michael", "market": "US"})
        assert str(chain[0]) == "kokoro:am_michael"
        assert len(chain) >= 2  # auto cross-provider fallback appended

    def test_market_defaults_when_unset(self):
        chain = resolve_channel_voice({"market": "KR"})
        assert chain[0].provider == "edge"
        assert "ko-KR" in chain[0].voice

    def test_legacy_profile_in_channel_json(self):
        chain = resolve_channel_voice(
            {"voice_profile": "kokoro_en_us_v1", "market": "US"})
        assert str(chain[0]) == "kokoro:af_heart"

    def test_dedupes_chain(self):
        chain = resolve_channel_voice({
            "voice_profile": "kokoro:af_heart",
            "voice_fallback": ["kokoro:af_heart", "edge:en-US-AriaNeural"],
        })
        assert len([s for s in chain if str(s) == "kokoro:af_heart"]) == 1

    def test_pool_rotation_avoids_taken(self):
        first = pick_voice_for_new_channel("US", set())
        second = pick_voice_for_new_channel("US", {first})
        assert first != second


# ── Router fallback behavior ─────────────────────────────────────────────────

class TestVoiceRouter:
    @pytest.mark.asyncio
    async def test_primary_success(self):
        router = VoiceRouter()
        with patch("omnicast.media.providers.registry.get_tts_provider",
                   side_effect=lambda pid: _provider(pid)):
            res = await router.synthesize("hi", ["kokoro:af_heart"], "/tmp/o.wav")
        assert res.spec.provider == "kokoro"
        assert res.attempts == []

    @pytest.mark.asyncio
    async def test_falls_back_in_order(self):
        router = VoiceRouter()
        providers = {"kokoro": _provider("kokoro", ok=False),
                     "edge": _provider("edge", ok=True)}
        with patch("omnicast.media.providers.registry.get_tts_provider",
                   side_effect=lambda pid: providers[pid]):
            res = await router.synthesize(
                "hi", ["kokoro:af_heart", "edge:en-US-AriaNeural"], "/tmp/o.wav")
        assert res.spec.provider == "edge"
        assert res.attempts == ["kokoro:af_heart"]

    @pytest.mark.asyncio
    async def test_all_fail_raises_no_robot_fallback(self):
        router = VoiceRouter()
        with patch("omnicast.media.providers.registry.get_tts_provider",
                   side_effect=lambda pid: _provider(pid, ok=False)):
            with pytest.raises(MediaError, match="All TTS sources failed"):
                await router.synthesize(
                    "hi", ["kokoro:af_heart", "edge:en-US-AriaNeural"], "/tmp/o.wav")

    @pytest.mark.asyncio
    async def test_empty_chain_raises(self):
        with pytest.raises(MediaError):
            await VoiceRouter().synthesize("hi", [], "/tmp/o.wav")

    @pytest.mark.asyncio
    async def test_unknown_provider_skipped(self):
        router = VoiceRouter()

        def get(pid):
            if pid == "nope":
                raise ValueError("Unknown TTS provider: nope")
            return _provider(pid)

        with patch("omnicast.media.providers.registry.get_tts_provider",
                   side_effect=get):
            res = await router.synthesize(
                "hi", ["nope:x", "kokoro:af_heart"], "/tmp/o.wav")
        assert res.spec.provider == "kokoro"


# ── TTSModule integration (router mocked) ────────────────────────────────────

class TestTTSModule:
    def test_name(self, tts):
        assert tts.name == "tts"

    @pytest.mark.asyncio
    async def test_process_routes_through_router(self, tts):
        fake = MagicMock()
        fake.audio_path = "/tmp/out.wav"
        fake.spec = VoiceSpec.parse("kokoro:af_heart")
        fake.attempts = []
        with patch.object(TTSModule._router, "synthesize",
                          new_callable=AsyncMock, return_value=fake), \
             patch.object(tts, "_normalize_lufs", new_callable=AsyncMock), \
             patch("omnicast.media.tts.measure_duration", return_value=3.2):
            result = await tts._process(
                TTSRequest(text="Hello", voice_profile="kokoro:af_heart"))
        assert result.audio_path == "/tmp/out.wav"
        assert result.engine_used == TTSEngine.KOKORO
        assert result.duration_seconds == pytest.approx(3.2)
        assert result.status == MediaStatus.DONE

    @pytest.mark.asyncio
    async def test_voice_clone_prepends_clone_provider(self, tts):
        captured = {}

        async def fake_synth(text, chain, output_path, **kw):
            captured["chain"] = [str(s) if isinstance(s, VoiceSpec) else s
                                 for s in chain]
            r = MagicMock()
            r.audio_path = output_path
            r.spec = VoiceSpec.parse("xttsv2:/refs/brand.wav")
            r.attempts = []
            return r

        with patch.object(TTSModule._router, "synthesize",
                          side_effect=fake_synth), \
             patch.object(tts, "_normalize_lufs", new_callable=AsyncMock), \
             patch("omnicast.media.tts.measure_duration", return_value=1.0):
            await tts._process(TTSRequest(
                text="Hi", voice_clone="/refs/brand.wav",
                voice_profile="kokoro:af_heart"))
        assert captured["chain"][0] == "xttsv2:/refs/brand.wav"

    @pytest.mark.asyncio
    async def test_router_failure_propagates(self, tts):
        with patch.object(TTSModule._router, "synthesize",
                          new_callable=AsyncMock,
                          side_effect=MediaError("All TTS sources failed")):
            with pytest.raises(MediaError):
                await tts._process(TTSRequest(text="Hi"))


class TestTTSDryRun:
    @pytest.mark.asyncio
    async def test_dry_run_returns_result(self, tts_dry):
        result = await tts_dry.process(TTSRequest(text="Hello world test sentence"))
        assert isinstance(result, TTSResult)
        assert result.status == MediaStatus.DONE
        assert result.duration_seconds > 0

    @pytest.mark.asyncio
    async def test_dry_run_uses_output_path(self, tts_dry):
        result = await tts_dry.process(
            TTSRequest(text="Hi", output_path="/tmp/custom.wav"))
        assert result.audio_path == "/tmp/custom.wav"
