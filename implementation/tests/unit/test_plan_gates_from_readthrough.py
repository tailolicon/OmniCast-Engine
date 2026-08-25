"""Four defects an operator read-through found in the first plan to pass every
gate — and the system's job is to catch them, not the operator's.

v1 of "The Man Who Knew Her Medicine": (1) a missing pill with no moment it
could have been taken; (2) a polite daytime question at the door followed
straight by the handle wrenched that night; (3) an escape by a neighbour's
headlights; (4) a voice rule of "never exact numbers" in a story that turns
on an exact dosage. Two are regexes, two are auditor questions.
"""

from __future__ import annotations

import inspect

import omnicast.agents.narrative_pipeline as np

V1_LADDER = [
    "Returning from the hospital, the mailbox flag is up though he never touched it.",
    "Counting the discharge bag's pills, one is missing that he'd swear was there in the car.",
    "At dusk a pickup idles at the end of the driveway with its lights off, then pulls away.",
    "A man knocks claiming to mow the lawn and asks after 'the new pain pills' by exact dosage.",
    "That night the back door handle is wrenched hard against the deadbolt while he stands ten feet away.",
    "Still on the line, he hears the laundry-room window sash being forced up in the room he just left.",
]
V2_LADDER = V1_LADDER[:4] + [
    "That night gravel crunches along the side of the house, stops outside the kitchen door, and stays silent there.",
] + V1_LADDER[4:]


def _plan(rungs=None, escape=""):
    class _S:
        story_id = "story_1"
        escalation_ladder = rungs or []
        escape_action = escape

    class _P:
        stories = [_S()]

    return _P()


def test_a_jump_cut_to_the_handle_is_refused():
    errs = np.ladder_order_problems(_plan(V1_LADDER))
    assert errs and "approach" in errs[0]


def test_footsteps_that_stop_outside_the_door_clear_it():
    assert np.ladder_order_problems(_plan(V2_LADDER)) == []


def test_a_ladder_with_no_breach_is_not_judged_on_order():
    assert np.ladder_order_problems(_plan([
        "A tap on the glass.", "Another tap, closer.", "A shape standing at the window.", "It stays."])) == []


def test_a_neighbours_headlights_are_a_coincidence():
    errs = np.escape_agency_problems(_plan(escape=(
        "Locks himself in the hallway bathroom with 911 on the line, then the window sash goes "
        "still as a neighbor's headlights sweep the driveway.")))
    assert errs and "coincidence" in errs[0]


def test_throwing_the_lights_and_a_called_deputy_is_an_escape():
    assert np.escape_agency_problems(_plan(escape=(
        "From the hallway he throws every exterior light from the panel, shouts that the sheriff "
        "is on the line, and locks himself in; he stays on the line until the deputy's light hits "
        "the window."))) == []


def test_an_escape_with_no_narrator_action_is_refused():
    errs = np.escape_agency_problems(_plan(escape="The figure stands there a while and then is gone."))
    assert errs and "no action" in errs[0]


def test_escape_agency_is_a_gate_and_ladder_order_is_not():
    """ladder_order rejected five of five real ladders on 2026-08-22 (a truck
    parked across the road, boots crossing the porch: approaches the regex
    could not see). It stays a planner rule and an auditor question, not a
    deterministic reject."""
    src = inspect.getsource(np.validate_plan_preflight)
    assert "errors.extend(ladder_order_problems(plan))" not in src
    assert "escape_agency_problems(plan)" in src


def test_the_auditor_is_asked_the_two_questions_a_regex_cannot():
    src = inspect.getsource(np._plan_audit_prompt) if hasattr(np, "_plan_audit_prompt") \
        else inspect.getsource(np)
    assert "- knowledge_path:" in src
    assert "- voice_vs_premise:" in src
    assert "knowledge_path" in str(np.PlanIssue.model_fields["category"].annotation)


def test_the_planner_is_told_all_four():
    src = inspect.getsource(np._plan_prompt)
    assert "DISTANCE CLOSES IN STEPS NOBODY CAN SKIP" in src
    assert "WHAT THE THREAT KNOWS, IT GOT SOMEWHERE" in src
    assert "never a neighbour's headlights" in src.lower() or "neighbour's headlights" in src


def test_a_threat_that_stops_as_gravel_crunches_away_is_a_coincidence():
    """Codex's editorial review of the run-15 plan: the narrator locks the
    bathroom and dials 911, and then 'the prying stops as gravel crunches
    away down the driveway' — nothing she did made him leave."""
    errs = np.escape_agency_problems(_plan(escape=(
        "Backs into the hall bathroom and locks it, dials 911 with the phone already in hand, "
        "and the prying stops as gravel crunches away down the driveway.")))
    assert errs and "coincidence" in errs[0]


def test_the_auditor_treats_a_spoken_private_fact_as_load_bearing():
    src = inspect.getsource(np)
    assert "EVERY fact the threat says aloud is load-bearing" in src
    assert "the moment he finally stops" in src


def test_the_planner_is_told_the_cold_open_must_not_spend_the_last_rung():
    src = inspect.getsource(np._plan_prompt)
    assert "THE COLD OPEN SELLS THE NIGHT, NOT THE PAYOFF" in src


def test_the_called_deputys_headlights_are_an_earned_escape():
    """Run 15 repair round 2 was thrown away as a coincidence for this."""
    assert np.escape_agency_problems(_plan(escape=(
        "Already on the line with 911 since the handle turned, narrator backs into the hall bathroom, "
        "locks it, and shouts that deputies are close; headlights sweep up the drive, the prying stops, "
        "and a deputy arrives nine minutes after the call."))) == []


def test_a_threat_that_simply_leaves_is_still_a_coincidence_even_with_911_named():
    errs = np.escape_agency_problems(_plan(escape=(
        "Locks the bathroom and dials 911; the prying stops as gravel crunches away down the driveway "
        "before the dispatcher finishes.")))
    assert errs and "coincidence" in errs[0]


def test_codex_round_two_became_mechanisms():
    """7/10 with four edits the auditor had marked minor or missed: a spoiled
    cold open (a compilation field repair could not touch), an unstaged
    ending object, night arithmetic, a 911 shout that was neither true nor a
    declared bluff."""
    src = inspect.getsource(np)
    assert "- cold_open:" in src and "cold_open" in str(np.PlanIssue.model_fields["category"].annotation)
    assert np.PlanRepairOutput.model_fields["cold_open"].default is None
    assert "AN OBJECT WHOSE CHANGE IS THE ENDING" in src
    assert "COUNT THE NIGHTS" in src
    assert "A SHOUT THAT 911 IS ON THE LINE" in src
    rep = inspect.getsource(np.NarrativeUnitPipeline._repair_plan)
    assert '_update["cold_open"] = repair.cold_open.strip()' in rep


def _story(**kw):
    class _S:
        story_id = "story_1"
        escalation_ladder = kw.get("ladder", [])
        continuity_ledger = kw.get("ledger", [])
        escape_action = ""
    return _S


def test_the_ladder_cannot_spend_more_nights_than_the_stay():
    S = _story(ladder=["Mailbox left unlocked three days; cards spill out.", "A man knocks in daylight.",
                       "Two nights later gravel crunches up the drive.", "The handle turns."],
               ledger=["hook_timeline: Narrator house-sits four nights while uncle recovers."])
    class _P:
        cold_open = ""
        stories = [S()]
    errs = np.night_arithmetic_problems(_P())
    assert errs and "spends 5" in errs[0]


def test_a_cold_open_that_repeats_the_last_rung_is_a_spoiler():
    S = _story(ladder=["Mailbox left unlocked.", "A man knocks in daylight.", "Gravel stops outside the door.",
                       "A voice says the uncle's private nickname through the glass."])
    class _P:
        cold_open = "I never leave a window unlatched anymore, not since something said his nickname through the glass."
        stories = [S()]
    errs = np.cold_open_spoiler_problems(_P())
    assert errs and "through the" in errs[0]
    _P.cold_open = "I never leave a window unlatched anymore, not since that October at my uncle's farmhouse."
    assert np.cold_open_spoiler_problems(_P()) == []


def test_cold_open_gate_errors_carry_the_cold_open_category():
    issues = np._gate_errors_as_issues(["story_1: cold_open repeats the last rungs ('through the glass')."])
    assert issues[0].category == "cold_open"


def test_the_auditor_is_calibrated_on_staying_and_on_staged():
    """Three repair rounds were spent on 'a reasonable person would leave'
    (a house-sitter with a cat who had reported the stranger) and on a screen
    'not specific or memorable enough' after the setup named it and its
    patch."""
    src = inspect.getsource(np)
    assert "STAYING AFTER A SIGN THAT CANNOT BE EXPLAINED AWAY is still the genre" in src
    assert "STAGED MEANS NAMED WITH A CONDITION" in src


def test_a_cold_open_objection_may_quote_the_cold_open():
    from tests.unit.test_narrative_unit_pipeline import _plan
    plan = _plan()
    review = np.PlanPlausibilityReview(issues=[np.PlanIssue(
        story_id="story_1", category="cold_open", severity="major",
        problem="spoils the payoff", plan_fix="sell the night",
        evidence_quote=plan.cold_open[:20])], summary="x")
    assert np.validate_plan_audit_issues(review, plan) == []


def test_a_cold_open_objection_shows_the_repairer_the_cold_open():
    from tests.unit.test_narrative_unit_pipeline import _plan
    from omnicast.config.narrative_quality import resolve_script_profile
    plan = _plan()
    strat = np.NamedChannelStrategy.from_quality_profile(resolve_script_profile("true_horror_strict_v1"))
    text = np._plan_repair_prompt(plan, ["story_1"], [np.PlanIssue(
        story_id="story_1", category="cold_open", severity="major", problem="spoils",
        plan_fix="sell the night", evidence_quote=plan.cold_open[:10])], strat)
    assert "THIS REPAIR MUST ALSO RETURN A NEW COLD OPEN" in text
    assert plan.cold_open in text
    plain = np._plan_repair_prompt(plan, ["story_1"], [np.PlanIssue(
        story_id="story_1", category="physical", severity="major", problem="x",
        plan_fix="y", evidence_quote="z")], strat)
    assert "THIS REPAIR MUST ALSO RETURN A NEW COLD OPEN" not in plain


def test_a_paraphrased_payoff_in_the_cold_open_is_a_spoiler():
    """Codex, three rounds: 'said his nickname through the glass' vs the rung
    'three knuckles rap the glass, then a voice says Boot'."""
    S = _story(ladder=[
        "Mailbox left unlocked three days; a card addressed to the nickname Boot.",
        "A man knocks in daylight, says he heard Boot was hospitalized.",
        "Gravel crunches up the drive and stops outside the kitchen door.",
        "The kitchen door handle turns once hard against the deadbolt.",
        "Knocking moves to the mudroom window; three knuckles rap the glass, then a voice says, Boot, you around.",
        "The window screen pops loose at one corner with a metallic snap, the aluminum frame bending inward under a hand.",
    ])
    class _P:
        cold_open = "I never leave a window unlatched anymore, not since the night something outside my uncle's house said his nickname through the glass."
        stories = [S()]
    errs = np.cold_open_spoiler_problems(_P())
    assert errs and "glass" in errs[0]
    _P.cold_open = "I never leave a window unlatched anymore, not since that October at my uncle's farmhouse at the end of the gravel."
    assert np.cold_open_spoiler_problems(_P()) == []


def test_a_cold_open_with_no_hook_is_refused():
    class _P:
        cold_open = "That week I house-sat my uncle's farmhouse, I learned our mailbox had been sitting unlocked for days."
        stories = []
    errs = np.cold_open_hook_problems(_P())
    assert errs and "no hook" in errs[0]
    for ok in ["I never leave a window unlatched anymore, not since that October at my uncle's farmhouse.",
               "The gate that let me in every morning was locked behind me, and he was still inside with me.",
               "I was twenty-nine and between leases the week a man learned my uncle's nickname from his mailbox."]:
        _P.cold_open = ok
        assert np.cold_open_hook_problems(_P()) == [], ok


def test_a_trimmed_cold_open_never_ends_on_a_dangling_word():
    from tests.unit.test_narrative_unit_pipeline import _plan
    plan = _plan().model_copy(update={"cold_open": (
        "I was thirty-four the summer I stayed at my aunt's house while she was in the hospital, "
        "and to this day I check any lock twice before I leave a room at night.")})
    out = np._salvage_cold_open(plan)
    assert len(out.cold_open.split()) <= 28
    assert not out.cold_open.endswith((" I.", " before.", " the."))
    assert out.cold_open.endswith("twice.")


def test_a_cold_open_only_repair_may_not_rewrite_the_story():
    src = inspect.getsource(np.NarrativeUnitPipeline._repair_plan)
    assert 'all(i.category == "cold_open" for i in _round_blocking)' in src
    assert "return the stories byte-identical and a new cold_open" in src


def test_the_repairers_good_cold_opens_pass_both_gates():
    """Live: the repair wrote these and the gates threw them away."""
    S = _story(ladder=[
        "Mailbox left unlocked three days; a card addressed to the nickname Boot.",
        "A man knocks in daylight, says he heard Boot was hospitalized.",
        "Gravel crunches up the drive and stops outside the kitchen door.",
        "The kitchen door handle turns once hard against the deadbolt.",
        "Knocking moves to the mudroom window; three knuckles rap the glass, then a voice says, Boot, you around.",
        "The window screen pops loose at one corner with a metallic snap, the aluminum frame bending inward under a hand.",
    ])
    S.ending_shape = "Deputies find nothing; with the bent screen unmentioned, narrator still checks the mudroom latch every night."
    class _P:
        stories = [S()]
    for cold in [
        "I still check that mudroom latch every night now, ever since the six nights I spent alone at my uncle's farmhouse and someone knocked who knew his name.",
        "I was twenty-nine, staying alone at my uncle's farmhouse while he was in the hospital, when I started sleeping with the truck keys in my pocket.",
        "I was twenty-nine the week my uncle went into the hospital, and by the third night I stopped opening the kitchen blinds after dark.",
    ]:
        _P.cold_open = cold
        assert np.cold_open_spoiler_problems(_P()) == [], cold
        assert np.cold_open_hook_problems(_P()) == [], cold
