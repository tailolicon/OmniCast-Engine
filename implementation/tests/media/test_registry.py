"""Tests for provider registry."""

import os
import pytest

from omnicast.media.providers.registry import (
    get_image_provider,
    get_video_provider,
    list_providers,
    register_image_provider,
    register_video_provider,
)
from omnicast.media.providers.interfaces import IImageProvider, IVideoProvider, ModelOption


class TestImageProviderRegistry:
    """Tests for image provider registry."""
    
    def test_get_gemini_image_provider(self):
        """Test getting Gemini image provider (no API key required for instantiation)."""
        provider = get_image_provider("gemini")
        assert provider.id == "gemini"
        assert provider.name == "Google Gemini Image"
    
    def test_get_unknown_image_provider(self):
        """Test that unknown provider raises error."""
        with pytest.raises(ValueError, match="Unknown image provider"):
            get_image_provider("unknown")
    
    def test_register_custom_image_provider(self):
        """Test registering a custom image provider."""
        
        class CustomImageProvider:
            id = "custom"
            name = "Custom Provider"
            models = [ModelOption(id="custom-model", name="Custom Model")]
            
            async def generate(self, prompt: str, *, negative: str = "",
                             model: str | None = None,
                             resolution: tuple[int, int] | None = None,
                             output_path: str) -> str:
                return output_path
        
        custom = CustomImageProvider()
        register_image_provider("custom", custom)
        
        provider = get_image_provider("custom")
        assert provider.id == "custom"
        assert provider.name == "Custom Provider"


class TestVideoProviderRegistry:
    """Tests for video provider registry."""
    
    def test_get_gemini_video_provider(self):
        """Test getting Gemini video provider (no API key required for instantiation)."""
        provider = get_video_provider("gemini")
        assert provider.id == "gemini"
        assert provider.name == "Google Veo"
    
    def test_get_unknown_video_provider(self):
        """Test that unknown provider raises error."""
        with pytest.raises(ValueError, match="Unknown video provider"):
            get_video_provider("unknown")
    
    def test_register_custom_video_provider(self):
        """Test registering a custom video provider."""
        
        class CustomVideoProvider:
            id = "custom"
            name = "Custom Video Provider"
            models = [ModelOption(id="custom-model", name="Custom Model")]
            
            async def convert(self, image_path: str, prompt: str, *,
                            duration: int = 5, model: str | None = None,
                            resolution: tuple[int, int] | None = None,
                            output_path: str) -> str:
                return output_path
        
        custom = CustomVideoProvider()
        register_video_provider("custom", custom)
        
        provider = get_video_provider("custom")
        assert provider.id == "custom"
        assert provider.name == "Custom Video Provider"


class TestListProviders:
    """Tests for listing all providers."""
    
    def test_list_providers_returns_data(self):
        """list_providers always returns provider metadata, regardless of key status."""
        providers = list_providers()
        assert len(providers) >= 2  # at least gemini image + video

        gemini_image = next((p for p in providers if p["id"] == "gemini" and p["category"] == "image"), None)
        assert gemini_image is not None
        assert gemini_image["name"] == "Google Gemini Image"
        assert len(gemini_image["models"]) > 0

        gemini_video = next((p for p in providers if p["id"] == "gemini" and p["category"] == "video"), None)
        assert gemini_video is not None
        assert gemini_video["name"] == "Google Veo"
        assert len(gemini_video["models"]) > 0
