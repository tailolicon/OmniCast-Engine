"""Visual-only repair must preserve the locked narration and prosody."""

from unittest.mock import AsyncMock

from omnicast.agents.visual_director import VisualDirectorAgent
from omnicast.models.script import ScriptDraft, ScriptScene, ScriptSegment


def _scene(vo: str, visual: str) -> ScriptScene:
    return ScriptScene(
        voiceover=vo,
        visual_prompt=visual,
        pace="slow",
        pause_after_ms=650,
        emphasis=["locked"],
    )


def test_apply_scenes_updates_hook_body_outro_without_losing_prosody():
    agent = VisualDirectorAgent(llm=AsyncMock())
    hook = _scene("Hook words stay exact.", "generic hook")
    body = _scene("Body words stay exact.", "generic body")
    outro = _scene("Outro words stay exact.", "generic outro")
    draft = ScriptDraft(
        variant_id="A",
        brief_title="T",
        hook=hook.voiceover,
        hook_scenes=[hook],
        segments=[ScriptSegment(
            index=1,
            heading="Rule",
            content=body.voiceover,
            estimated_duration_seconds=5,
            scenes=[body],
        )],
        outro=outro.voiceover,
        outro_scenes=[outro],
    )

    repaired = agent._apply_scenes(draft, {
        1: ("SSA page close-up", None),
        2: ("threshold comparison chart", "ting"),
        3: ("calendar and benefits statement", None),
    })

    scenes = [
        repaired.hook_scenes[0],
        repaired.segments[0].scenes[0],
        repaired.outro_scenes[0],
    ]
    assert [scene.voiceover for scene in scenes] == [
        hook.voiceover, body.voiceover, outro.voiceover]
    assert [scene.visual_prompt for scene in scenes] == [
        "SSA page close-up",
        "threshold comparison chart",
        "calendar and benefits statement",
    ]
    assert all(scene.pace == "slow" for scene in scenes)
    assert all(scene.pause_after_ms == 650 for scene in scenes)
    assert all(scene.emphasis == ["locked"] for scene in scenes)
