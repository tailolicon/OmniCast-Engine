"""Test backward compatibility of ScriptScene with new optional fields.

This test ensures that old ScriptDraft data (without the new AI media gen fields)
can still be loaded and parsed without validation errors.
"""

import pytest

from omnicast.models.script import ScriptScene, ScriptSegment, ScriptDraft


def test_script_scene_defaults_to_empty_strings():
    """Test that new fields default to empty strings for backward compat."""
    scene = ScriptScene(
        voiceover="This is a test voiceover",
        visual_prompt="A red cube on white background",
        sfx="cash-register",
        duration_s=3.5
    )
    
    # New fields should default to empty strings
    assert scene.image_prompt == ""
    assert scene.negative_prompt == ""
    assert scene.video_prompt == ""
    assert scene.text_overlay == ""
    assert scene.transition == "cut"


def test_script_scene_with_new_fields():
    """Test that new fields can be set explicitly."""
    scene = ScriptScene(
        voiceover="This is a test voiceover",
        visual_prompt="A red cube on white background",
        sfx="cash-register",
        duration_s=3.5,
        image_prompt="Photorealistic red cube, studio lighting, white background",
        negative_prompt="blurry, distorted, watermark, text, low quality",
        video_prompt="Slow zoom in, subtle camera movement",
        text_overlay="RED CUBE",
        transition="fade"
    )
    
    assert scene.image_prompt == "Photorealistic red cube, studio lighting, white background"
    assert scene.negative_prompt == "blurry, distorted, watermark, text, low quality"
    assert scene.video_prompt == "Slow zoom in, subtle camera movement"
    assert scene.text_overlay == "RED CUBE"
    assert scene.transition == "fade"


def test_script_segment_with_old_scenes():
    """Test that ScriptSegment can load scenes without new fields."""
    segment = ScriptSegment(
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
            )
        ]
    )
    
    # Should load without errors
    assert len(segment.scenes) == 2
    assert segment.scenes[0].image_prompt == ""
    assert segment.scenes[1].transition == "cut"


def test_script_draft_backward_compat():
    """Test that ScriptDraft can be created with old-style data."""
    draft = ScriptDraft(
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
                    )
                ]
            )
        ],
        outro="This is the outro"
    )
    
    # Should parse without errors
    assert draft.variant_id == "test-variant-1"
    assert len(draft.segments) == 1
    assert draft.segments[0].scenes[0].image_prompt == ""


def test_script_scene_transition_validation():
    """Test that transition field accepts valid values."""
    valid_transitions = ["cut", "fade", "dissolve", "whip-pan"]
    
    for transition in valid_transitions:
        scene = ScriptScene(
            voiceover="Test",
            visual_prompt="Test",
            transition=transition
        )
        assert scene.transition == transition
