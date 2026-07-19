"""Tests for VisualDirectorAgent.

Tests the new enrich() method for AI media gen field population.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from omnicast.agents.visual_director import VisualDirectorAgent
from omnicast.models.script import ScriptDraft, ScriptSegment, ScriptScene, TopicBrief
from omnicast.models.enums import Market
from omnicast.media.style_guide import StyleGuide
from omnicast.llm.client import LLMResponse


@pytest.fixture
def mock_llm():
    """Create a mock LLM client."""
    llm = MagicMock()
    llm.complete = AsyncMock()
    return llm


@pytest.fixture
def visual_director(mock_llm):
    """Create VisualDirectorAgent instance."""
    return VisualDirectorAgent(mock_llm)


@pytest.fixture
def style_guide():
    """Create a test style guide."""
    return StyleGuide(
        tone="professional",
        color_palette=["#1A1A2E", "#E94560"],
        tempo="medium",
        camera_style="static documentary",
        brand_voice="Authoritative but approachable"
    )


@pytest.fixture
def script_draft():
    """Create a test ScriptDraft with scenes."""
    return ScriptDraft(
        variant_id="test-variant-1",
        brief_title="Test Brief",
        hook="This is the hook",
        segments=[
            ScriptSegment(
                index=0,
                heading="Introduction",
                content="This is the narration",
                estimated_duration_seconds=10,
                scenes=[
                    ScriptScene(
                        voiceover="Scene 1 voiceover",
                        visual_prompt="Scene 1 visual",
                        sfx=None,
                        duration_s=3.0
                    ),
                    ScriptScene(
                        voiceover="Scene 2 voiceover",
                        visual_prompt="Scene 2 visual",
                        sfx="whoosh",
                        duration_s=4.0
                    ),
                    ScriptScene(
                        voiceover="Scene 3 voiceover",
                        visual_prompt="Scene 3 visual",
                        sfx=None,
                        duration_s=3.0
                    )
                ]
            )
        ],
        outro="This is the outro"
    )


class TestVisualDirectorEnrich:
    """Tests for the enrich() method."""
    
    @pytest.mark.asyncio
    async def test_enrich_populates_new_fields(self, visual_director, script_draft, style_guide, mock_llm):
        """Test that enrich() populates the 5 new AI media gen fields."""
        # Mock LLM response
        mock_response = LLMResponse(
            content='[{"scene_idx": 0, "image_prompt": "Photorealistic scene 1", "negative_prompt": "blurry", "video_prompt": "Slow zoom", "transition": "cut"}, '
                   '{"scene_idx": 1, "image_prompt": "Photorealistic scene 2", "negative_prompt": "distorted", "video_prompt": "Pan right", "transition": "fade"}, '
                   '{"scene_idx": 2, "image_prompt": "Photorealistic scene 3", "negative_prompt": "watermark", "video_prompt": "Static", "transition": "dissolve"}]',
            model="deepseek-chat",
            input_tokens=100,
            output_tokens=200,
            cost_usd=0.001,
            stop_reason="end_turn",
        )
        mock_llm.complete.return_value = mock_response
        
        enriched_draft = await visual_director.enrich(script_draft, style_guide)
        
        # Verify new fields are populated
        assert len(enriched_draft.segments) == 1
        scenes = enriched_draft.segments[0].scenes
        assert len(scenes) == 3
        
        # Scene 0
        assert scenes[0].image_prompt == "Photorealistic scene 1"
        assert scenes[0].negative_prompt == "blurry"
        assert scenes[0].video_prompt == "Slow zoom"
        assert scenes[0].transition == "cut"
        
        # Scene 1
        assert scenes[1].image_prompt == "Photorealistic scene 2"
        assert scenes[1].negative_prompt == "distorted"
        assert scenes[1].video_prompt == "Pan right"
        assert scenes[1].transition == "fade"
        
        # Scene 2
        assert scenes[2].image_prompt == "Photorealistic scene 3"
        assert scenes[2].negative_prompt == "watermark"
        assert scenes[2].video_prompt == "Static"
        assert scenes[2].transition == "dissolve"
    
    @pytest.mark.asyncio
    async def test_enrich_preserves_original_fields(self, visual_director, script_draft, style_guide, mock_llm):
        """Test that enrich() preserves original voiceover, visual_prompt, sfx."""
        mock_response = LLMResponse(
            content='[{"scene_idx": 0, "image_prompt": "New image prompt", "negative_prompt": "", "video_prompt": "", "transition": "cut"}]',
            model="deepseek-chat",
            input_tokens=100,
            output_tokens=50,
            cost_usd=0.001,
            stop_reason="end_turn",
        )
        mock_llm.complete.return_value = mock_response
        
        enriched_draft = await visual_director.enrich(script_draft, style_guide)
        
        scene = enriched_draft.segments[0].scenes[0]
        assert scene.voiceover == "Scene 1 voiceover"
        assert scene.visual_prompt == "Scene 1 visual"
        assert scene.sfx is None
        assert scene.duration_s == 3.0
    
    @pytest.mark.asyncio
    async def test_enrich_with_brief_context(self, visual_director, script_draft, style_guide, mock_llm):
        """Test that enrich() includes brief context in prompt."""
        brief = TopicBrief(
            title="Test Brief Title",
            niche="finance",
            market=Market.US,
            brand_voice="Professional financial advice"
        )
        
        mock_response = LLMResponse(
            content='[{"scene_idx": 0, "image_prompt": "Test", "negative_prompt": "", "video_prompt": "", "transition": "cut"}]',
            model="deepseek-chat",
            input_tokens=100,
            output_tokens=50,
            cost_usd=0.001,
            stop_reason="end_turn",
        )
        mock_llm.complete.return_value = mock_response
        
        await visual_director.enrich(script_draft, style_guide, brief)
        
        # Verify LLM was called
        assert mock_llm.complete.called
    
    @pytest.mark.asyncio
    async def test_enrich_handles_llm_failure(self, visual_director, script_draft, style_guide, mock_llm):
        """Test that enrich() returns original draft on LLM failure."""
        mock_llm.complete.side_effect = Exception("LLM error")
        
        enriched_draft = await visual_director.enrich(script_draft, style_guide)
        
        # Should return original draft unchanged
        assert enriched_draft.variant_id == script_draft.variant_id
        assert len(enriched_draft.segments) == len(script_draft.segments)
        # New fields should be empty (defaults)
        scene = enriched_draft.segments[0].scenes[0]
        assert scene.image_prompt == ""
        assert scene.negative_prompt == ""
        assert scene.video_prompt == ""
    
    @pytest.mark.asyncio
    async def test_enrich_handles_malformed_json(self, visual_director, script_draft, style_guide, mock_llm):
        """Test that enrich() handles malformed JSON response."""
        mock_response = LLMResponse(
            content="This is not valid JSON",
            model="deepseek-chat",
            input_tokens=100,
            output_tokens=50,
            cost_usd=0.001,
            stop_reason="end_turn",
        )
        mock_llm.complete.return_value = mock_response
        
        enriched_draft = await visual_director.enrich(script_draft, style_guide)
        
        # Should return original draft unchanged
        scene = enriched_draft.segments[0].scenes[0]
        assert scene.image_prompt == ""
        assert scene.negative_prompt == ""
    
    @pytest.mark.asyncio
    async def test_enrich_handles_segment_without_scenes(self, visual_director, style_guide, mock_llm):
        """Test that enrich() skips segments without scenes."""
        draft = ScriptDraft(
            variant_id="test-variant-2",
            brief_title="Test Brief",
            hook="Hook",
            segments=[
                ScriptSegment(
                    index=0,
                    heading="No Scenes",
                    content="Content without scenes",
                    estimated_duration_seconds=10,
                    scenes=[]  # No scenes
                )
            ],
            outro="Outro"
        )
        
        enriched_draft = await visual_director.enrich(draft, style_guide)
        
        # Should not call LLM for segment without scenes
        assert not mock_llm.complete.called
        assert len(enriched_draft.segments) == 1


class TestEnrichPromptBuilder:
    """Tests for _build_enrich_prompt method."""
    
    def test_build_enrich_prompt_includes_style_guide(self, visual_director, style_guide):
        """Test that prompt includes formatted style guide."""
        seg = ScriptSegment(
            index=0,
            heading="Test",
            content="Content",
            estimated_duration_seconds=10,
            scenes=[ScriptScene(voiceover="Test", visual_prompt="Test", sfx=None, duration_s=3.0)]
        )
        
        prompt = visual_director._build_enrich_prompt(seg, style_guide, None)
        
        assert "## Project Style Guide" in prompt
        assert "professional" in prompt.lower()
        assert "#1A1A2E" in prompt
    
    def test_build_enrich_prompt_includes_scenes(self, visual_director, style_guide):
        """Test that prompt includes scene list."""
        seg = ScriptSegment(
            index=0,
            heading="Test",
            content="Content",
            estimated_duration_seconds=10,
            scenes=[
                ScriptScene(voiceover="VO 1", visual_prompt="Visual 1", sfx=None, duration_s=3.0),
                ScriptScene(voiceover="VO 2", visual_prompt="Visual 2", sfx="whoosh", duration_s=4.0),
            ]
        )
        
        prompt = visual_director._build_enrich_prompt(seg, style_guide, None)
        
        assert "VO 1" in prompt
        assert "Visual 1" in prompt
        assert "VO 2" in prompt
        assert "Visual 2" in prompt


class TestEnrichResponseParser:
    """Tests for _parse_enrich_response method."""
    
    def test_parse_valid_json_array(self, visual_director):
        """Test parsing valid JSON array."""
        content = '[{"scene_idx": 0, "image_prompt": "Test", "negative_prompt": "", "video_prompt": "", "transition": "cut"}]'
        result = visual_director._parse_enrich_response(content, 1)
        
        assert len(result) == 1
        assert result[0]["scene_idx"] == 0
        assert result[0]["image_prompt"] == "Test"
    
    def test_parse_json_with_markdown(self, visual_director):
        """Test parsing JSON wrapped in markdown code blocks."""
        content = '```json\n[{"scene_idx": 0, "image_prompt": "Test", "negative_prompt": "", "video_prompt": "", "transition": "cut"}]\n```'
        result = visual_director._parse_enrich_response(content, 1)
        
        assert len(result) == 1
        assert result[0]["scene_idx"] == 0
    
    def test_parse_malformed_json(self, visual_director):
        """Test handling malformed JSON."""
        content = "This is not JSON"
        result = visual_director._parse_enrich_response(content, 1)
        
        assert result == []
    
    def test_parse_non_list_response(self, visual_director):
        """Test handling non-list JSON response."""
        content = '{"scene_idx": 0, "image_prompt": "Test"}'
        result = visual_director._parse_enrich_response(content, 1)
        
        assert result == []
