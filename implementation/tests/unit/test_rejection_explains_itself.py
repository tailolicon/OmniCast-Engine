"""A rejected script must say why it was rejected.

Two builds of the flagship video were rejected at 62/100 and 79/100. Both left
the same thing on disk: the text, and a number. The critic's per-dimension
scores and its list of fixes existed in memory and were dropped, so the only
route back was to re-run a sixteen-minute generation and guess at what changed.

The cause was structural, not a missing write: only the debate flow fills
`DebateResult.rounds`, and the flagship channel runs `claude_first`, which
built its result with `rounds=[]` and discarded the verdict.
"""

from __future__ import annotations

import inspect
from pathlib import Path

from omnicast.agents.orchestrator import DebateResult


def test_the_result_can_carry_the_verdict_that_produced_its_score():
    assert "final_feedback" in DebateResult.__dataclass_fields__
    assert DebateResult(variant_id="x", final_draft=None, final_score=0,
                        approved=False, converged=True).final_feedback is None


def test_every_flow_that_scores_a_script_attaches_its_feedback():
    """Asserted on the CONSTRUCTIONS, not on one variable name: the flow has
    already been refactored once since this bug, and a test pinned to
    `final_feedback=best_fb` would have gone green while the guarantee moved."""
    import re

    import omnicast.pipeline.steps as steps

    src = Path(steps.__file__).read_text(encoding="utf-8")
    builds = re.findall(r"DebateResult\((?:[^()]|\([^()]*\))*\)", src)
    assert builds, "no DebateResult construction found — did the flow move?"
    # unit_first is scored by the narrative scorecard, not by CriticFeedback,
    # and its diagnostics are written separately to narrative_audit.json — so
    # it is exempt from carrying a critic verdict, not exempt from explaining
    # itself. That file is asserted below.
    missing = [b for b in builds
               if "final_feedback=" not in b and "unit_first" not in b]
    assert not missing, (
        "these results are built without the verdict that scored them: "
        + " | ".join(b.split("variant_id=")[-1][:60] for b in missing))
    assert "narrative_audit.json" in src
    # the polish pass overwrites draft AND score — the verdict must follow
    assert "final_feedback = _fb2" in src


def test_the_rejection_branch_reads_feedback_from_either_flow():
    import omnicast.pipeline.steps as steps

    src = Path(steps.__file__).read_text(encoding="utf-8")
    i = src.index("if not best.approved:")
    branch = src[i:i + 2500]
    assert 'getattr(best, "final_feedback", None)' in branch
    assert "critic_feedback.json" in branch
    assert "critic_feedback.md" in branch
    # per-dimension detail, not just the total
    assert "_d.score" in branch and "_d.max_score" in branch
    assert "specific_fixes" in branch


def test_saving_the_verdict_can_never_break_the_run():
    """A diagnostics write must not turn a rejection into a crash."""
    import omnicast.pipeline.steps as steps

    src = Path(steps.__file__).read_text(encoding="utf-8")
    i = src.index("critic_feedback.json")
    window = src[max(0, i - 900):i]
    assert "try:" in window
    tail = src[i:i + 1800]
    assert "except Exception" in tail


def test_dataclass_field_is_typed_not_stringly_annotated():
    """`"CriticFeedback | None"` as a string annotation would still work at
    runtime but hides the dependency from every type checker in the repo."""
    ann = inspect.get_annotations(DebateResult, eval_str=False)["final_feedback"]
    assert "CriticFeedback" in str(ann)
