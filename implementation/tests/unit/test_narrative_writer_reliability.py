"""TDD contracts for writer-reliability hardening (Plans.md task 2.1).

Covers: spoken setup_requirement vs private continuity facts, bounded local
first-draft recovery, integer length envelopes and explicit repair budgets,
one contract-only repair retry, and human-response plausibility obligations.
"""

from __future__ import annotations

import json
import math
import re

import pytest
from pydantic import ValidationError

import omnicast.agents.narrative_pipeline as np
from omnicast.agents.narrative_pipeline import (
    BlindPatchSelection,
    FinalCompilationReview,
    NarrativeUnitPipeline,
    StoryOutput,
    StoryPatchCandidate,
    StoryPatchCandidateSet,
    StoryTextEdit,
)

from tests.unit.test_narrative_unit_pipeline import (
    _FakeStructuredLLM,
    _approved_final_review,
    _brief,
    _draft,
    _narration,
    _passing_score,
    _plan,
    _select_changed_option,
    _select_option_containing,
    _story_plan,
)


def _strategy() -> np.NamedChannelStrategy:
    return np.NamedChannelStrategy(
        strategy_id="reliability_test",
        writer_rules="plain restrained narration",
        critic_rules="strict literal audit",
        annotation_rules="literal metadata",
    )


# ---------------------------------------------------------------------------
# 1. setup_requirement is the only spoken setup obligation.


def test_story_plan_requires_a_concise_spoken_setup_requirement():
    assert "setup_requirement" in np.NarrativeStoryPlan.model_fields

    payload = _story_plan(1).model_dump()
    payload.pop("setup_requirement")
    with pytest.raises(ValidationError):
        np.NarrativeStoryPlan.model_validate(payload)


def test_preflight_rejects_missing_duplicate_or_bloated_setup_requirements():
    plan = _plan()
    duplicated = plan.model_copy(update={
        "stories": [
            item.model_copy(update={"setup_requirement": "the same spoken setup line"})
            for item in plan.stories
        ]
    })
    errors = np.validate_plan_preflight(duplicated, 3)
    assert any("setup_requirement" in error for error in errors)

    bloated = plan.model_copy(update={
        "stories": [
            plan.stories[0].model_copy(update={
                "setup_requirement": " ".join(f"word{i}" for i in range(40)),
            }),
            *plan.stories[1:],
        ]
    })
    errors = np.validate_plan_preflight(bloated, 3)
    assert any("setup_requirement" in error for error in errors)

    assert np.validate_plan_preflight(plan, 3) == []


def test_ordinary_setup_beat_is_judged_against_setup_requirement_not_setting():
    from tests.unit.test_narrative_story_compliance import _review

    story = _draft(1)
    plan = _story_plan(1)
    review = _review(story)
    assert np.validate_story_compliance(plan, story, review) == []

    # Echoing the private setting where the spoken setup obligation belongs is a
    # contract violation: private facts are not exposition obligations.
    echoed_setting = review.model_copy(update={
        "beats": [
            review.beats[0].model_copy(update={"locked_requirement": plan.setting}),
            *review.beats[1:],
        ]
    })
    errors = np.validate_story_compliance(plan, story, echoed_setting)
    assert any("ordinary_setup" in error and "locked requirement" in error for error in errors)


def test_compliance_prompt_locks_ordinary_setup_to_setup_requirement():
    plan = _story_plan(1)
    prompt = np._story_compliance_prompt(plan, _draft(1), _strategy())
    assert f"ordinary_setup={json.dumps(plan.setup_requirement)}" in prompt
    assert f"ordinary_setup={json.dumps(plan.setting)}" not in prompt
    assert "not exposition obligations" in prompt


def test_planner_and_story_prompts_separate_spoken_setup_from_private_facts():
    strategy = _strategy()
    plan_prompt = np._plan_prompt(_brief(), 3, 2250, None, "", strategy)
    assert "setup_requirement" in plan_prompt

    plan = _story_plan(1)
    story_prompt = np._story_prompt(plan, 750, "cold open", strategy)
    assert plan.setup_requirement in story_prompt
    assert "SPOKEN SETUP REQUIREMENT" in story_prompt
    assert "private continuity constraints" in story_prompt


def test_setup_requirement_changes_the_locked_plan_fingerprint():
    plan = _story_plan(1)
    changed = plan.model_copy(update={"setup_requirement": "a different spoken setup"})
    assert np._story_plan_fingerprint(plan) != np._story_plan_fingerprint(changed)


# ---------------------------------------------------------------------------
# 2. Local deterministic first-draft recovery.


def _writer_with_recovery(initial: dict, recovery_narrations: dict):
    """First drafts come from `initial`; recovery calls return the mapped text."""
    calls = {"recovery_prompts": []}

    def write(prompt, _schema):
        sid = next(s for s in ("story_1", "story_2", "story_3") if s in prompt)
        if "REPAIR ONLY THIS STORY" in prompt and "Surgically repair" not in prompt:
            calls["recovery_prompts"].append(prompt)
            return StoryOutput(
                title=f"Unit {sid[-1]}", hook_candidates=[f"hook {sid[-1]}"],
                narration=recovery_narrations[sid],
            )
        draft = initial[sid]
        return StoryOutput(
            title=draft.title, hook_candidates=draft.hook_candidates,
            narration=draft.narration,
        )

    return write, calls


@pytest.mark.asyncio
async def test_local_hard_gate_failure_gets_one_recovery_before_audit():
    planner = _FakeStructuredLLM(lambda _p, _s: _plan())
    initial = {f"story_{i}": _draft(i) for i in range(1, 4)}
    initial["story_1"] = initial["story_1"].model_copy(update={
        "narration": "I told myself it was nothing. " + initial["story_1"].narration,
    })
    clean = _narration("recovered", 730)
    write, calls = _writer_with_recovery(initial, {"story_1": clean})

    critic = _FakeStructuredLLM(
        lambda _p, schema: (
            _approved_final_review() if schema is FinalCompilationReview else _passing_score()
        )
    )
    writer = _FakeStructuredLLM(write)
    result = await NarrativeUnitPipeline(planner, writer, critic, None).run(
        _brief(), annotate=False
    )

    assert result.call_counts["story_writer"] == 3
    assert result.call_counts["story_writer_recovery"] == 1
    assert result.call_counts["repair_writer"] == 0
    assert result.stories[0].narration == clean
    assert result.stories[1].narration == initial["story_2"].narration
    assert result.stories[2].narration == initial["story_3"].narration
    assert result.gate_report.passed is True
    assert result.content_locked is True
    # The recovery brief carries the exact deterministic failure it must fix.
    assert len(calls["recovery_prompts"]) == 1
    assert "self-reassurance" in calls["recovery_prompts"][0]


@pytest.mark.asyncio
async def test_clean_first_drafts_never_pay_for_a_recovery_call():
    planner = _FakeStructuredLLM(lambda _p, _s: _plan())
    initial = {f"story_{i}": _draft(i) for i in range(1, 4)}
    write, calls = _writer_with_recovery(initial, {})
    critic = _FakeStructuredLLM(
        lambda _p, schema: (
            _approved_final_review() if schema is FinalCompilationReview else _passing_score()
        )
    )
    result = await NarrativeUnitPipeline(
        planner, _FakeStructuredLLM(write), critic, None
    ).run(_brief(), annotate=False)

    assert result.call_counts["story_writer_recovery"] == 0
    assert calls["recovery_prompts"] == []
    assert result.content_locked is True


@pytest.mark.asyncio
async def test_recovery_that_does_not_strictly_improve_keeps_original_bytes():
    planner = _FakeStructuredLLM(lambda _p, _s: _plan())
    initial = {f"story_{i}": _draft(i) for i in range(1, 4)}
    banned_original = "I told myself it was nothing. " + initial["story_1"].narration
    initial["story_1"] = initial["story_1"].model_copy(update={"narration": banned_original})
    still_banned = "I told myself it was fine. " + _narration("stillbad", 730)
    write, calls = _writer_with_recovery(initial, {"story_1": still_banned})

    issue_score = _passing_score().model_copy(update={
        "story_issues": [np.StoryIssue(
            story_id="story_1", severity="major", issue_kind="style",
            problem="stock phrase", repair_instruction="replace it",
            evidence_quote="I told myself it was nothing. ", viewer_impact="synthetic",
            issue_id="stock_1",
        )]
    })

    def judge(prompt, schema):
        if schema is BlindPatchSelection:
            return _select_changed_option(prompt)
        if schema is FinalCompilationReview:
            return _approved_final_review()
        return issue_score

    result = await NarrativeUnitPipeline(
        planner, _FakeStructuredLLM(write), _FakeStructuredLLM(judge), None
    ).run(_brief(), annotate=False)

    assert result.call_counts["story_writer_recovery"] == 1
    assert result.stories[0].narration == banned_original


@pytest.mark.asyncio
async def test_recovery_tie_at_zero_local_failures_accepts_only_a_closer_length():
    # Only the compilation total is short: every story passes its own band, so the
    # shortest story ties at zero story-attributable failures and must win on length.
    planner = _FakeStructuredLLM(lambda _p, _s: _plan())
    initial = {
        "story_1": _draft(1, words=660),
        "story_2": _draft(2, words=680),
        "story_3": _draft(3, words=680),
    }
    closer = _narration("closer", 740)
    write, calls = _writer_with_recovery(initial, {"story_1": closer})
    critic = _FakeStructuredLLM(
        lambda _p, schema: (
            _approved_final_review() if schema is FinalCompilationReview else _passing_score()
        )
    )
    result = await NarrativeUnitPipeline(
        planner, _FakeStructuredLLM(write), critic, None
    ).run(_brief(), annotate=False)

    assert result.call_counts["story_writer_recovery"] == 1
    assert result.stories[0].narration == closer
    assert result.gate_report.passed is True
    assert result.content_locked is True


@pytest.mark.asyncio
async def test_recovery_tie_that_moves_away_from_target_is_discarded():
    planner = _FakeStructuredLLM(lambda _p, _s: _plan())
    initial = {
        "story_1": _draft(1, words=660),
        "story_2": _draft(2, words=680),
        "story_3": _draft(3, words=680),
    }
    original = initial["story_1"].narration
    farther = _narration("farther", 640)
    write, calls = _writer_with_recovery(initial, {"story_1": farther})
    critic = _FakeStructuredLLM(lambda _p, _s: _passing_score())
    result = await NarrativeUnitPipeline(
        planner, _FakeStructuredLLM(write), critic, None
    ).run(_brief(), annotate=False)

    assert result.call_counts["story_writer_recovery"] == 1
    assert result.stories[0].narration == original


@pytest.mark.asyncio
async def test_recovery_provider_error_keeps_original_bytes_without_crashing():
    planner = _FakeStructuredLLM(lambda _p, _s: _plan())
    initial = {f"story_{i}": _draft(i) for i in range(1, 4)}
    banned = "I told myself it was nothing. " + initial["story_1"].narration
    initial["story_1"] = initial["story_1"].model_copy(update={"narration": banned})

    def write(prompt, _schema):
        sid = next(s for s in ("story_1", "story_2", "story_3") if s in prompt)
        if "REPAIR ONLY THIS STORY" in prompt and "Surgically repair" not in prompt:
            raise ValueError("provider exploded")
        draft = initial[sid]
        return StoryOutput(
            title=draft.title, hook_candidates=draft.hook_candidates,
            narration=draft.narration,
        )

    critic = _FakeStructuredLLM(lambda _p, _s: _passing_score())
    result = await NarrativeUnitPipeline(
        planner, _FakeStructuredLLM(write), critic, None
    ).run(_brief(), annotate=False)

    assert result.call_counts["story_writer_recovery"] == 1
    assert result.stories[0].narration == banned


# ---------------------------------------------------------------------------
# 3. Concrete integer length envelope and explicit repair budgets.


def test_story_prompt_gives_an_integer_word_envelope():
    prompt = np._story_prompt(_story_plan(1), 750, "cold open", _strategy())
    assert f"{math.floor(750 * 0.9)}" in prompt
    assert f"{math.ceil(750 * 1.1)}" in prompt
    assert "90%-110%" not in prompt


def test_repair_prompt_states_current_length_envelope_and_edit_budgets():
    original = _narration("repairbudget", 700)
    current = len(np._words(original))
    prompt = np._repair_patch_prompt(
        _story_plan(1), original, [], ["story_1 has 700 words"], 750, _strategy(),
    )
    assert f"CURRENT LENGTH: {current} words" in prompt
    assert f"{math.floor(750 * 0.9)}-{math.ceil(750 * 1.1)}" in prompt
    assert str(max(30, math.floor(current * 0.20))) in prompt
    assert "180" in prompt
    assert str(math.floor(current * 0.10)) in prompt


# ---------------------------------------------------------------------------
# 4. Exactly one contract-only repair retry, then fail closed.


def _issue_score() -> np.NarrativeScorecard:
    return _passing_score().model_copy(update={
        "story_issues": [np.StoryIssue(
            story_id="story_1", severity="major", issue_kind="style",
            problem="stock phrase", repair_instruction="replace it",
            evidence_quote="I told myself it was nothing. ", viewer_impact="synthetic",
            issue_id="stock_1",
        )]
    })


def _banned_initial() -> dict:
    initial = {f"story_{i}": _draft(i) for i in range(1, 4)}
    initial["story_1"] = initial["story_1"].model_copy(update={
        "narration": "I told myself it was nothing. " + initial["story_1"].narration,
    })
    return initial


@pytest.mark.asyncio
async def test_invalid_repair_pair_gets_one_contract_retry_then_fails_closed():
    planner = _FakeStructuredLLM(lambda _p, _s: _plan())
    initial = _banned_initial()
    repair_prompts: list[str] = []

    def write(prompt, _schema):
        sid = next(s for s in initial if s in prompt)
        if "Surgically repair" in prompt:
            repair_prompts.append(prompt)
            return StoryPatchCandidateSet(candidates=[
                StoryPatchCandidate(candidate_id="candidate_1", edits=[StoryTextEdit(
                    find="text that is not present", replace="replacement",
                )]),
                StoryPatchCandidate(candidate_id="candidate_2", edits=[StoryTextEdit(
                    find="other text that is not present", replace="replacement",
                )]),
            ])
        draft = initial[sid]
        return StoryOutput(
            title=draft.title, hook_candidates=draft.hook_candidates,
            narration=draft.narration,
        )

    result = await NarrativeUnitPipeline(
        planner, _FakeStructuredLLM(write),
        _FakeStructuredLLM(lambda _p, _s: _issue_score()), None,
    ).run(_brief(), annotate=False)

    assert result.call_counts["repair_writer"] == 2
    assert len(repair_prompts) == 2
    assert "CONTRACT RETRY" in repair_prompts[1]
    assert "atomic" in repair_prompts[1].lower() or "exact" in repair_prompts[1].lower()
    # Identical brief/anchors/budgets: the retry contains the whole first prompt.
    assert repair_prompts[0] in repair_prompts[1]
    assert result.stories[0].narration == initial["story_1"].narration
    assert result.content_locked is False


@pytest.mark.asyncio
async def test_repair_contract_retry_can_recover_a_valid_pair():
    planner = _FakeStructuredLLM(lambda _p, _s: _plan())
    initial = _banned_initial()
    attempts = {"repair": 0}

    def write(prompt, _schema):
        sid = next(s for s in initial if s in prompt)
        if "Surgically repair" in prompt:
            attempts["repair"] += 1
            if attempts["repair"] == 1:
                raise ValueError("malformed patch JSON")
            return StoryPatchCandidateSet(candidates=[
                StoryPatchCandidate(candidate_id="candidate_1", edits=[StoryTextEdit(
                    find="I told myself it was nothing. ",
                    replace="I checked the latch twice. ",
                )]),
                StoryPatchCandidate(candidate_id="candidate_2", edits=[StoryTextEdit(
                    find="I told myself it was nothing. ",
                    replace="I pressed my thumb against the latch. ",
                )]),
            ])
        draft = initial[sid]
        return StoryOutput(
            title=draft.title, hook_candidates=draft.hook_candidates,
            narration=draft.narration,
        )

    scores = iter([_issue_score(), _passing_score()])

    def judge(prompt, schema):
        if schema is BlindPatchSelection:
            return _select_changed_option(prompt)
        if schema is FinalCompilationReview:
            return _approved_final_review()
        return next(scores)

    result = await NarrativeUnitPipeline(
        planner, _FakeStructuredLLM(write), _FakeStructuredLLM(judge), None,
    ).run(_brief(), annotate=False)

    assert result.call_counts["repair_writer"] == 2
    assert not result.stories[0].narration.startswith("I told myself")
    assert result.content_locked is True


# ---------------------------------------------------------------------------
# 5. Final-editor blockers form the monotonic baseline of their own repair, and
#    the recorded patch decision names the candidate that actually won.


@pytest.mark.asyncio
async def test_final_editor_blocker_repair_is_accepted_on_an_equal_rescore():
    planner = _FakeStructuredLLM(lambda _p, _s: _plan())
    initial = {f"story_{i}": _draft(i) for i in range(1, 4)}
    blocker_quote = initial["story_1"].narration.split("\n\n")[6]
    fixed_line = blocker_quote.replace("detail", "latched", 1)
    alternate_line = blocker_quote.replace("detail", "secured", 1)

    def write(prompt, _schema):
        sid = next(s for s in initial if s in prompt)
        if "Surgically repair" in prompt:
            return StoryPatchCandidateSet(candidates=[
                StoryPatchCandidate(candidate_id="candidate_1", edits=[StoryTextEdit(
                    find=blocker_quote, replace=fixed_line,
                )]),
                StoryPatchCandidate(candidate_id="candidate_2", edits=[StoryTextEdit(
                    find=blocker_quote, replace=alternate_line,
                )]),
            ])
        draft = initial[sid]
        return StoryOutput(
            title=draft.title, hook_candidates=draft.hook_candidates,
            narration=draft.narration,
        )

    final_calls = {"count": 0}

    def judge(prompt, schema):
        if schema is BlindPatchSelection:
            return _select_option_containing(prompt, "latched")
        if schema is FinalCompilationReview:
            final_calls["count"] += 1
            if final_calls["count"] == 1:
                return FinalCompilationReview(
                    approved=False,
                    reviewed_story_ids=["story_1", "story_2", "story_3"],
                    issues=[np.StoryIssue(
                        story_id="story_1", severity="major",
                        issue_kind="contradiction",
                        problem="this paragraph contradicts the locked ending shape",
                        repair_instruction="repair only this paragraph",
                        evidence_quote=blocker_quote,
                        viewer_impact="breaks belief in the promised ending",
                        issue_id="final_1",
                    )],
                    summary="one grounded blocker",
                )
            return _approved_final_review()
        # The fresh critic rescores the patched compilation at the SAME total.
        # Resolving the final editor's grounded blocker must itself count as
        # progress; requiring a strictly higher score would discard a valid fix.
        return _passing_score()

    result = await NarrativeUnitPipeline(
        planner, _FakeStructuredLLM(write), _FakeStructuredLLM(judge), None,
    ).run(_brief(), annotate=False)

    assert result.call_counts["final_editor"] == 2
    assert result.call_counts["repair_writer"] == 1
    assert result.repair_waves == 1
    assert fixed_line in result.stories[0].narration
    assert blocker_quote not in result.stories[0].narration
    assert result.stories[1].narration == initial["story_2"].narration
    assert result.stories[2].narration == initial["story_3"].narration
    assert result.final_editor_approved is True
    assert result.content_locked is True
    assert result.release_tier == "editorially_ready"


@pytest.mark.asyncio
async def test_patch_decision_reports_the_candidate_that_actually_won():
    planner = _FakeStructuredLLM(lambda _p, _s: _plan())
    initial = _banned_initial()

    def write(prompt, _schema):
        sid = next(s for s in initial if s in prompt)
        if "Surgically repair" in prompt:
            # A reversed pair order must not corrupt the recorded decision.
            return StoryPatchCandidateSet(candidates=[
                StoryPatchCandidate(candidate_id="candidate_2", edits=[StoryTextEdit(
                    find="I told myself it was nothing. ",
                    replace="I pressed my thumb against the latch. ",
                )]),
                StoryPatchCandidate(candidate_id="candidate_1", edits=[StoryTextEdit(
                    find="I told myself it was nothing. ",
                    replace="I checked the deadbolt twice. ",
                )]),
            ])
        draft = initial[sid]
        return StoryOutput(
            title=draft.title, hook_candidates=draft.hook_candidates,
            narration=draft.narration,
        )

    scores = iter([_issue_score(), _passing_score()])

    def judge(prompt, schema):
        if schema is BlindPatchSelection:
            return _select_option_containing(prompt, "deadbolt")
        if schema is FinalCompilationReview:
            return _approved_final_review()
        return next(scores)

    result = await NarrativeUnitPipeline(
        planner, _FakeStructuredLLM(write), _FakeStructuredLLM(judge), None,
    ).run(_brief(), annotate=False)

    assert "I checked the deadbolt twice. " in result.stories[0].narration
    assert len(result.patch_decisions) == 1
    decision = result.patch_decisions[0]
    assert decision.selected == "candidate_1"
    assert decision.selected_candidate_id == "candidate_1"
    assert result.content_locked is True


# ---------------------------------------------------------------------------
# 6. Obvious human-safety failures are major for writer, critic, and final gate.


def test_writer_critic_and_final_prompts_treat_obvious_safety_failures_as_major():
    strategy = _strategy()
    writer_prompt = np._story_prompt(_story_plan(1), 750, "cold open", strategy)
    critic_prompt = np._critic_prompt(
        _plan(), [_draft(i) for i in range(1, 4)],
        np.gate_compilation(_plan(), [_draft(i) for i in range(1, 4)]), strategy,
    )
    final_prompt = np._final_review_prompt(
        _plan(), [_draft(i) for i in range(1, 4)], strategy,
    )
    for prompt in (writer_prompt, critic_prompt, final_prompt):
        lowered = prompt.lower()
        assert "preserve mystery" in lowered
        assert "urgent help" in lowered
        assert "re-enter" in lowered
    for prompt in (critic_prompt, final_prompt):
        assert "at least major" in prompt.lower()


# ---------------------------------------------------------------------------
# 7. A dead-ended patch contract escalates to ONE bounded full-story rewrite.
#    Local acceptance stays deterministic (no new attributable hard-gate
#    failures, no identical bytes); the semantic verdict stays with the wave's
#    compliance re-audit, critic re-score, and monotonic gate — so the release
#    gate remains fail-closed while a fixable story stops dying on patch
#    budget technicalities (the 20260715 apartment-maintenance builds shipped
#    0/11 for exactly this reason).


def _rewrite_writer(initial: dict, rewrites: dict, log: dict):
    """First drafts and recoveries return `initial`; every patch pair is
    locally invalid; the rewrite fallback returns the mapped narration."""

    def write(prompt, _schema):
        sid = next(s for s in initial if s in prompt)
        if "Surgically repair" in prompt:
            log.setdefault("patch_prompts", []).append(prompt)
            return StoryPatchCandidateSet(candidates=[
                StoryPatchCandidate(candidate_id="candidate_1", edits=[StoryTextEdit(
                    find="text that is not present", replace="replacement",
                )]),
                StoryPatchCandidate(candidate_id="candidate_2", edits=[StoryTextEdit(
                    find="other text that is not present", replace="replacement",
                )]),
            ])
        if "patch contract" in prompt:
            log.setdefault("rewrite_prompts", []).append(prompt)
            return StoryOutput(
                title=initial[sid].title, hook_candidates=[f"hook {sid[-1]}"],
                narration=rewrites[sid],
            )
        draft = initial[sid]
        return StoryOutput(
            title=draft.title, hook_candidates=draft.hook_candidates,
            narration=draft.narration,
        )

    return write


@pytest.mark.asyncio
async def test_patch_contract_dead_end_escalates_to_one_bounded_rewrite():
    planner = _FakeStructuredLLM(lambda _p, _s: _plan())
    initial = _banned_initial()
    clean = _narration("rewritten", 750)
    log: dict = {}
    write = _rewrite_writer(initial, {"story_1": clean}, log)

    scores = iter([_issue_score(), _passing_score()])

    def judge(_prompt, schema):
        if schema is FinalCompilationReview:
            return _approved_final_review()
        return next(scores)

    result = await NarrativeUnitPipeline(
        planner, _FakeStructuredLLM(write), _FakeStructuredLLM(judge), None,
    ).run(_brief(), annotate=False)

    assert result.call_counts["repair_writer"] == 2
    assert result.call_counts["repair_rewrite"] == 1
    assert result.stories[0].narration == clean
    assert result.content_locked is True
    decision = next(d for d in result.patch_decisions if d.story_id == "story_1")
    assert decision.selected == "full_rewrite"
    # The rewrite brief carries the original, the deterministic gate defect,
    # and the critic's repair instruction — everything needed to fix it blind.
    prompt = log["rewrite_prompts"][0]
    assert "REPAIR ONLY THIS STORY" in prompt
    assert initial["story_1"].narration in prompt
    assert "self-reassurance" in prompt
    assert "replace it" in prompt


@pytest.mark.asyncio
async def test_rewrite_fallback_that_worsens_the_hard_gate_keeps_baseline():
    planner = _FakeStructuredLLM(lambda _p, _s: _plan())
    initial = _banned_initial()
    # Keeps the banned phrase AND collapses the length: strictly worse locally.
    worse = "I told myself it was nothing. " + _narration("worse", 200)
    log: dict = {}
    write = _rewrite_writer(initial, {"story_1": worse}, log)

    result = await NarrativeUnitPipeline(
        planner, _FakeStructuredLLM(write),
        _FakeStructuredLLM(lambda _p, _s: _issue_score()), None,
    ).run(_brief(), annotate=False)

    assert result.call_counts["repair_rewrite"] == 1
    assert result.stories[0].narration == initial["story_1"].narration
    decision = next(d for d in result.patch_decisions if d.story_id == "story_1")
    assert decision.selected == "baseline"
    assert "rewrite" in decision.reason
    assert result.content_locked is False


@pytest.mark.asyncio
async def test_identical_rewrite_bytes_are_rejected_not_recorded_as_progress():
    planner = _FakeStructuredLLM(lambda _p, _s: _plan())
    initial = _banned_initial()
    log: dict = {}
    write = _rewrite_writer(
        initial, {"story_1": initial["story_1"].narration}, log
    )

    result = await NarrativeUnitPipeline(
        planner, _FakeStructuredLLM(write),
        _FakeStructuredLLM(lambda _p, _s: _issue_score()), None,
    ).run(_brief(), annotate=False)

    assert result.call_counts["repair_rewrite"] == 1
    decision = next(d for d in result.patch_decisions if d.story_id == "story_1")
    assert decision.selected == "baseline"
    assert result.content_locked is False


@pytest.mark.asyncio
async def test_wave_length_shortfall_is_fixed_by_the_rewrite_fallback():
    """Replay of the 20260715_1514 build: one story lands ~630/750 words, the
    patch budget cannot add ~120 words, and the compilation must not die on it."""
    planner = _FakeStructuredLLM(lambda _p, _s: _plan())
    initial = {f"story_{i}": _draft(i) for i in range(1, 4)}
    initial["story_2"] = _draft(2, words=630)
    fixed = _narration("stretched", 760)
    log: dict = {}
    write = _rewrite_writer(initial, {"story_2": fixed}, log)

    def judge(_prompt, schema):
        if schema is FinalCompilationReview:
            return _approved_final_review()
        return _passing_score()

    result = await NarrativeUnitPipeline(
        planner, _FakeStructuredLLM(write), _FakeStructuredLLM(judge), None,
    ).run(_brief(), annotate=False)

    # First-draft recovery ran and failed (identical bytes) before the wave.
    assert result.call_counts["story_writer_recovery"] == 1
    assert result.call_counts["repair_rewrite"] == 1
    assert result.stories[1].narration == fixed
    assert result.gate_report.passed is True
    assert result.content_locked is True
    prompt = log["rewrite_prompts"][0]
    current = len(np._words(initial["story_2"].narration))
    assert f"{current} words" in prompt
    assert f"story_2 has {current} words" in prompt
