"""Tests for the F5-TTS voice-clone provider (ported from voice-pro stack).

Verify registration + contract without requiring the heavy ``f5-tts`` package.
"""

import pytest

from omnicast.media.providers.registry import get_tts_provider
from omnicast.media.providers.tts_local import F5TTSProvider


class TestF5TTSProvider:
    def test_registered_in_registry(self):
        provider = get_tts_provider("f5tts")
        assert isinstance(provider, F5TTSProvider)

    def test_metadata(self):
        p = F5TTSProvider()
        assert p.id == "f5tts"
        assert "Cloning" in p.name
        assert p.models and p.models[0].id == "F5TTS_v1_Base"

    async def test_requires_voice_clone_path(self):
        p = F5TTSProvider()
        with pytest.raises(ValueError, match="requires voice_clone_path"):
            await p.generate("hello", output_path="out.wav")

    async def test_missing_dependency_raises_clear_error(self, monkeypatch, tmp_path):
        """Without f5-tts installed, generate raises an actionable RuntimeError."""
        import builtins

        real_import = builtins.__import__

        def _block(name, *args, **kwargs):
            if name.startswith("f5_tts"):
                raise ImportError("blocked for test")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", _block)

        ref = tmp_path / "ref.wav"
        ref.write_bytes(b"")
        p = F5TTSProvider()
        with pytest.raises(RuntimeError, match="f5-tts not installed"):
            await p.generate("hello", voice_clone_path=str(ref), output_path=str(tmp_path / "out.wav"))
