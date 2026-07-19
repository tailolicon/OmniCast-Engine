"""TDD contract for per-story plan/beat compliance."""

from __future__ import annotations

import asyncio
import re

import pytest

from omnicast.agents.narrative_pipeline import (
    NamedChannelStrategy,
    StoryBeatCheck,
    StoryComplianceReview,
    StoryDraft,
    _canonical_quote,
    _canonicalize_story_compliance,
    _narration_sha256,
    _story_plan_fingerprint,
    _story_prompt,
    story_compliance_approved,
    story_compliance_issues,
    validate_story_compliance,
)
from omnicast.config.narrative_quality import resolve_script_profile

from tests.unit.test_narrative_unit_pipeline import (
    _FakeStructuredLLM,
    _approved_final_review,
    _brief,
    _draft,
    _passing_score,
    _plan,
    _story_plan,
)
from omnicast.agents.narrative_pipeline import (
    FinalCompilationReview,
    NarrativePipelineResult,
    NarrativeUnitPipeline,
    StoryOutput,
)


def _review(story: StoryDraft, *, approved: bool = True) -> StoryComplianceReview:
    quotes = [paragraph.strip() for paragraph in story.narration.split("\n\n")[:5]]
    status = "complete" if approved else "missing"
    plan = _story_plan(int(story.story_id[-1]))
    requirements = (
        plan.setup_requirement, plan.threat, plan.escape_action, plan.escape_action,
        plan.ending_shape,
    )
    return StoryComplianceReview(
        story_id=story.story_id,
        plan_fingerprint=_story_plan_fingerprint(_story_plan(int(story.story_id[-1]))),
        narration_sha256=_narration_sha256(story),
        beats=[
            StoryBeatCheck(
                beat_id=beat_id, status=(status if beat_id == "completed_ending" else "complete"),
                locked_requirement=requirement,
                evidence_quote=(quote if status == "complete" or beat_id != "completed_ending" else ""),
                anchor_quote=(quote if status == "missing" and beat_id == "completed_ending" else ""),
                explanation="required beat",
            )
            for beat_id, quote, requirement in zip((
                "ordinary_setup", "threat_confirmation", "decision_action",
                "completed_escape", "completed_ending",
            ), quotes, requirements, strict=True)
        ],
        plan_facts_status="preserved",
        evidence_budget_status="preserved",
    )


def test_story_compliance_requires_exact_unique_quotes_in_narrative_order():
    story = _draft(1)
    review = _review(story)
    assert validate_story_compliance(_story_plan(1), story, review) == []

    swapped = review.model_copy(update={
        "beats": [*review.beats[:2], review.beats[2].model_copy(update={
            "evidence_quote": review.beats[3].evidence_quote,
        }), review.beats[3].model_copy(update={
            "evidence_quote": review.beats[2].evidence_quote,
        }), review.beats[4]]
    })
    assert any("order" in error for error in validate_story_compliance(
        _story_plan(1), story, swapped
    ))

    absent = review.model_copy(update={
        "beats": [*review.beats[:4], review.beats[4].model_copy(update={
            "evidence_quote": "This sentence does not occur in the story."
        })]
    })
    assert any("exact" in error for error in validate_story_compliance(
        _story_plan(1), story, absent
    ))


def test_story_compliance_rejects_wrong_plan_and_false_approval_claims():
    story = _draft(1)
    review = _review(story).model_copy(update={
        "plan_fingerprint": _story_plan_fingerprint(_story_plan(2)),
    })
    errors = validate_story_compliance(_story_plan(1), story, review)
    assert any("fingerprint" in error for error in errors)
    assert story_compliance_approved(review) is True


def test_story_compliance_rejects_reused_quote_and_unresolved_evidence_budget():
    story = _draft(1)
    review = _review(story)
    reused = review.model_copy(update={
        "beats": [
            item.model_copy(update={"evidence_quote": review.beats[0].evidence_quote})
            for item in review.beats
        ]
    })
    errors = validate_story_compliance(_story_plan(1), story, reused)
    assert any("distinct evidence" in error for error in errors)
    assert any("strictly ordered" in error for error in errors)

    unresolved = review.model_copy(update={"evidence_budget_status": "unclear"})
    assert story_compliance_approved(unresolved) is False


def test_compliance_quote_is_canonicalized_only_across_whitespace():
    narration = "I reached the hallway.\nThe outer door shut behind me."
    assert _canonical_quote(
        narration, "I reached the hallway. The outer door shut behind me."
    ) == narration
    assert _canonical_quote(narration, "I reached the lobby instead.") is None

    story = _draft(1)
    review = _review(story)
    echoed_plan = review.model_copy(update={
        "beats": [review.beats[0].model_copy(update={
            "evidence_quote": _story_plan(1).setting,
        }), *review.beats[1:]]
    })
    canonical = _canonicalize_story_compliance(story, echoed_plan)
    assert canonical.beats[0].evidence_quote == _story_plan(1).setting
    assert any("ordinary_setup quote" in error for error in
               validate_story_compliance(_story_plan(1), story, canonical))


def test_optional_compliance_anchor_accepts_provider_null_without_weakening_evidence():
    beat = StoryBeatCheck.model_validate({
        "beat_id": "ordinary_setup",
        "locked_requirement": "ordinary setup",
        "status": "complete",
        "evidence_quote": "An exact quote from the story.",
        "anchor_quote": None,
        "explanation": "complete beats do not need a repair anchor",
    })
    assert beat.anchor_quote == ""

    with pytest.raises(ValueError):
        StoryBeatCheck.model_validate({
            "beat_id": "ordinary_setup",
            "locked_requirement": "ordinary setup",
            "status": "complete",
            "evidence_quote": None,
            "anchor_quote": "",
            "explanation": "required evidence must remain strict",
        })


def test_review_level_optional_text_accepts_provider_null_without_weakening_gates():
    """DeepSeek escalation returned JSON null for plan_facts_quote/evidence_quote
    on a preserved verdict (build 20260716_2058) and zeroed the whole run on a
    schema crash. Null optional text coerces to "" — a failing verdict with an
    empty quote is still rejected semantically by validate_story_compliance."""
    story = _draft(3)
    base = _review(story).model_dump()
    base.update({
        "plan_facts_quote": None,
        "plan_facts_explanation": None,
        "evidence_quote": None,
        "evidence_explanation": None,
    })
    review = StoryComplianceReview.model_validate(base)
    assert review.plan_facts_quote == ""
    assert review.evidence_quote == ""
    assert review.plan_facts_explanation == ""
    assert review.evidence_explanation == ""

    # A negative verdict without a grounding quote still fails — semantically.
    base["story_id"] = story.story_id
    base["plan_facts_status"] = "contradicted"
    ungrounded = StoryComplianceReview.model_validate(base)
    errors = validate_story_compliance(_story_plan(3), story, ungrounded)
    assert any("plan facts failure requires an exact unique quote" in e for e in errors)


def test_story_issue_and_review_summaries_accept_provider_null():
    from omnicast.agents.narrative_pipeline import StoryIssue

    issue = StoryIssue.model_validate({
        "story_id": "story_1", "severity": "major",
        "problem": "contradiction", "repair_instruction": "fix it",
        "evidence_quote": None, "anchor_quote": None,
        "viewer_impact": None, "issue_id": None,
    })
    assert issue.evidence_quote == ""
    assert issue.anchor_quote == ""
    assert issue.viewer_impact == ""
    assert issue.issue_id == ""
    final = FinalCompilationReview.model_validate({
        "approved": True, "reviewed_story_ids": ["story_1"],
        "issues": [], "summary": None,
    })
    assert final.summary == ""


def test_story_compliance_issues_must_be_forensically_grounded():
    story = _draft(1)
    review = _review(story, approved=False)
    issues = story_compliance_issues(review)
    assert issues[0].issue_id == "story_1:completed_ending"
    assert issues[0].issue_kind == "omission"
    assert issues[0].anchor_quote in story.narration


def test_writer_prompt_contains_semantic_beat_contract_and_real_failure_examples():
    strategy = NamedChannelStrategy.from_quality_profile(
        resolve_script_profile("true_horror_strict_v1")
    )
    prompt = _story_prompt(_story_plan(1), 750, "cold open", strategy)
    assert "COMPLETED locked escape" in prompt
    assert "COMPLETED ending" in prompt
    assert "admitting the threat inside" in prompt
    assert "intent to escape is not escape completion" in prompt.lower()
    assert "Do not print beat labels" in prompt


@pytest.mark.asyncio
async def test_compliance_calls_can_overlap_instead_of_serializing_three_stories():
    planner = _FakeStructuredLLM(lambda _p, _s: _plan())
    drafts = {f"story_{index}": _draft(index) for index in range(1, 4)}

    def write(prompt, _schema):
        sid = next(sid for sid in drafts if sid in prompt)
        draft = drafts[sid]
        return StoryOutput(
            title=draft.title, hook_candidates=draft.hook_candidates,
            narration=draft.narration,
        )

    compliance = _FakeStructuredLLM(
        lambda prompt, _schema: _review(drafts[next(
            sid for sid in drafts if f"story_id: {sid}" in prompt
        )]), auto_compliance=False,
    )
    critic = _FakeStructuredLLM(
        lambda _p, schema: (
            _approved_final_review() if schema is FinalCompilationReview
            else _passing_score()
        )
    )
    result = await NarrativeUnitPipeline(
        planner, _FakeStructuredLLM(write), critic, None,
        compliance_llm=compliance,
    ).run(_brief(), annotate=False)

    assert compliance.max_active == 3
    assert result.call_counts["story_compliance"] == 3
    assert result.story_compliance_valid is True
    assert result.content_locked is True

    forged = result.model_dump(mode="json")
    forged["story_compliance_reviews"][0]["plan_fingerprint"] = "0" * 64
    with pytest.raises(ValueError, match="approved story compliance"):
        NarrativePipelineResult.model_validate(forged)

    stale_content_valid = result.model_dump(mode="json")
    stale_content_valid.update({
        "content_locked": False, "production_ready": False,
        "final_editor_approved": False, "locked_voiceover_sha256": "",
        "release_tier": "content_valid",
    })
    stale_content_valid["story_compliance_reviews"][0]["narration_sha256"] = "f" * 64
    with pytest.raises(ValueError, match="release_tier"):
        NarrativePipelineResult.model_validate(stale_content_valid)


@pytest.mark.asyncio
async def test_invalid_compliance_retries_then_blocks_critic_and_annotations():
    planner = _FakeStructuredLLM(lambda _p, _s: _plan())
    drafts = {f"story_{index}": _draft(index) for index in range(1, 4)}

    def write(prompt, _schema):
        sid = next(sid for sid in drafts if sid in prompt)
        draft = drafts[sid]
        return StoryOutput(
            title=draft.title, hook_candidates=draft.hook_candidates,
            narration=draft.narration,
        )

    compliance = _FakeStructuredLLM(
        lambda _p, _s: (_ for _ in ()).throw(ValueError("malformed compliance")),
        auto_compliance=False,
    )
    critic = _FakeStructuredLLM(lambda _p, _s: pytest.fail("critic must not run"))
    annotation = _FakeStructuredLLM(lambda _p, _s: pytest.fail("annotation must not run"))
    result = await NarrativeUnitPipeline(
        planner, _FakeStructuredLLM(write), critic, annotation,
        compliance_llm=compliance,
    ).run(_brief(), annotate=True)

    assert result.story_compliance_valid is False
    assert result.content_locked is False
    assert result.release_tier == "needs_edit"
    assert result.call_counts["story_compliance"] == 6
    assert result.call_counts["critic_score"] == 0
    assert result.call_counts["annotation"] == 0


@pytest.mark.asyncio
async def test_failed_flash_contract_escalates_once_per_story_to_senior_auditor():
    planner = _FakeStructuredLLM(lambda _p, _s: _plan())
    drafts = {f"story_{index}": _draft(index) for index in range(1, 4)}

    def write(prompt, _schema):
        sid = next(sid for sid in drafts if sid in prompt)
        draft = drafts[sid]
        return StoryOutput(
            title=draft.title, hook_candidates=draft.hook_candidates,
            narration=draft.narration,
        )

    flash = _FakeStructuredLLM(
        lambda _p, _s: (_ for _ in ()).throw(ValueError("bad fast audit")),
        auto_compliance=False,
    )
    senior = _FakeStructuredLLM(lambda _p, _s: pytest.fail("auto audit should handle"))
    critic = _FakeStructuredLLM(
        lambda _p, schema: (
            _approved_final_review() if schema is FinalCompilationReview
            else _passing_score()
        )
    )
    result = await NarrativeUnitPipeline(
        planner, _FakeStructuredLLM(write), critic, None,
        compliance_llm=flash, compliance_escalation_llm=senior,
    ).run(_brief(), annotate=False)

    assert result.story_compliance_valid is True
    assert result.call_counts["story_compliance"] == 6
    assert result.call_counts["story_compliance_escalation"] == 3
    assert result.content_locked is True
