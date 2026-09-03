"""A ladder of clues is a detective story. Fear is present tense and distance.

Measured across 2,320 escalation sentences in 147 competitor scripts: 36%
have the threat ACTING while the narrator is there (a tap on the glass, a
handle turning, a figure that stays); 3% are traces found afterwards. The
first two plans this channel ever had accepted were 0/7 and 1/7 present-tense
and 3/7 trace — restacked woodpiles, a missing key, a note found on the door.
The auditor judged plausibility and freshness. Nobody had asked it about fear,
and the operator's reaction to the accepted plans was "this is not scary".
"""

from __future__ import annotations

import inspect

import omnicast.agents.narrative_pipeline as np

TRACE_LADDER = [
    "Gate unlatched though he latched it the night before.",
    "Boot prints by the coop, tread unlike his own.",
    "Porch light he switched off is lit again the next evening.",
    "Screen door found propped open with a stick that was not there that morning.",
    "A note listing the exact minute he fed the cat each night.",
]
PRESENT_LADDER = [
    "Gate unlatched though he latched it the night before.",
    "A tap on the bedroom window after midnight.",
    "Another tap, this time closer to the center of the glass.",
    "Footsteps on the porch, stopping outside the door.",
    "The door handle turns once, hard, while he stands behind it.",
]


def _plan(rungs):
    class _S:
        story_id = "story_1"
        escalation_ladder = rungs

    class _P:
        stories = [_S()]

    return _P()


def test_rung_kind_separates_acting_from_evidence():
    assert np.rung_kind("Another tap came, this time closer to the center of the glass.") == "present"
    assert np.rung_kind("Woodpile behind the garage restacked differently.") == "trace"


def test_a_ladder_of_traces_is_refused_before_any_paid_call():
    errs = np.ladder_fear_problems(_plan(TRACE_LADDER))
    assert errs and "present" in errs[0]


def test_a_present_tense_ladder_passes():
    assert np.ladder_fear_problems(_plan(PRESENT_LADDER)) == []


def test_a_trace_in_the_last_three_rungs_is_refused_even_if_the_count_is_fine():
    rungs = PRESENT_LADDER[:-1] + ["The next morning the gate is found propped open with a stick."]
    errs = np.ladder_fear_problems(_plan(rungs))
    assert errs and "last three" in errs[0]


def test_the_gate_is_wired_into_preflight():
    src = inspect.getsource(np.validate_plan_preflight)
    assert "ladder_fear_problems(plan)" in src


def test_the_planner_is_told_fear_is_present_tense():
    src = inspect.getsource(np._plan_prompt)
    assert "FEAR IS PRESENT TENSE AND DISTANCE" in src
    assert "ALL of the last three" in src


def test_single_story_length_is_not_the_whole_compilation():
    """With story_count forced to 1 the full 30-minute budget (4,500 words,
    ±10% on the writer) landed on one premise, so a seven-rung ladder had to
    be padded to 4,050+ words. Length should come from what the account has
    in it, not from a compilation envelope with two stories removed."""
    src = inspect.getsource(np.NarrativeUnitPipeline.run)
    # 23/08: superseded by the operator's rule — no forced word count at all.
    # The planner's own estimate is kept; nothing caps or floors it but sanity.
    assert "min(target_words, 2600)" not in src
    assert "THE PLANNER'S ESTIMATE IS KEPT" in src


def test_a_plan_without_a_ladder_is_refused():
    """Run 15 accepted a plan with no escalation_ladder at all: the fear gate
    skips ladders under four rungs, so nothing judged the empty one."""
    src = inspect.getsource(np.validate_plan_preflight)
    assert "escalation_ladder has" in src and "at least four" in src
    assert 'getattr(strategy, "require_ladder", False)' in src, (
        "hand-built test strategies have no ladders; only ladder-planning profiles require one")
    from omnicast.config.narrative_quality import resolve_script_profile
    strat = np.NamedChannelStrategy.from_quality_profile(resolve_script_profile("true_horror_strict_v1"))
    assert strat.require_ladder is True
