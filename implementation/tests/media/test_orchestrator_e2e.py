"""End-to-end tests for orchestrator with provider system.

These tests verify that the orchestrator correctly uses the provider system
instead of the old placeholder modules.
"""

import os
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from omnicast.media.orchestrator import MediaPipelineOrchestrator
from omnicast.media.models import ImageGenResult, VideoGenResult
from omnicast.media.style_guide import StyleGuide
from omnicast.media.prompt_builder import build_full_image_prompt, build_full_video_prompt
from omnicast.models.schemas import BrandConfig


@pytest.mark.skipif(
    not os.getenv("GOOGLE_API_KEY"),
    reason="GOOGLE_API_KEY not set"
)
class TestOrchestratorWithProviders:
    """Tests for orchestrator using real providers."""
    
    @pytest.fixture
    def brand_config(self):
        """Create a test brand config."""
        return BrandConfig(
            channel_id="test_channel",
            voice_profile="default",
            use_video_gen=False,  # Skip video gen for basic test
            music_bpm_range=(120, 140),
        )
    
    @pytest.mark.asyncio
    async def test_run_images_uses_provider(self, brand_config, tmp_path):
        """Test that _run_images uses the provider system."""
        orchestrator = MediaPipelineOrchestrator()
        
        # Mock the provider to avoid actual API calls
        with patch('omnicast.media.orchestrator.get_image_provider') as mock_get_provider:
            mock_provider = AsyncMock()
            mock_provider.generate.return_value = str(tmp_path / "scene_000.png")
            mock_get_provider.return_value = mock_provider
            
            prompts = ["a red cube", "a blue sphere"]
            results = await orchestrator._run_images(prompts, brand_config, str(tmp_path))
            
            # Verify provider was called
            assert mock_get_provider.called
            assert mock_provider.generate.call_count == 2
            
            # Verify results
            assert len(results) == 2
            assert all(isinstance(r, ImageGenResult) for r in results)
    
    @pytest.mark.asyncio
    async def test_run_video_gen_uses_provider(self, brand_config, tmp_path):
        """Test that _run_video_gen uses the provider system."""
        orchestrator = MediaPipelineOrchestrator()
        brand_config.use_video_gen = True
        
        # Mock the provider
        with patch('omnicast.media.orchestrator.get_video_provider') as mock_get_provider:
            mock_provider = AsyncMock()
            mock_provider.convert.return_value = str(tmp_path / "clip_000.mp4")
            mock_get_provider.return_value = mock_provider
            
            prompts = ["a red cube", "a blue sphere"]
            images = [
                ImageGenResult(image_path=str(tmp_path / "scene_000.png"), prompt="a red cube"),
                ImageGenResult(image_path=str(tmp_path / "scene_001.png"), prompt="a blue sphere"),
            ]
            
            results = await orchestrator._run_video_gen(prompts, images, brand_config, str(tmp_path))
            
            # Verify provider was called
            assert mock_get_provider.called
            assert mock_provider.convert.call_count == 2
            
            # Verify results
            assert len(results) == 2
            assert all(isinstance(r, VideoGenResult) for r in results)


class TestOrchestratorWithMockProviders:
    """Tests for orchestrator using mock providers (no API key required)."""
    
    @pytest.fixture
    def brand_config(self):
        """Create a test brand config."""
        return BrandConfig(
            channel_id="test_channel",
            voice_profile="default",
            use_video_gen=False,
            music_bpm_range=(120, 140),
        )
    
    @pytest.fixture
    def style_guide(self):
        """Create a test style guide."""
        return StyleGuide(
            tone="professional",
            color_palette=["#1A1A2E", "#E94560"],
            tempo="medium",
            camera_style="static documentary"
        )
    
    @pytest.mark.asyncio
    async def test_run_images_handles_provider_failure(self, brand_config, tmp_path):
        """Test that _run_images handles provider failures gracefully."""
        orchestrator = MediaPipelineOrchestrator()
        
        with patch('omnicast.media.orchestrator.get_image_provider') as mock_get_provider:
            mock_provider = AsyncMock()
            mock_provider.generate.side_effect = Exception("API error")
            mock_get_provider.return_value = mock_provider
            
            prompts = ["a red cube", "a blue sphere"]
            results = await orchestrator._run_images(prompts, brand_config, str(tmp_path))
            
            # Should return results with empty paths for failed generations
            assert len(results) == 2
            assert all(r.image_path == "" for r in results)
    
    @pytest.mark.asyncio
    async def test_run_images_uses_style_guide(self, brand_config, style_guide, tmp_path):
        """Test that _run_images uses style guide to build full prompts."""
        orchestrator = MediaPipelineOrchestrator()
        
        with patch('omnicast.media.orchestrator.get_image_provider') as mock_get_provider:
            mock_provider = AsyncMock()
            mock_provider.generate.return_value = str(tmp_path / "scene_000.png")
            mock_get_provider.return_value = mock_provider
            
            prompts = ["a red cube"]
            results = await orchestrator._run_images(prompts, brand_config, str(tmp_path), style_guide)
            
            # Verify provider was called with full prompt
            assert mock_provider.generate.called
            call_args = mock_provider.generate.call_args
            full_prompt = call_args.kwargs.get('prompt', call_args.args[0] if call_args.args else None)
            assert full_prompt is not None
            # Should contain style guide elements
            assert "professional" in full_prompt.lower() or "Professional photography" in full_prompt
    
    @pytest.mark.asyncio
    async def test_run_video_gen_skips_missing_images(self, tmp_path):
        """Test that _run_video_gen skips scenes with missing images."""
        orchestrator = MediaPipelineOrchestrator()
        brand_config = BrandConfig(
            channel_id="test_channel",
            voice_profile="default",
            use_video_gen=True,  # Enable video gen
            music_bpm_range=(120, 140),
        )
        
        with patch('omnicast.media.orchestrator.get_video_provider') as mock_get_provider:
            mock_provider = AsyncMock()
            mock_provider.convert.return_value = str(tmp_path / "clip_000.mp4")
            mock_get_provider.return_value = mock_provider
            
            prompts = ["a red cube", "a blue sphere"]
            images = [
                ImageGenResult(image_path="", prompt="a red cube"),  # Missing image
                ImageGenResult(image_path=str(tmp_path / "scene_001.png"), prompt="a blue sphere"),
            ]
            
            results = await orchestrator._run_video_gen(prompts, images, brand_config, str(tmp_path))
            
            # Provider should only be called once (for the second scene)
            assert mock_provider.convert.call_count == 1
            assert len(results) == 2
    
    @pytest.mark.asyncio
    async def test_run_video_gen_uses_style_guide(self, style_guide, tmp_path):
        """Test that _run_video_gen uses style guide to build full prompts."""
        orchestrator = MediaPipelineOrchestrator()
        brand_config = BrandConfig(
            channel_id="test_channel",
            voice_profile="default",
            use_video_gen=True,  # Enable video gen
            music_bpm_range=(120, 140),
        )
        
        with patch('omnicast.media.orchestrator.get_video_provider') as mock_get_provider:
            mock_provider = AsyncMock()
            mock_provider.convert.return_value = str(tmp_path / "clip_000.mp4")
            mock_get_provider.return_value = mock_provider
            
            prompts = ["a red cube"]
            images = [ImageGenResult(image_path=str(tmp_path / "scene_000.png"), prompt="a red cube")]
            
            results = await orchestrator._run_video_gen(prompts, images, brand_config, str(tmp_path), style_guide)
            
            # Verify provider was called with full prompt
            assert mock_provider.convert.called
            call_args = mock_provider.convert.call_args
            full_prompt = call_args.kwargs.get('prompt', call_args.args[1] if len(call_args.args) > 1 else None)
            assert full_prompt is not None
            # Should contain style guide elements
            assert "static documentary" in full_prompt.lower() or "cinematic" in full_prompt.lower()
