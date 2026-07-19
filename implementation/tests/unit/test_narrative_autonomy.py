"""TDD contracts for autonomous operation.

Two mechanisms replace manual needs_edit editing: a semantic plan-plausibility
audit BEFORE any paid drafting (a bad premise cannot be fixed by good prose),
and an outer fresh-plan retry so a failed compilation regenerates a different
concept instead of parking at needs_edit for a human.

Autonomy is not the same as optimism. This file originally encoded a fail-OPEN
audit — a lone major was discarded, an unreachable auditor read as clean, and the
final planner attempt proceeded on a premise the auditor had blocked, all to stop
an over-zealous auditor from deadlocking a run. The 2026-07-17 artifact is what
that bought: a 93/100 production_ready compilation whose premise an informed
viewer rejects on sight. The contracts below are the corrected ones — a run that
cannot establish its premise is worth less than a run that stops."""

from __future__ import annotations

import pytest

import omnicast.agents.narrative_pipeline as np
from omnicast.agents.narrative_pipeline import (
    FinalCompilationReview,
    NarrativeUnitPipeline,
    PlanAuditUnavailable,
    PlanIssue,
    PlanNotPlausible,
    PlanPlausibilityReview,
    StoryOutput,
    StoryPatchCandidate,
    StoryPatchCandidateSet,
    StoryTextEdit,
    plan_audit_blockers,
)

from tests.unit.test_narrative_unit_pipeline import (
    _FakeStructuredLLM,
    _approved_final_review,
    _brief,
    _draft,
    _narration,
    _passing_score,
    _plan,
    _variant_plan,
)
from tests.unit.test_narrative_writer_reliability import (
    _banned_initial,
    _issue_score,
)


# ---------------------------------------------------------------------------
# 1. Blocking plan defects are derived locally; the auditor never self-approves.


def test_plan_audit_blockers_derive_locally_from_severity():
    review = PlanPlausibilityReview(issues=[
        PlanIssue(
            story_id="story_1", category="professional", severity="critical",
            problem="a standard breaker cannot reset itself",
            plan_fix="swap the self-resetting breaker for a GFCI someone tripped",
            evidence_quote="different human threat 1",
        ),
        PlanIssue(
            story_id="story_2", category="trope", severity="minor",
            problem="slightly familiar premise", plan_fix="vary the setting",
        ),
    ])
    blockers = plan_audit_blockers(review)
    assert len(blockers) == 1
    assert "story_1" in blockers[0]
    assert "cannot reset itself" in blockers[0]
    assert "GFCI" in blockers[0]


def test_every_major_blocks_and_only_minors_pass():
    """Superseded contract: a lone major used to be discarded as a warning and
    only two majors on one story blocked. A plan is cheap to redo and a shot video
    is not, so one grounded major is enough."""
    single = PlanPlausibilityReview(issues=[PlanIssue(
        story_id="story_1", category="geography", severity="major",
        problem="exit is behind the threat", plan_fix="move the exit",
        evidence_quote="different practical escape 1",
    )])
    blockers = plan_audit_blockers(single)
    assert len(blockers) == 1
    assert "exit is behind the threat" in blockers[0]
    assert "move the exit" in blockers[0]

    double = PlanPlausibilityReview(issues=[
        PlanIssue(story_id="story_1", category="geography", severity="major",
                  problem="exit is behind the threat", plan_fix="move the exit",
                  evidence_quote="different practical escape 1"),
        PlanIssue(story_id="story_1", category="prop_staging", severity="major",
                  problem="the mop cart is never staged before use",
                  plan_fix="stage the cart in the setup",
                  evidence_quote="different human threat 1"),
    ])
    assert len(plan_audit_blockers(double)) == 2

    minor_only = PlanPlausibilityReview(issues=[PlanIssue(
        story_id="story_2", category="trope", severity="minor",
        problem="slightly familiar premise", plan_fix="vary the setting",
    )])
    assert plan_audit_blockers(minor_only) == []


def test_plan_issue_optional_text_accepts_provider_null():
    issue = PlanIssue.model_validate({
        "story_id": None, "category": "physical", "severity": "minor",
        "problem": "p", "plan_fix": None,
    })
    assert issue.story_id == ""
    assert issue.plan_fix == ""
    review = PlanPlausibilityReview.model_validate({"issues": None, "summary": None})
    assert review.issues == []
    assert review.summary == ""


# ---------------------------------------------------------------------------
# 2. Audit wiring: a block sends the planner back with the fix and it must return
#    a materially repaired plan; an unreachable auditor aborts before the writer;
#    an unresolved block at the bound aborts rather than drafting anyway.


def _clean_writer(initial: dict):
    def write(prompt, _schema):
        sid = next(s for s in initial if s in prompt)
        draft = initial[sid]
        return StoryOutput(
            title=draft.title, hook_candidates=draft.hook_candidates,
            narration=draft.narration,
        )
    return write


@pytest.mark.asyncio
async def test_plan_audit_blocker_feeds_the_planner_a_repaired_second_attempt():
    """A blocked plan is replanned with the auditor's fix, and the repaired plan
    is accepted on its merits. Rejecting a candidate must not burn its concept:
    the repair keeps the same mechanisms and only fixes what was objected to."""
    planner_prompts: list[str] = []
    state = {"attempt": 0}

    def plan_handler(prompt, _schema):
        planner_prompts.append(prompt)
        state["attempt"] += 1
        if state["attempt"] == 1:
            return _plan()
        # The repair: same concept, materially changed premise text.
        return _plan().model_copy(update={"stories": [
            _plan().stories[0].model_copy(update={
                "threat": "a maintenance worker cuts the power at the panel by hand",
            }),
            *_plan().stories[1:],
        ]})

    initial = {f"story_{i}": _draft(i) for i in range(1, 4)}
    audits = iter([
        PlanPlausibilityReview(issues=[PlanIssue(
            story_id="story_1", category="professional", severity="critical",
            problem="a standard breaker cannot reset itself",
            plan_fix="give the power cut a human cause",
            evidence_quote="different human threat 1",
        )]),
        PlanPlausibilityReview(),
    ])

    def judge(_prompt, schema):
        if schema is PlanPlausibilityReview:
            return next(audits)
        if schema is FinalCompilationReview:
            return _approved_final_review()
        return _passing_score()

    result = await NarrativeUnitPipeline(
        _FakeStructuredLLM(plan_handler), _FakeStructuredLLM(_clean_writer(initial)),
        _FakeStructuredLLM(judge, auto_plan_audit=False), None,
    ).run(_brief(), annotate=False)

    assert result.call_counts["planner"] == 2
    assert result.call_counts["plan_audit"] == 2
    assert "cannot reset itself" in planner_prompts[1]
    assert "give the power cut a human cause" in planner_prompts[1]
    assert result.content_locked is True
    assert result.plan_audit.status == "valid"
    assert result.plan.stories[0].threat.startswith("a maintenance worker")


@pytest.mark.asyncio
async def test_a_planner_that_resends_the_blocked_plan_verbatim_is_told_so():
    """Ignoring the audit feedback is a distinct failure from failing to fix it,
    and the run must not spend three identical audits discovering the same block."""
    planner_prompts: list[str] = []

    def plan_handler(prompt, _schema):
        planner_prompts.append(prompt)
        return _plan()

    def judge(_prompt, schema):
        if schema is PlanPlausibilityReview:
            return PlanPlausibilityReview(issues=[PlanIssue(
                story_id="story_1", category="professional", severity="critical",
                problem="a standard breaker cannot reset itself",
                plan_fix="give the power cut a human cause",
                evidence_quote="different human threat 1",
            )])
        return _passing_score()

    writer = _FakeStructuredLLM(lambda _p, _s: pytest.fail("writer must not be called"))
    pipe = NarrativeUnitPipeline(
        _FakeStructuredLLM(plan_handler), writer,
        _FakeStructuredLLM(judge, auto_plan_audit=False), None,
    )
    with pytest.raises(PlanNotPlausible) as excinfo:
        await pipe.run(_brief(), annotate=False)

    assert "identical plan that was just rejected" in str(excinfo.value)
    assert writer.calls == []
    # The audit runs once; the verbatim resends are caught locally and for free.
    fresh_plans = [p for p in planner_prompts if "Repair ONLY the blocked" not in p]
    assert len(fresh_plans) == pipe.max_plan_attempts
    assert pipe._run_call_counts["plan_audit"] == 1
    # The first block earns one targeted repair; its output is not a repair object,
    # so it is rejected and the loop falls back to replanning.
    assert pipe._run_call_counts["plan_repair"] == 1


@pytest.mark.asyncio
async def test_clean_plan_audit_costs_one_call_and_no_planner_retry():
    initial = {f"story_{i}": _draft(i) for i in range(1, 4)}

    def judge(_prompt, schema):
        if schema is PlanPlausibilityReview:
            return PlanPlausibilityReview()
        if schema is FinalCompilationReview:
            return _approved_final_review()
        return _passing_score()

    result = await NarrativeUnitPipeline(
        _FakeStructuredLLM(lambda _p, _s: _plan()),
        _FakeStructuredLLM(_clean_writer(initial)), _FakeStructuredLLM(judge), None,
    ).run(_brief(), annotate=False)

    assert result.call_counts["planner"] == 1
    assert result.call_counts["plan_audit"] == 1
    assert result.plan_audit_warnings == []
    assert result.content_locked is True


@pytest.mark.asyncio
async def test_plan_audit_infra_failure_aborts_before_the_writer():
    """Superseded contract: an exception used to return [] — indistinguishable
    from a clean audit. A provider outage, a 402, and a sound premise all read the
    same, so an unaudited premise shipped as an audited one."""
    initial = {f"story_{i}": _draft(i) for i in range(1, 4)}
    writer = _FakeStructuredLLM(_clean_writer(initial))

    def judge(_prompt, schema):
        if schema is PlanPlausibilityReview:
            raise ValueError("provider returned malformed JSON")
        if schema is FinalCompilationReview:
            return _approved_final_review()
        return _passing_score()

    pipe = NarrativeUnitPipeline(
        _FakeStructuredLLM(lambda _p, _s: _plan()), writer,
        _FakeStructuredLLM(judge, auto_plan_audit=False), None,
    )
    with pytest.raises(PlanAuditUnavailable) as excinfo:
        await pipe.run(_brief(), annotate=False)

    assert excinfo.value.audit.status == "infra_failed"
    assert any("malformed JSON" in item for item in excinfo.value.audit.provider_errors)
    assert writer.calls == [], "no draft is paid for against an unaudited premise"
    # One planner call, two auditor attempts, then stop — not a retry storm.
    assert pipe._run_call_counts["planner"] == 1
    assert pipe._run_call_counts["plan_audit"] == 2


@pytest.mark.asyncio
async def test_unresolved_blocker_at_the_attempt_bound_aborts_instead_of_drafting():
    """Superseded contract: the final planner attempt used to proceed with the
    auditor's objection demoted to a 'warning' so an over-zealous auditor could
    not deadlock the run. That is exactly how a premise an ex-cop would laugh at
    reached production_ready. The outer loop retries a fresh concept instead."""
    initial = {f"story_{i}": _draft(i) for i in range(1, 4)}
    writer = _FakeStructuredLLM(_clean_writer(initial))
    blocker = PlanIssue(
        story_id="story_1", category="physical", severity="critical",
        problem="the door cannot lock from both sides", plan_fix="use one lock",
        evidence_quote="different human threat 1",
    )
    state = {"attempt": 0}

    def plan_handler(_prompt, _schema):
        state["attempt"] += 1
        # A planner that materially changes the plan every time and still never
        # resolves the objection: the bound must stop it, not accept it.
        return _variant_plan(state["attempt"] - 1)

    def judge(_prompt, schema):
        if schema is PlanPlausibilityReview:
            return PlanPlausibilityReview(issues=[blocker])
        if schema is FinalCompilationReview:
            return _approved_final_review()
        return _passing_score()

    pipe = NarrativeUnitPipeline(
        _FakeStructuredLLM(plan_handler), writer,
        _FakeStructuredLLM(judge, auto_plan_audit=False), None,
    )
    with pytest.raises(PlanNotPlausible) as excinfo:
        await pipe.run(_brief(), annotate=False)

    assert pipe._run_call_counts["planner"] == pipe.max_plan_attempts
    assert writer.calls == []
    assert excinfo.value.audit.status == "blocked"
    assert any("cannot lock from both sides" in item for item in excinfo.value.audit.blockers)
    # Every rejected premise stays on the audit trail as evidence.
    assert len(excinfo.value.rejected_plans) == pipe.max_plan_attempts
    assert len(excinfo.value.rejection_reasons) == pipe.max_plan_attempts


# ---------------------------------------------------------------------------
# 3. Outer retry: a failed compilation regenerates with a DIFFERENT concept and
#    an explicit account of why the last one failed — no human edit step.


@pytest.mark.asyncio
async def test_failed_compilation_retries_once_with_a_fresh_plan_brief():
    state = {"attempt": 0}
    planner_prompts: list[str] = []

    def plan_handler(prompt, _schema):
        state["attempt"] += 1
        planner_prompts.append(prompt)
        # A fresh concept per attempt: "plan something different" is now enforced,
        # so a planner that returns the spent beat sheet never reaches a writer.
        return _variant_plan(state["attempt"] - 1)

    banned = _banned_initial()
    clean = {f"story_{i}": _draft(i) for i in range(1, 4)}

    def write(prompt, _schema):
        drafts = banned if state["attempt"] == 1 else clean
        sid = next(s for s in drafts if s in prompt)
        if "Surgically repair" in prompt:
            return StoryPatchCandidateSet(candidates=[
                StoryPatchCandidate(candidate_id="candidate_1", edits=[StoryTextEdit(
                    find="text that is not present", replace="replacement",
                )]),
                StoryPatchCandidate(candidate_id="candidate_2", edits=[StoryTextEdit(
                    find="other text that is not present", replace="replacement",
                )]),
            ])
        draft = drafts[sid]
        return StoryOutput(
            title=draft.title, hook_candidates=draft.hook_candidates,
            narration=draft.narration,
        )

    def judge(_prompt, schema):
        if schema is PlanPlausibilityReview:
            return PlanPlausibilityReview()
        if schema is FinalCompilationReview:
            return _approved_final_review()
        return _issue_score() if state["attempt"] == 1 else _passing_score()

    result = await NarrativeUnitPipeline(
        _FakeStructuredLLM(plan_handler), _FakeStructuredLLM(write),
        _FakeStructuredLLM(judge), None,
    ).run_with_retry(_brief(), annotate=False)

    assert result.attempt == 2
    assert result.content_locked is True
    assert "FAILED PREVIOUS ATTEMPT" in planner_prompts[1]
    # The avoid brief names the failed premises so the planner varies them.
    assert "different human threat 1" in planner_prompts[1]


@pytest.mark.asyncio
async def test_locked_first_attempt_never_pays_for_a_retry():
    planner = _FakeStructuredLLM(lambda _p, _s: _plan())
    initial = {f"story_{i}": _draft(i) for i in range(1, 4)}

    def judge(_prompt, schema):
        if schema is PlanPlausibilityReview:
            return PlanPlausibilityReview()
        if schema is FinalCompilationReview:
            return _approved_final_review()
        return _passing_score()

    result = await NarrativeUnitPipeline(
        planner, _FakeStructuredLLM(_clean_writer(initial)),
        _FakeStructuredLLM(judge), None,
    ).run_with_retry(_brief(), annotate=False)

    assert result.attempt == 1
    assert result.content_locked is True
    assert len(planner.calls) == 1


@pytest.mark.asyncio
async def test_both_failed_attempts_return_the_higher_ranked_one():
    state = {"attempt": 0}

    def plan_handler(_prompt, _schema):
        state["attempt"] += 1
        return _plan()

    banned = _banned_initial()

    def write(prompt, _schema):
        sid = next(s for s in banned if s in prompt)
        if "Surgically repair" in prompt:
            return StoryPatchCandidateSet(candidates=[
                StoryPatchCandidate(candidate_id="candidate_1", edits=[StoryTextEdit(
                    find="text that is not present", replace="replacement",
                )]),
                StoryPatchCandidate(candidate_id="candidate_2", edits=[StoryTextEdit(
                    find="other text that is not present", replace="replacement",
                )]),
            ])
        draft = banned[sid]
        return StoryOutput(
            title=draft.title, hook_candidates=draft.hook_candidates,
            narration=draft.narration,
        )

    weaker = _issue_score().model_copy(update={"continuity_believability": 10})

    def judge(_prompt, schema):
        if schema is PlanPlausibilityReview:
            return PlanPlausibilityReview()
        if schema is FinalCompilationReview:
            return _approved_final_review()
        return _issue_score() if state["attempt"] == 1 else weaker

    result = await NarrativeUnitPipeline(
        _FakeStructuredLLM(plan_handler), _FakeStructuredLLM(write),
        _FakeStructuredLLM(judge), None,
    ).run_with_retry(_brief(), annotate=False)

    assert result.content_locked is False
    assert result.attempt == 1
    assert result.scorecard.total_score > weaker.total_score


# ---------------------------------------------------------------------------
# 4. Last-mile closure (from the 2026-07-17 0/3 live batch):
#    (a) length defects skip the patch contract — no surgical edit budget can
#        add ~115 words — and go straight to the bounded rewrite;
#    (b) a patch pair that materializes but leaves a story's deterministic gate
#        failures un-reduced escalates to the rewrite instead of shipping a
#        cosmetic fix (gas-station build kept a banned-phrase variant);
#    (c) a release-blocking dimension deduction with ZERO critical/major issues
#        is an ungrounded verdict — the critic gets exactly one grounding
#        re-score, then the run fails closed.


from tests.unit.test_narrative_writer_reliability import _rewrite_writer


@pytest.mark.asyncio
async def test_length_defects_skip_the_patch_contract_entirely():
    planner = _FakeStructuredLLM(lambda _p, _s: _plan())
    initial = {f"story_{i}": _draft(i) for i in range(1, 4)}
    initial["story_2"] = _draft(2, words=630)
    log: dict = {}
    write = _rewrite_writer(initial, {"story_2": _narration("stretched", 760)}, log)

    def judge(_prompt, schema):
        if schema is FinalCompilationReview:
            return _approved_final_review()
        return _passing_score()

    result = await NarrativeUnitPipeline(
        planner, _FakeStructuredLLM(write), _FakeStructuredLLM(judge), None,
    ).run(_brief(), annotate=False)

    assert result.call_counts["repair_writer"] == 0
    assert "patch_prompts" not in log
    assert result.call_counts["repair_rewrite"] == 1
    assert result.gate_report.passed is True
    assert result.content_locked is True


@pytest.mark.asyncio
async def test_cosmetic_patches_that_leave_gate_failures_escalate_to_rewrite():
    planner = _FakeStructuredLLM(lambda _p, _s: _plan())
    initial = _banned_initial()
    anchor = initial["story_1"].narration.split("\n\n")[3]
    clean = _draft(1).narration
    log: dict = {}

    def write(prompt, _schema):
        sid = next(s for s in initial if s in prompt)
        if "Surgically repair" in prompt:
            log.setdefault("patch_prompts", []).append(prompt)
            # Valid, materializable edits that do NOT remove the banned phrase.
            return StoryPatchCandidateSet(candidates=[
                StoryPatchCandidate(candidate_id="candidate_1", edits=[StoryTextEdit(
                    find=anchor, replace=anchor.replace("detail", "latched", 1),
                )]),
                StoryPatchCandidate(candidate_id="candidate_2", edits=[StoryTextEdit(
                    find=anchor, replace=anchor.replace("detail", "secured", 1),
                )]),
            ])
        if "patch contract" in prompt:
            log.setdefault("rewrite_prompts", []).append(prompt)
            return StoryOutput(
                title="Unit 1", hook_candidates=["hook 1"], narration=clean,
            )
        draft = initial[sid]
        return StoryOutput(
            title=draft.title, hook_candidates=draft.hook_candidates,
            narration=draft.narration,
        )

    scores = iter([_issue_score(), _passing_score()])

    def judge(_prompt, schema):
        if schema is FinalCompilationReview:
            return _approved_final_review()
        return next(scores)

    result = await NarrativeUnitPipeline(
        planner, _FakeStructuredLLM(write), _FakeStructuredLLM(judge), None,
    ).run(_brief(), annotate=False)

    assert result.call_counts["repair_writer"] == 1
    assert result.call_counts["repair_rewrite"] == 1
    assert result.stories[0].narration == clean
    decision = next(d for d in result.patch_decisions if d.story_id == "story_1")
    assert decision.selected == "full_rewrite"
    assert result.content_locked is True


# ---------------------------------------------------------------------------
# 4b. Judges cite narration through a JSON round-trip that mangles whitespace;
#     a genuinely grounded review must not die on 'quote not found' (third live
#     batch: three clean 93-100 compilations blocked ONLY by this).


@pytest.mark.asyncio
async def test_final_review_survives_whitespace_mangled_quotes():
    stories = [_draft(i) for i in range(1, 4)]
    quote = stories[0].narration.split("\n\n")[2]
    mangled = "  " + quote.replace(" ", "  ") + "  "
    payload = FinalCompilationReview(
        approved=False, reviewed_story_ids=["story_1", "story_2", "story_3"],
        issues=[np.StoryIssue(
            story_id="story_1", severity="major", issue_kind="contradiction",
            problem="a grounded blocker", repair_instruction="fix it",
            evidence_quote=mangled, viewer_impact="v", issue_id="fa_1",
        )],
        summary="one blocker",
    )
    pipe = NarrativeUnitPipeline(
        _FakeStructuredLLM(lambda _p, _s: _plan()),
        _FakeStructuredLLM(lambda _p, _s: None),
        _FakeStructuredLLM(lambda _p, _s: payload), None,
    )
    review, approved = await pipe._final_review(
        _plan(), stories, pipe.quality_strategy
    )
    assert approved is False  # a grounded blocker still blocks
    assert "contract failed" not in review.summary
    assert review.issues[0].evidence_quote == quote


@pytest.mark.asyncio
async def test_critic_scorecard_quotes_are_canonicalized_across_whitespace():
    stories = [_draft(i) for i in range(1, 4)]
    quote = stories[1].narration.split("\n\n")[1]
    payload = _passing_score().model_copy(update={"story_issues": [np.StoryIssue(
        story_id="story_2", severity="major", issue_kind="contradiction",
        problem="p", repair_instruction="r",
        evidence_quote=quote.replace(" ", "   "),
        viewer_impact="v", issue_id="cs_1",
    )]})
    pipe = NarrativeUnitPipeline(
        _FakeStructuredLLM(lambda _p, _s: _plan()),
        _FakeStructuredLLM(lambda _p, _s: None),
        _FakeStructuredLLM(lambda _p, _s: payload), None,
    )
    plan = _plan()
    gate = np.gate_compilation(plan, stories)
    score, valid, errors = await pipe._score_validated(
        plan, stories, gate, pipe.quality_strategy
    )
    assert valid is True
    assert errors == []
    assert score.story_issues[0].evidence_quote == quote


# ---------------------------------------------------------------------------
# 5. Reliability (from the 2026-07-17 second live batch): an attempt that
#    ABORTS (planner preflight, provider outage) must not kill the outer retry,
#    and a cold open a few words over the cap is trimmed locally instead of
#    throwing away an otherwise good plan.


@pytest.mark.asyncio
async def test_an_aborted_attempt_does_not_kill_the_outer_retry():
    state = {"planner_calls": 0}
    pipe: NarrativeUnitPipeline | None = None

    def plan_handler(_prompt, _schema):
        state["planner_calls"] += 1
        # Every inner try of attempt 1 dies, so attempt 1 aborts outright. Each of
        # its plan attempts costs two calls: the plan, then one contract-only
        # schema/provider retry.
        if state["planner_calls"] <= pipe.max_plan_attempts * 2:
            raise ValueError("provider outage")
        return _plan()

    initial = {f"story_{i}": _draft(i) for i in range(1, 4)}

    def judge(_prompt, schema):
        if schema is FinalCompilationReview:
            return _approved_final_review()
        return _passing_score()

    pipe = NarrativeUnitPipeline(
        _FakeStructuredLLM(plan_handler), _FakeStructuredLLM(_clean_writer(initial)),
        _FakeStructuredLLM(judge), None,
    )
    result = await pipe.run_with_retry(_brief(), annotate=False)

    assert result.attempt == 2
    assert result.content_locked is True
    # The dead attempt is on the bill, not written off.
    assert result.attempts_executed == 2
    assert result.attempt_summaries[0].outcome == "aborted"
    assert "provider outage" in result.attempt_summaries[0].reason
    assert result.attempt_summaries[0].call_counts["planner"] == pipe.max_plan_attempts
    assert result.call_counts["planner"] == 1
    assert result.aggregate_call_counts["planner"] == pipe.max_plan_attempts + 1


@pytest.mark.asyncio
async def test_every_attempt_aborting_reraises_the_last_error():
    def plan_handler(_prompt, _schema):
        raise ValueError("provider outage")

    def judge(_prompt, schema):
        if schema is FinalCompilationReview:
            return _approved_final_review()
        return _passing_score()

    with pytest.raises(ValueError):
        await NarrativeUnitPipeline(
            _FakeStructuredLLM(plan_handler),
            _FakeStructuredLLM(lambda _p, _s: None), _FakeStructuredLLM(judge), None,
        ).run_with_retry(_brief(), annotate=False)


def test_overlong_two_sentence_cold_open_is_trimmed_to_its_first_sentence():
    long_tail = " ".join(f"w{i}" for i in range(30))
    plan = _plan().model_copy(update={
        "cold_open": "I still keep the porch light off. " + long_tail + ".",
    })
    salvaged = np._salvage_cold_open(plan)
    assert salvaged.cold_open == "I still keep the porch light off."
    assert len(np._words(salvaged.cold_open)) <= 28


def test_single_overlong_sentence_cold_open_is_left_for_preflight_to_reject():
    one_long_sentence = " ".join(f"w{i}" for i in range(35)) + "."
    plan = _plan().model_copy(update={"cold_open": one_long_sentence})
    salvaged = np._salvage_cold_open(plan)
    assert salvaged.cold_open == one_long_sentence


def test_compliant_cold_open_is_untouched():
    plan = _plan()
    assert np._salvage_cold_open(plan).cold_open == plan.cold_open


# ---------------------------------------------------------------------------
# 6. Salvage-single-patch: a rejected multi-story wave gets one bounded rescue
#    keeping only the heaviest-blocker story's patch (live 2026-07-18 1903: a
#    geography fix the blind selector praised was thrown away because a sibling
#    patch regressed).


@pytest.mark.asyncio
async def test_rejected_wave_salvages_the_heaviest_correct_patch():
    initial = _banned_initial()  # story_1 carries the banned-phrase gate failure
    stories = [initial[f"story_{i}"] for i in range(1, 4)]
    clean_1 = _draft(1)  # the correct patch: banned phrase gone
    # The sibling patch regressed story_2 with a fresh banned phrase.
    bad_2 = _draft(2).model_copy(update={
        "narration": "I told myself it was nothing. " + _draft(2).narration,
    })
    candidate_list = [clean_1, bad_2, stories[2]]

    def judge(_prompt, schema):
        if schema is PlanPlausibilityReview:
            return PlanPlausibilityReview()
        if schema is FinalCompilationReview:
            return _approved_final_review()
        return _passing_score()

    pipe = NarrativeUnitPipeline(
        _FakeStructuredLLM(lambda _p, _s: _plan()),
        _FakeStructuredLLM(lambda _p, _s: None),
        _FakeStructuredLLM(judge), None,
    )
    plan = _plan()
    gate = np.gate_compilation(plan, stories, pipe.quality_strategy)
    score = _issue_score()  # major on story_1 → heaviest blocker
    pipe._run_call_counts = {}
    # The real wave always holds a full prior review set for unchanged stories.
    prior, prior_valid = await pipe._audit_stories(plan, stories, pipe.quality_strategy)
    assert prior_valid
    result = await pipe._salvage_single_patch(
        plan, stories, candidate_list, {"story_1", "story_2"},
        score, gate, pipe.quality_strategy, prior,
    )
    assert result is not None
    solo, solo_gate, solo_score, _reviews = result
    assert solo[0].narration == clean_1.narration      # correct patch kept
    assert solo[1].narration == stories[1].narration   # regressing patch dropped
    assert solo_gate.passed is True


@pytest.mark.asyncio
async def test_single_story_wave_gets_no_salvage():
    pipe = NarrativeUnitPipeline(
        _FakeStructuredLLM(lambda _p, _s: _plan()),
        _FakeStructuredLLM(lambda _p, _s: None),
        _FakeStructuredLLM(lambda _p, _s: _passing_score()), None,
    )
    plan = _plan()
    stories = [_draft(i) for i in range(1, 4)]
    result = await pipe._salvage_single_patch(
        plan, stories, stories, {"story_1"},
        _issue_score(), np.gate_compilation(plan, stories, pipe.quality_strategy),
        pipe.quality_strategy, {},
    )
    assert result is None


@pytest.mark.asyncio
async def test_ungrounded_below_floor_deduction_gets_one_grounding_rescore():
    planner = _FakeStructuredLLM(lambda _p, _s: _plan())
    initial = {f"story_{i}": _draft(i) for i in range(1, 4)}
    # 21 < continuity_min 22 with ZERO critical/major issues: the gas-station
    # build died exactly here — a deduction nothing downstream could act on.
    ungrounded = _passing_score().model_copy(update={"continuity_believability": 21})
    scores = iter([ungrounded, _passing_score()])

    def judge(_prompt, schema):
        if schema is FinalCompilationReview:
            return _approved_final_review()
        return next(scores)

    critic = _FakeStructuredLLM(judge)
    result = await NarrativeUnitPipeline(
        planner, _FakeStructuredLLM(_clean_writer(initial)), critic, None,
    ).run(_brief(), annotate=False)

    assert result.call_counts["critic_score"] == 2
    assert any("below the release floor" in call for call in critic.calls)
    assert result.content_locked is True


@pytest.mark.asyncio
async def test_persistently_ungrounded_deduction_still_fails_closed():
    planner = _FakeStructuredLLM(lambda _p, _s: _plan())
    initial = {f"story_{i}": _draft(i) for i in range(1, 4)}
    ungrounded = _passing_score().model_copy(update={"continuity_believability": 21})

    def judge(_prompt, schema):
        if schema is FinalCompilationReview:
            return _approved_final_review()
        return ungrounded

    result = await NarrativeUnitPipeline(
        planner, _FakeStructuredLLM(_clean_writer(initial)),
        _FakeStructuredLLM(judge), None,
    ).run(_brief(), annotate=False)

    assert result.call_counts["critic_score"] == 2
    assert result.content_locked is False


@pytest.mark.asyncio
async def test_grounded_below_floor_deduction_is_not_challenged():
    planner = _FakeStructuredLLM(lambda _p, _s: _plan())
    initial = {f"story_{i}": _draft(i) for i in range(1, 4)}
    grounded = _issue_score().model_copy(update={"continuity_believability": 21})

    def judge(_prompt, schema):
        if schema is FinalCompilationReview:
            return _approved_final_review()
        return grounded

    critic = _FakeStructuredLLM(judge)
    result = await NarrativeUnitPipeline(
        planner, _FakeStructuredLLM(_clean_writer(initial)), critic, None,
    ).run(_brief(), annotate=False)

    assert not any("below the release floor" in call for call in critic.calls)
    assert result.content_locked is False
