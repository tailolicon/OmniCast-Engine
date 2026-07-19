"""Tests for prompt builder.

Tests golden output for 3 cases: empty guide, partial guide, full guide.
"""

import pytest

from omnicast.media.style_guide import StyleGuide
from omnicast.media.prompt_builder import (
    build_image_style_prefix,
    build_video_style_prefix,
    build_full_image_prompt,
    build_full_video_prompt,
    format_style_guide_for_prompt,
)


class TestImageStylePrefix:
    """Tests for image style prefix builder."""
    
    def test_empty_guide(self):
        """Test with empty style guide."""
        guide = StyleGuide()
        prefix = build_image_style_prefix(guide)
        
        # Should have base photorealistic instruction
        assert "Professional photography" in prefix
        assert "natural lighting" in prefix
    
    def test_partial_guide_colors(self):
        """Test with only color palette."""
        guide = StyleGuide(color_palette=["#FF0000", "#00FF00"])
        prefix = build_image_style_prefix(guide)
        
        assert "red and green" in prefix.lower()
        assert "color palette" in prefix.lower()
    
    def test_partial_guide_tone(self):
        """Test with only tone."""
        guide = StyleGuide(tone="energetic")
        prefix = build_image_style_prefix(guide)
        
        assert "dynamic" in prefix.lower()
        assert "high contrast" in prefix.lower()
    
    def test_full_guide(self):
        """Test with all fields populated."""
        guide = StyleGuide(
            tone="professional",
            color_palette=["#1A1A2E", "#E94560"],
            tempo="slow"
        )
        prefix = build_image_style_prefix(guide)
        
        assert "Professional photography" in prefix
        assert "clean composition" in prefix.lower()
        assert "steady composition" in prefix.lower()


class TestVideoStylePrefix:
    """Tests for video style prefix builder."""
    
    def test_empty_guide(self):
        """Test with empty style guide."""
        guide = StyleGuide()
        prefix = build_video_style_prefix(guide)
        
        # Should be empty for no guide
        assert prefix == ""
    
    def test_camera_style_only(self):
        """Test with only camera style."""
        guide = StyleGuide(camera_style="static documentary")
        prefix = build_video_style_prefix(guide)
        
        assert "static documentary" in prefix
    
    def test_tempo_only(self):
        """Test with only tempo."""
        guide = StyleGuide(tempo="fast")
        prefix = build_video_style_prefix(guide)
        
        assert "quick motion" in prefix.lower()
        assert "dynamic camera" in prefix.lower()
    
    def test_full_guide(self):
        """Test with all fields populated."""
        guide = StyleGuide(
            camera_style="dynamic handheld",
            tempo="medium",
            tone="calm"
        )
        prefix = build_video_style_prefix(guide)
        
        assert "dynamic handheld" in prefix
        assert "steady camera" in prefix.lower()
        assert "gentle pacing" in prefix.lower()


class TestFullImagePrompt:
    """Tests for full image prompt builder."""
    
    def test_with_empty_guide(self):
        """Test full prompt with empty guide."""
        guide = StyleGuide()
        prompt = build_full_image_prompt("a red cube on white background", guide)
        
        assert "a red cube on white background" in prompt
        assert "Professional photography" in prompt
        assert "natural lighting" in prompt
    
    def test_with_custom_instruction(self):
        """Test with custom instruction override."""
        guide = StyleGuide()
        custom = "Use bright colors and high contrast"
        prompt = build_full_image_prompt("a blue sphere", guide, custom)
        
        assert custom in prompt
        assert "a blue sphere" in prompt
    
    def test_with_full_guide(self):
        """Test with full style guide."""
        guide = StyleGuide(
            tone="energetic",
            color_palette=["#FF0000"],
            tempo="fast"
        )
        prompt = build_full_image_prompt("a green triangle", guide)
        
        assert "a green triangle" in prompt
        assert "dynamic" in prompt.lower()
        assert "red" in prompt.lower()


class TestFullVideoPrompt:
    """Tests for full video prompt builder."""
    
    def test_with_empty_guide(self):
        """Test full prompt with empty guide."""
        guide = StyleGuide()
        prompt = build_full_video_prompt("slow zoom in", guide)
        
        assert "slow zoom in" in prompt
        assert "subtle natural motion" in prompt.lower()
    
    def test_with_custom_instruction(self):
        """Test with custom instruction override."""
        guide = StyleGuide()
        custom = "Fast cuts and dynamic movement"
        prompt = build_full_video_prompt("pan left", guide, custom)
        
        assert custom in prompt
        assert "pan left" in prompt
    
    def test_with_full_guide(self):
        """Test with full style guide."""
        guide = StyleGuide(
            camera_style="smooth dolly",
            tempo="slow",
            tone="professional"
        )
        prompt = build_full_video_prompt("gentle rotation", guide)
        
        assert "gentle rotation" in prompt
        assert "smooth dolly" in prompt.lower()
        assert "smooth professional" in prompt.lower()


class TestFormatStyleGuide:
    """Tests for style guide markdown formatter."""
    
    def test_empty_guide(self):
        """Test with empty guide."""
        guide = StyleGuide()
        formatted = format_style_guide_for_prompt(guide)
        
        assert "## Project Style Guide" in formatted
        # Should only have header
        lines = [l for l in formatted.split("\n") if l and not l.startswith("#")]
        assert len(lines) == 0
    
    def test_partial_guide(self):
        """Test with partial fields."""
        guide = StyleGuide(
            tone="playful",
            color_palette=["#FF0000", "#00FF00"]
        )
        formatted = format_style_guide_for_prompt(guide)
        
        assert "**Tone:** playful" in formatted
        assert "**Color Palette:** #FF0000, #00FF00" in formatted
    
    def test_full_guide(self):
        """Test with all fields."""
        guide = StyleGuide(
            tone="professional",
            color_palette=["#1A1A2E", "#E94560"],
            tempo="medium",
            camera_style="static documentary",
            brand_voice="Authoritative but approachable",
            must_include=["charts", "data visualization"],
            must_avoid=["stock footage", "generic images"]
        )
        formatted = format_style_guide_for_prompt(guide)
        
        assert "**Tone:** professional" in formatted
        assert "**Color Palette:** #1A1A2E, #E94560" in formatted
        assert "**Tempo:** medium-paced" in formatted
        assert "**Camera Style:** static documentary" in formatted
        assert "**Brand Voice:** Authoritative but approachable" in formatted
        assert "**Must Include:** charts, data visualization" in formatted
        assert "**Must Avoid:** stock footage, generic images" in formatted
