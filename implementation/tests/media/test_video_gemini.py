"""Tests for GeminiVideoProvider.

These tests require a valid GOOGLE_API_KEY and Veo access (paid tier).
They are skipped by default unless explicitly enabled.
"""

import os
import pytest

from omnicast.media.providers.video_gemini import GeminiVideoProvider, MediaError


class TestGeminiVideoProviderUnit:
    """Unit tests that don't require an API key."""

    @pytest.fixture
    def provider(self):
        return GeminiVideoProvider()  # must NOT raise

    def test_provider_attributes(self, provider):
        assert provider.id == "gemini"
        assert provider.name == "Google Veo"
        assert len(provider.models) == 2
        assert provider.models[0].id == "veo-3.0-generate-001"

    def test_clamp_duration(self, provider):
        # Ties round DOWN (matches AutoVio's strict-less-than reduce).
        assert provider._clamp_duration(3) == 4
        assert provider._clamp_duration(4) == 4
        assert provider._clamp_duration(5) == 4   # tie 4|6 -> 4
        assert provider._clamp_duration(6) == 6
        assert provider._clamp_duration(7) == 6   # tie 6|8 -> 6
        assert provider._clamp_duration(8) == 8
        assert provider._clamp_duration(10) == 8

    def test_determine_aspect_ratio(self, provider):
        assert provider._determine_aspect_ratio((1080, 1920)) == "9:16"
        assert provider._determine_aspect_ratio((1920, 1080)) == "16:9"
        assert provider._determine_aspect_ratio((1080, 1080)) == "1:1"
        assert provider._determine_aspect_ratio(None) is None


@pytest.mark.skipif(
    not (os.getenv("GOOGLE_API_KEY") and os.getenv("TEST_VEO_VIDEO_GEN") == "1"),
    reason="GOOGLE_API_KEY + TEST_VEO_VIDEO_GEN=1 required (Veo is paid tier)"
)
class TestGeminiVideoProviderRealAPI:
    """Tests requiring live Veo API access."""

    @pytest.fixture
    def provider(self):
        return GeminiVideoProvider()

    @pytest.mark.asyncio
    async def test_convert_simple_video(self, provider, tmp_path):
        pytest.skip("Requires actual image file - manual testing only")


def test_provider_interface_compliance():
    """Test that GeminiVideoProvider implements IVideoProvider protocol."""
    from omnicast.media.providers.interfaces import IVideoProvider
    
    # Verify it has the required protocol attributes
    assert hasattr(GeminiVideoProvider, "id")
    assert hasattr(GeminiVideoProvider, "name")
    assert hasattr(GeminiVideoProvider, "models")
    assert hasattr(GeminiVideoProvider, "convert")


@pytest.mark.asyncio
async def test_convert_without_api_key_raises(tmp_path, monkeypatch):
    """convert() raises MediaError when GOOGLE_API_KEY is missing (deferred validation)."""
    from omnicast.config.settings import get_settings

    get_settings.cache_clear()
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

    provider = GeminiVideoProvider()  # must NOT raise
    # Settings also read `.env`, so clearing the env var alone left a real key
    # in place wherever one exists — patch the loaded settings object.
    monkeypatch.setattr(provider.settings, "google_api_key", "", raising=False)
    with pytest.raises(MediaError, match="GOOGLE_API_KEY not configured"):
        await provider.convert(
            image_path=str(tmp_path / "x.png"),
            prompt="x",
            output_path=str(tmp_path / "y.mp4"),
        )

    get_settings.cache_clear()
