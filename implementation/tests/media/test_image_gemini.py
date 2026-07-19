"""Tests for GeminiImageProvider.

Provider instantiation + metadata tests run unconditionally.
Real API generate() tests are skipped unless GOOGLE_API_KEY is set.
"""

import os
from pathlib import Path
import pytest

from omnicast.media.providers.image_gemini import GeminiImageProvider, MediaError


class TestGeminiImageProviderMetadata:
    """Tests that don't require an API key."""

    def test_provider_attributes(self):
        """Provider has correct id/name/models even without an API key."""
        provider = GeminiImageProvider()
        assert provider.id == "gemini"
        assert provider.name == "Google Gemini Image"
        assert len(provider.models) == 2
        assert provider.models[0].id == "gemini-2.5-flash-image-preview"

    @pytest.mark.asyncio
    async def test_generate_without_api_key_raises(self, tmp_path, monkeypatch):
        """generate() raises MediaError when GOOGLE_API_KEY is missing."""
        from omnicast.config.settings import get_settings
        get_settings.cache_clear()
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

        provider = GeminiImageProvider()  # must NOT raise
        with pytest.raises(MediaError, match="GOOGLE_API_KEY not configured"):
            await provider.generate(prompt="x", output_path=str(tmp_path / "x.png"))

        get_settings.cache_clear()


@pytest.mark.skipif(
    not os.getenv("GOOGLE_API_KEY"),
    reason="GOOGLE_API_KEY not set (real API call)"
)
class TestGeminiImageProviderRealAPI:
    """Tests requiring a live GOOGLE_API_KEY."""

    @pytest.fixture
    def provider(self):
        return GeminiImageProvider()

    @pytest.mark.asyncio
    async def test_generate_simple_image(self, provider, tmp_path):
        """Test generating a simple image."""
        output_path = tmp_path / "test_image.png"
        
        result = await provider.generate(
            prompt="a red cube on a white background",
            output_path=str(output_path)
        )
        
        # Verify file exists
        assert Path(result).exists()
        assert Path(result).suffix == ".png"
        
        # Verify file has content
        assert Path(result).stat().st_size > 0
    
    @pytest.mark.asyncio
    async def test_generate_with_custom_model(self, provider, tmp_path):
        """Test generating with custom model parameter."""
        output_path = tmp_path / "test_image_custom.png"
        
        result = await provider.generate(
            prompt="a blue circle",
            model="gemini-2.5-flash-image-preview",
            output_path=str(output_path)
        )
        
        assert Path(result).exists()
    
def test_provider_interface_compliance():
    """GeminiImageProvider exposes the IImageProvider structural attributes."""
    assert hasattr(GeminiImageProvider, "id")
    assert hasattr(GeminiImageProvider, "name")
    assert hasattr(GeminiImageProvider, "models")
    assert hasattr(GeminiImageProvider, "generate")
