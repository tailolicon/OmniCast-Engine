"""The profile must not order what the auditor forbids.

Two consecutive live runs, on two different topics, both died at
`plan_audit/human_behavior`, both on story_1, both with the same complaint:

    "A reasonable person would not remain stationary while a stranger
     approaches on foot at midnight."
    "A reasonable courier would not need to check the manifest to refuse an
     off-manifest package; the request itself is a red flag."

Neither was a bad topic. The profile told the planner to delay recognition
through "observation, checking, hesitation", and the auditor's own contract
says "no one preserves mystery over safety". The planner obeyed the profile and
was punished for it, twice, at roughly forty minutes a run.

Both sides were right about craft. The rule was wrong about where the delay
comes from: in a real account nobody is slow, the situation has simply not
declared itself yet.
"""

from __future__ import annotations

import re
from pathlib import Path

import omnicast.agents.narrative_pipeline as np
from omnicast.config.narrative_quality import SCRIPT_PROFILE_REGISTRY

PROFILE = SCRIPT_PROFILE_REGISTRY["true_horror_strict_v1"]
RULES = " ".join(PROFILE.dread_rules + PROFILE.planning_rules
                 + PROFILE.voice_rules)


def _auditor_contract() -> str:
    src = Path(np.__file__).read_text(encoding="utf-8")
    m = re.search(r"- human_behavior:(.*?)\n- prop_staging:", src, re.S)
    assert m, "the human_behavior contract moved; this test must follow it"
    return m.group(1)


def test_the_auditor_still_demands_a_reasonable_immediate_response():
    # The contract is wrapped across lines in the source, so compare on
    # collapsed whitespace rather than pinning where the line break falls.
    contract = " ".join(_auditor_contract().lower().split())
    assert "reasonable person" in contract
    assert "mystery over safety" in contract


def test_no_rule_asks_the_narrator_to_hesitate():
    """The specific words that caused it: a rule may not source the delay from
    the narrator's own slowness."""
    banned = ("through observation, checking, hesitation",
              "delay full recognition of danger through")
    lowered = RULES.lower()
    for phrase in banned:
        assert phrase not in lowered, (
            f"a rule tells the planner to delay via {phrase!r}, which "
            "plan_audit/human_behavior rejects on sight")


def test_the_delay_is_sourced_from_the_signal_not_the_person():
    lowered = RULES.lower()
    assert "signal ambiguous" in lowered, (
        "dread still needs a delay; it must come from the situation not having "
        "declared itself")
    assert "act at once" in lowered, (
        "and the rule must say what happens when it does declare itself, or it "
        "reads as permission to wait")


def test_the_rule_and_the_contract_agree_on_the_unmistakable_case():
    """Where they used to contradict: once the signal is clear, both now
    require immediate action."""
    contract = _auditor_contract().lower()
    assert "fight, flight" in contract or "defensive decision" in contract
    assert "act at once" in RULES.lower()


def test_the_auditor_judges_whether_they_act_not_how_well():
    """Round three of the same argument. With passivity fixed, the auditor
    moved to rejecting a real escape for being tactically suboptimal — "they
    would not reverse down a gravel lane with a known hay turnoff". That is a
    standard 85% of the genre fails: 125 of 147 competitor scripts contain a
    choice the narrator second-guesses later, and that regret is the texture of
    a true account, not a defect in it. The contract says "fight, flight"; it
    never said the flight had to be the best one."""
    contract = " ".join(_auditor_contract().lower().split())
    assert "whether they act" in contract
    assert "not the optimal one" in contract or "optimal" in contract
    assert "tactically imperfect" in contract
    # and the things it must still reject
    assert "passivity" in contract
    assert "curiosity that outranks safety" in contract


def test_the_auditor_does_not_run_the_ladder_backwards():
    """Run 10 (2026-08-22): two six-rung ladders, correct geometry, and the
    verdict 'after finding the deadbolt unlocked, a reasonable person would not
    stay alone in the house'. Measured against the corpus, that objection
    rejects the genre: every top-20 account has the narrator notice, explain
    away, and stay (median five times), the first departure lands at 32%, and
    59 of 147 never leave. Staying after a DENIABLE sign is the form; only
    staying after an undeniable one, or passivity at the last rung, is a
    defect."""
    contract = " ".join(_auditor_contract().lower().split())
    assert "staying after a deniable sign is not a defect" in contract
    assert "only after a sign that cannot be explained away" in contract
    assert "do not run the ladder backwards" in contract
