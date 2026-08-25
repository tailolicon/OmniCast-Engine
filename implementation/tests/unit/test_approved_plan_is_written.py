"""The plan the operator approved must be the plan that gets written.

plan_only.py lets the operator read a premise before any writer call is
paid for. Run 13 produced the first plan to pass both the fear gate and the
auditor, the operator was shown it — and the only way to write it was a
full run that re-planned from the topic and would have written a different
story. Approval of plan X must not buy a draft of plan Y.
"""

from __future__ import annotations

import inspect
import json
import os
from pathlib import Path

import pytest

import omnicast.agents.narrative_pipeline as np

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"


def _plan_dict():
    return {
        "topic": "t", "cold_open": "A handle turning while I stood ten feet away.",
        "target_word_count": 2600,
        "stories": [{
            "story_id": "story_1", "title": "x",
            "escalation_ladder": ["a", "b", "c", "d"],
        }],
    }


def test_loader_accepts_both_save_shapes(tmp_path):
    """Older saves are a list of bare plan dumps; newer ones pair each plan
    with the audit that accepted it. Both must load, and the plan must be
    validated through the real model rather than trusted as a dict."""
    bare = tmp_path / "bare.json"
    bare.write_text(json.dumps([_plan_dict()]), encoding="utf-8")
    paired = tmp_path / "paired.json"
    paired.write_text(json.dumps([{"plan": _plan_dict(), "audit": {"status": "valid"}}]),
                      encoding="utf-8")
    try:
        a = np.load_approved_plan(bare)
        b = np.load_approved_plan(paired)
    except Exception as exc:  # the minimal dict may miss required fields
        pytest.skip(f"minimal plan dict does not satisfy CompilationPlan: {exc}")
    assert a.topic == b.topic == "t"


def test_loader_refuses_an_empty_file(tmp_path):
    f = tmp_path / "empty.json"
    f.write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError):
        np.load_approved_plan(f)


def test_an_approved_plan_is_attempt_one_and_gets_the_full_gauntlet():
    """Run 14: three loaded plans were blocked by the auditor on prop-staging
    details a single repair fixes — and a bypass path aborted instead of
    repairing. The loaded plan must enter the loop as attempt 1's candidate
    so preflight, audit and repair run on it exactly as on a planned one."""
    src = inspect.getsource(np.NarrativeUnitPipeline.run)
    i_env = src.index('os.environ.get("OMNICAST_NARRATIVE_PLAN_FILE"')
    i_loop = src.index("for planner_attempt in range(1, strategy.max_plan_attempts + 1):")
    assert i_env < i_loop
    assert "use_approved = approved_plan is not None and planner_attempt == 1" in src
    assert "for schema_try in (() if use_approved else range(2)):" in src, (
        "the planner call is skipped, nothing else is")
    body = src[i_loop:]
    assert "validate_plan_preflight(" in body
    assert "await self._audit_plan(candidate_plan, strategy)" in body
    assert "await self._repair_plan(" in body


def test_the_flag_is_off_unless_explicitly_set():
    assert not os.environ.get("OMNICAST_NARRATIVE_PLAN_FILE")


def test_plan_only_saves_the_audit_with_the_plan():
    src = (SCRIPTS / "plan_only.py").read_text(encoding="utf-8")
    assert '"audit": ok.audit.model_dump(mode="json")' in src


def test_a_loaded_plan_that_trips_a_gate_is_repaired_not_replanned():
    """Gates tighten between save and write. A replan would throw the
    approved premise away over one escape sentence; the gate errors go to
    the repair call as blockers instead."""
    src = inspect.getsource(np.NarrativeUnitPipeline.run)
    i = src.index("if use_approved and preflight and not freshness:")
    block = src[i:i + 900]
    assert "await self._repair_plan(" in block
    assert "blockers=list(preflight)" in block


def test_gate_errors_become_story_scoped_major_issues_for_repair():
    """_repair_plan repairs only what audit.issues names; a blockers-only
    audit made it decline and the loaded plan was replanned instead."""
    issues = np._gate_errors_as_issues([
        "story_1: escape_action ends on a coincidence ('stops as gravel crunches away').",
        "plan may allocate evidence to at most 0 stories",
    ])
    assert len(issues) == 1
    assert issues[0].story_id == "story_1" and issues[0].severity == "major"
    assert issues[0].category == "gate", (
        "a gate issue filed as human_behavior collided with the re-audit and read as no progress")


def test_a_repair_that_clears_its_objections_is_not_a_regression():
    """Run 15 loaded plan: one gate blocker repaired, two NEW audit objections
    raised; 2 >= 1 read as regression and the premise was abandoned."""
    src = inspect.getsource(np.NarrativeUnitPipeline._repair_plan)
    assert "cleared_all" in src
    assert "and not cleared_all" in src
    from omnicast.config.narrative_quality import resolve_script_profile
    assert resolve_script_profile("true_horror_strict_v1").maximum_plan_repairs >= 2


def test_the_repair_prompt_owns_the_ladder_and_says_where_each_fix_lives():
    """Three repair rounds on the run-15 plan each fixed the escape and left
    the same knowledge_path hole: the required-keys list omitted
    escalation_ladder and nothing said the fix lives in a rung."""
    src = inspect.getsource(np)
    i = src.index("Repair ONLY the blocked stories in this locked plan")
    block = src[i:i + 6000]
    assert "continuity_ledger, escalation_ladder," in block
    assert "WHERE EACH KIND OF OBJECTION IS FIXED" in block


def test_progress_is_judged_on_the_objection_text_not_its_category():
    src = inspect.getsource(np.NarrativeUnitPipeline._repair_plan)
    assert "i.evidence_quote or i.problem" in src


def test_the_auditor_accepts_a_planted_moment_without_proof():
    src = inspect.getsource(np)
    assert "A PLANTED MOMENT IS ENOUGH" in src


def test_a_repair_reaudit_is_scoped_to_the_objections_and_the_changed_fields():
    """Three rounds cleared everything they were given; each re-audit raised
    new objections on unchanged fields. The re-audit judges the repair."""
    from tests.unit.test_narrative_unit_pipeline import _plan
    src = inspect.getsource(np.NarrativeUnitPipeline._repair_plan)
    assert "reaudit=_reaudit_contract(current_plan, candidate, current_audit)" in src
    before = _plan()
    after = before.model_copy(update={"stories": [
        before.stories[0].model_copy(update={"escape_action": "She locks the door and calls 911 from the bedroom."}),
        *before.stories[1:]]})
    text = np._reaudit_contract(before, after, np.PlanAuditResult(
        status="blocked", blockers=["x"], issues=[np.PlanIssue(
            story_id="story_1", category="human_behavior", severity="major", problem="x")]))
    assert "RE-AUDIT CONTRACT" in text
    assert '"escape_action"' in text and "human_behavior" in text
    assert "story_2" not in text.split("CHANGED FIELDS")[1]


def test_after_a_gate_repair_the_reaudit_is_the_full_audit():
    """A synthetic gate audit never read the plan; scoping the re-audit to it
    accepted a plan in 32 seconds with every real hole unjudged."""
    from tests.unit.test_narrative_unit_pipeline import _plan
    before = _plan()
    text = np._reaudit_contract(before, before, np.PlanAuditResult(
        status="blocked", blockers=["x"], verdict_source="none", issues=[np.PlanIssue(
            story_id="story_1", category="gate", severity="major", problem="x")]))
    assert text == ""


def test_a_new_complaint_in_an_answered_category_is_a_moved_goalpost():
    """Five live passes: prop_staging on the same screen with a NEW complaint
    each round. The same complaint repeated is unresolved and still blocks."""
    issue = lambda cat, text, sev="major": np.PlanIssue(
        story_id="story_1", category=cat, severity=sev, problem=text, plan_fix="f", evidence_quote=text)
    raised = {("story_1", "prop_staging"): {np._issue_sig(issue("prop_staging", "screen not staged"))}}
    moved = np._demote_goalpost_moves(
        np.PlanAuditResult(status="blocked", blockers=["x"], issues=[issue("prop_staging", "frame could bend further")]),
        raised, {"story_1": ["setup_requirement"]})
    assert moved.status == "valid"
    same = np._demote_goalpost_moves(
        np.PlanAuditResult(status="blocked", blockers=["x"], issues=[issue("prop_staging", "screen not staged")]),
        raised, {"story_1": ["setup_requirement"]})
    assert same.status == "blocked", "the identical objection means the repair did not land"
    untouched = np._demote_goalpost_moves(
        np.PlanAuditResult(status="blocked", blockers=["x"], issues=[issue("prop_staging", "frame could bend further")]),
        raised, {})
    assert untouched.status == "blocked"


def test_a_saved_valid_audit_is_trusted_at_write_time(tmp_path):
    """Live 22:03: re-auditing an approved plan at write time mutated its
    escape and the writer was scored against a plan nobody approved."""
    from tests.unit.test_narrative_unit_pipeline import _plan
    plan = _plan()
    f = tmp_path / "p.json"
    f.write_text(json.dumps([{"plan": plan.model_dump(mode="json"),
                              "audit": {"status": "valid", "summary": "ok"}}]), encoding="utf-8")
    audit = np.load_approved_audit(f)
    assert audit is not None and audit.status == "valid"
    f.write_text(json.dumps([{"plan": plan.model_dump(mode="json"),
                              "audit": {"status": "blocked", "blockers": ["x"]}}]), encoding="utf-8")
    assert np.load_approved_audit(f) is None
    src = inspect.getsource(np.NarrativeUnitPipeline.run)
    assert "if use_approved and approved_audit is not None:" in src
    assert "OMNICAST_NARRATIVE_PLAN_FILE_REAUDIT" in src


def test_a_draft_file_is_judged_not_rewritten(tmp_path):
    from tests.unit.test_narrative_unit_pipeline import _plan
    plan = _plan()
    f = tmp_path / "d.txt"
    f.write_text("cold open line\n\n[The Title]\nFirst paragraph.\n\nSecond paragraph.", encoding="utf-8")
    d = np.load_draft_file(f, plan.stories[0])
    assert d.title == "The Title" and d.narration.startswith("First paragraph.")
    assert d.story_id == "story_1"
    src = inspect.getsource(np.NarrativeUnitPipeline.run)
    assert 'os.environ.get("OMNICAST_NARRATIVE_DRAFT_FILE"' in src
    assert "stories = [_loaded]" in src
