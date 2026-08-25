"""Cost-routing tests for the claude-first script path."""

from omnicast.pipeline.steps import (
    _apply_human_anchor_gate,
    _apply_operator_editorial_feedback,
    _needs_length_only_fill,
    _needs_visual_only_repair,
    _script_result_rank,
)
from omnicast.agents.orchestrator import DebateResult
from omnicast.models.enums import Market, Niche, TopicSource
from omnicast.models.script import (
    CriticDimension,
    CriticFeedback,
    ScriptDraft,
    ScriptScene,
    ScriptSegment,
    TopicBrief,
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


def test_full_length_revision_beats_underlength_initial_with_two_more_points():
    initial = DebateResult(
        variant_id="claude_initial", final_draft=_draft(1632), final_score=79,
        approved=False, converged=True,
    )
    revision = DebateResult(
        variant_id="claude_revised", final_draft=_draft(2271), final_score=77,
        approved=False, converged=True,
    )

    assert _script_result_rank(revision, _brief()) \
        > _script_result_rank(initial, _brief())


def test_a_fragment_cannot_win_by_being_too_short_to_be_wrong():
    """Live run 2026-08-03: the pipeline reported a 128-word outline scoring
    27/100 as its best candidate over a complete 2,111-word draft scoring 66.
    The outline made too few claims to trip an evidence boundary, and the rank
    put evidence cleanliness ahead of length — so making almost no claims read
    as making good ones. Approval is untouched by this ordering: the evidence
    gate already forces approved=False on anything it flags."""
    fragment = DebateResult(
        variant_id="claude_initial", final_draft=_draft(128), final_score=27,
        approved=False, converged=True,
    )
    complete = DebateResult(
        variant_id="claude_revised", final_draft=_draft(2400), final_score=66,
        approved=False, converged=True,
    )
    complete.evidence_problems = ["spoken figure outside the verified range"]

    assert _script_result_rank(complete, _brief()) \
        > _script_result_rank(fragment, _brief())


def test_among_usable_drafts_evidence_cleanliness_still_wins():
    """The reordering must not become 'length beats everything'. Once both
    drafts clear the floor, a clean one outranks a flagged one even on a lower
    score — that is the YMYL preference the term exists for."""
    clean = DebateResult(
        variant_id="clean", final_draft=_draft(2400), final_score=70,
        approved=False, converged=True,
    )
    flagged = DebateResult(
        variant_id="flagged", final_draft=_draft(2600), final_score=78,
        approved=False, converged=True,
    )
    flagged.evidence_problems = ["stale 2024 threshold spoken as current"]

    assert _script_result_rank(clean, _brief()) \
        > _script_result_rank(flagged, _brief())


def test_explicit_human_anchor_contract_overrides_a_soft_critic_approval():
    feedback = CriticFeedback(
        total_score=84,
        voiceover_score=60,
        production_score=24,
        approved=True,
        dimensions=[
            CriticDimension(
                name="retention_structure",
                score=8,
                max_score=9,
                feedback="The example is clear.",
            ),
        ],
    )
    arithmetic_only = ScriptDraft(
        variant_id="A",
        brief_title="T",
        hook="The limit is concrete.",
        segments=[
            ScriptSegment(
                index=1,
                heading="HYPOTHETICAL EXAMPLE",
                content="Say, hypothetically, someone earns $30,000.",
                estimated_duration_seconds=10,
            ),
        ],
        outro="That is the calculation.",
    )

    gated, problems = _apply_human_anchor_gate(
        feedback,
        arithmetic_only,
        "THE HUMAN ANCHOR\nLet's call her Denise. She is hypothetical.",
    )

    assert problems
    assert gated.approved is False
    assert gated.total_score < feedback.total_score
    assert any("HARD GATE (human anchor)" in reason
               for reason in gated.rejection_reasons)


def test_human_anchor_failure_never_routes_to_voiceover_locked_visual_repair():
    feedback = CriticFeedback(
        total_score=81,
        voiceover_score=60,
        production_score=21,
        approved=False,
    )

    assert _needs_visual_only_repair(feedback, [], []) is True
    assert _needs_visual_only_repair(
        feedback,
        [],
        ["Denise is absent from the hook"],
    ) is False


def test_explicit_editorial_readthrough_rejection_routes_back_to_writer_once():
    feedback = CriticFeedback(
        total_score=88,
        voiceover_score=63,
        production_score=25,
        approved=True,
        specific_fixes=["Keep the sourced figures."],
    )

    gated, fixes = _apply_operator_editorial_feedback(
        feedback,
        "OPERATOR EDITORIAL REVIEW — REJECTED\n"
        "- Cut the repeated arithmetic.\n"
        "- Return to the kitchen table at the payoff.",
    )

    assert gated.approved is False
    assert fixes == [
        "Cut the repeated arithmetic.",
        "Return to the kitchen table at the payoff.",
    ]
    assert gated.specific_fixes[:2] == fixes
    assert _apply_operator_editorial_feedback(gated, "") == (gated, [])
