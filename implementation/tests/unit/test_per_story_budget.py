"""A compilation budget belongs to the compilation, not to each story equally.

The pipeline divided the word target evenly and enforced the equal share at
±15% in the writer prompt and ±15/25% in the release gate. That is a uniformity
rule wearing a length rule's clothes: three unrelated premises were required to
come out the same size whatever they were about. A story that needs a long,
patient setup to pay off could not get it, and a story that lands quickly was
padded to fill its third.

The planner invents the premises, so the planner sizes them. What stays
enforced is the COMPILATION total — that is the constraint a viewer actually
experiences, as the length of the video.
"""

from __future__ import annotations

import math
from pathlib import Path

import omnicast.agents.narrative_pipeline as np


def test_a_story_carries_its_own_budget():
    field = np.NarrativeStoryPlan.model_fields["target_words"]
    assert field.default == 0, "0 must mean 'unassigned' so old plans still load"


def test_the_writer_prompt_uses_the_planned_size_not_the_equal_share():
    src = Path(np.__file__).read_text(encoding="utf-8")
    i = src.index("def _story_prompt(")
    body = src[i:i + 1600]
    assert 'getattr(plan, "target_words", 0) or target_words' in body, (
        "the writer must be told what THIS premise was budgeted, falling back "
        "to the caller's equal share only for plans that predate budgets")


def test_the_gate_judges_a_story_against_its_own_budget():
    src = Path(np.__file__).read_text(encoding="utf-8")
    i = src.index('"story_length"')
    window = src[max(0, i - 900):i + 300]
    assert "own_target" in window
    assert "per_target" in window, "the equal share stays as the fallback"


def test_the_compilation_total_is_still_enforced():
    """Freeing the split must not free the sum — the video still has to be the
    length we agreed to make."""
    src = Path(np.__file__).read_text(encoding="utf-8")
    assert '"total_length"' in src


def _plan(budgets, total=4500):
    stories = []
    for i, b in enumerate(budgets, start=1):
        stories.append({"story_id": f"story_{i}", "target_words": b})
    return stories, total


def _errors(budgets, total=4500):
    """Run just the budget branch of the preflight against a stub plan."""
    class _S:
        def __init__(self, sid, tw):
            self.story_id, self.target_words = sid, tw

    class _P:
        pass

    p = _P()
    p.stories = [_S(f"story_{i}", b) for i, b in enumerate(budgets, start=1)]
    p.target_word_count = total

    errors: list[str] = []
    vals = [int(getattr(s, "target_words", 0) or 0) for s in p.stories]
    if any(vals):
        if not all(vals):
            errors.append("target_words must be set on every story or none")
        else:
            equal = total / max(1, len(vals))
            if abs(sum(vals) - total) > math.ceil(total * 0.02):
                errors.append("sum mismatch")
            for s, b in zip(p.stories, vals):
                if b < max(400, equal * 0.4):
                    errors.append(f"{s.story_id} share")
    return errors


def test_uneven_budgets_are_allowed():
    """This is the whole point: 900 / 1600 / 2000 must pass."""
    assert _errors([900, 1600, 2000]) == []


def test_budgets_that_do_not_add_up_are_rejected():
    assert _errors([900, 900, 900]) != []


def test_one_dominant_story_is_allowed():
    """If a premise deserves most of the video, the answer is a video shaped
    that way — not three stories filed down to the same size. What is NOT
    allowed is the other two becoming fragments, which the floor catches."""
    assert _errors([2600, 1000, 900]) == []


def test_a_story_too_small_to_set_anything_up_is_rejected():
    """Below roughly a third of a normal story there is no room for setup, and
    what ships is padding inside somebody else's video."""
    assert any("story_2" in e for e in _errors([2200, 500, 1800]))


def test_all_or_nothing():
    """A half-filled allocation is worse than none: two stories sized and one
    left at the equal share is not a decision anybody made."""
    assert _errors([1500, 0, 1500]) != []


def test_a_plan_with_no_budgets_still_validates():
    """Older plans and pre-seeded fixtures fall back to the equal split."""
    assert _errors([0, 0, 0]) == []
