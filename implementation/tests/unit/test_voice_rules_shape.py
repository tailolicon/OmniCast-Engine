"""A list of voice markers and a line of them are the same thing.

The planner prompt asks for "voice_rules LISTING 2-3 MEASURABLE idiolect
markers" and shows three comma-separated examples. The planner returned a JSON
array — reasonably — and the field was typed `str`, so Pydantic rejected the
whole plan before anything read it. The concept was discarded and the contract
retry regenerated it as a string.

Measured cost: `planner=4 / planner_schema_retry=4` in the call counters, run
after run, for weeks. Half of every planner call on this channel went to that
disagreement. Nothing downstream cared — the only consumer joins these fields
into one block of text.

Three explanations were measured and eliminated before this one was found: the
prompt names all 16 required fields; 345 real ledger entries top out at 21
words against a 24-word limit; real plans run 2,100-2,350 tokens against a
3,200 cap. The remaining half was a preamble the JSON extractor could not skip
(see test_claude_cli_json_extraction.py); this is the other half.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from omnicast.agents.narrative_pipeline import NarrativeStoryPlan

BASE = dict(
    story_id="story_1", title="T", narrator_profile="A rural courier",
    setting="A gravel county road", setup_requirement="The gate code changed",
    threat="A man at the gate", threat_type="human",
    escape_action="He reverses to the county road",
    ending_shape="He never uses that gate again",
    continuity_ledger=[
        "hook_timeline: third night on the same route",
        "people_objects: one man, one cooler, one van",
        "locations_exits: gate, lane, county road",
        "props_threat_position: man stands inside the open gate",
        "response_escape: reverses to the county road at once",
    ],
    threat_mechanism="blocks_path",
    progression_mechanism="silent_stillness",
    escape_mechanism="flee_to_occupied_place",
    aftermath_mechanism="no_explanation_offered",
    threat_identity="lone_stranger",
)


def _plan(**over) -> NarrativeStoryPlan:
    return NarrativeStoryPlan.model_validate({**BASE, **over})


def test_a_list_of_markers_is_accepted():
    plan = _plan(voice_rules=["short clipped sentences",
                              "calls everything by its trade name"])
    assert isinstance(plan.voice_rules, str)
    assert "short clipped sentences" in plan.voice_rules
    assert "calls everything by its trade name" in plan.voice_rules


def test_a_plain_string_is_untouched():
    plan = _plan(voice_rules="rambles and self-corrects mid-sentence")
    assert plan.voice_rules == "rambles and self-corrects mid-sentence"


def test_the_markers_stay_separable_after_joining():
    """The consumer reads this as text, but a human auditing a plan should
    still be able to see where one marker ends and the next begins."""
    plan = _plan(voice_rules=["a", "b", "c"])
    assert plan.voice_rules.count(";") == 2


def test_empty_entries_are_dropped_not_preserved_as_gaps():
    plan = _plan(voice_rules=["never swears", "", "  ", "hedges every estimate"])
    assert plan.voice_rules == "never swears; hedges every estimate"


def test_a_shape_nobody_asked_for_still_fails():
    """Accepting a list must not become accepting anything. A dict is not a
    misunderstanding of the instruction, it is a different answer."""
    with pytest.raises(ValidationError):
        _plan(voice_rules={"marker": "short sentences"})


def test_the_only_consumer_treats_it_as_text():
    """Why coercion is lossless: plan_evidence joins these fields with
    newlines, so a joined list reads identically to a written line."""
    import inspect

    from omnicast.agents import narrative_pipeline as np

    src = inspect.getsource(np)
    i = src.index("item.threat, item.escape_action, item.ending_shape, item.voice_rules")
    window = src[max(0, i - 300):i]
    assert '"\\n".join' in window
