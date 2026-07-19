"""Cost-routing tests for the claude-first script path."""

from omnicast.pipeline.steps import _needs_length_only_fill, _script_result_rank
from omnicast.agents.orchestrator import DebateResult
from omnicast.models.enums import Market, Niche, TopicSource
from omnicast.models.script import (
    CriticFeedback, ScriptDraft, ScriptScene, ScriptSegment, TopicBrief,
)


def _draft(words: int) -> ScriptDraft:
    vo = " ".join(["word"] * words)
    scene = ScriptScene(voiceover=vo, visual_prompt="dark office")
    return ScriptDraft(
        variant_id="A", brief_title="T", hook="",
        segments=[ScriptSegment(
            index=1, heading="Hall", content=vo,
            estimated_duration_seconds=words // 2, scenes=[scene],
        )],
    )


def _brief() -> TopicBrief:
    return TopicBrief(
        title="T", niche=Niche.PSYCHOLOGY, market=Market.US,
        source=TopicSource.MANUAL, target_duration_min=15,
    )


def test_high_score_underlength_uses_fill_not_full_revision():
    feedback = CriticFeedback(
        total_score=85, voiceover_score=56, production_score=29,
        approved=False, continuity_issues=[],
    )

    assert _needs_length_only_fill(_draft(1700), feedback, _brief(), 82) is True


def test_low_quality_or_continuity_issue_still_uses_revision():
    low = CriticFeedback(
        total_score=70, voiceover_score=44, production_score=26,
        approved=False,
    )
    broken = CriticFeedback(
        total_score=85, voiceover_score=56, production_score=29,
        approved=False, continuity_issues=["door position changes"],
    )

    assert _needs_length_only_fill(_draft(1700), low, _brief(), 82) is False
    assert _needs_length_only_fill(_draft(1700), broken, _brief(), 82) is False


def test_debate_selection_prefers_near_complete_draft_over_short_higher_score():
    short_result = DebateResult(
        variant_id="short", final_draft=_draft(2), final_score=65,
        approved=False, converged=True,
    )
    complete_result = DebateResult(
        variant_id="complete", final_draft=_draft(1975), final_score=60,
        approved=False, converged=True,
    )

    assert _script_result_rank(complete_result, _brief()) \
        > _script_result_rank(short_result, _brief())
