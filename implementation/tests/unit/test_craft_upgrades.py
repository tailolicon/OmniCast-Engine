"""Pins for the 2026-07-17 craft campaign, batch 1 (multi-agent research +
adversarial panel): critic voice-blindness fix, planner/writer rule split,
instruction-contradiction repairs, the threat_identity axis, and the passive
threat-withdrawal escape shape."""

from __future__ import annotations

import omnicast.agents.narrative_pipeline as np
from omnicast.agents.narrative_pipeline import (
    NamedChannelStrategy,
    validate_plan_preflight,
)
from omnicast.config.narrative_quality import resolve_script_profile

from tests.unit.test_narrative_unit_pipeline import (
    _brief,
    _draft,
    _plan,
    _story_plan,
)


def _horror() -> NamedChannelStrategy:
    return NamedChannelStrategy.from_quality_profile(
        resolve_script_profile("true_horror_strict_v1")
    )


# ---------------------------------------------------------------------------
# P1 — the critic scores distinct_authentic_voices /20; it must actually
# receive the profile's voice criteria (it previously received none).


def test_critic_rules_carry_the_profile_voice_rules():
    profile = resolve_script_profile("true_horror_strict_v1")
    strategy = _horror()
    for rule in profile.voice_rules:
        assert rule in strategy.critic_rules


def test_critic_prompt_defines_a_groundable_voice_defect():
    stories = [_draft(i) for i in range(1, 4)]
    prompt = np._critic_prompt(
        _plan(), stories, np.gate_compilation(_plan(), stories), _horror(),
    )
    assert "VOICE DEFECTS" in prompt
    assert "lineup test" in prompt
    # Contract-compatible grounding: one story owns the evidence_quote.
    assert "against ONE story" in prompt


# ---------------------------------------------------------------------------
# P6 — planning rules are planner-side; the story prompt must not spend
# attention on compilation-level constraints the writer cannot act on.


def test_planning_rules_stay_out_of_the_writer_prompt():
    profile = resolve_script_profile("true_horror_strict_v1")
    strategy = _horror()
    for rule in profile.planning_rules:
        assert rule not in strategy.writer_rules
        assert rule in strategy.planner_rules
    story_prompt = np._story_prompt(_story_plan(1), 750, "cold open", strategy)
    assert profile.planning_rules[0] not in story_prompt
    plan_prompt = np._plan_prompt(_brief(), 3, 2250, None, "", strategy)
    assert profile.planning_rules[0] in plan_prompt


def test_hand_built_strategies_fall_back_to_writer_rules_for_planning():
    bare = NamedChannelStrategy(
        strategy_id="bare", writer_rules="- keep it restrained",
        critic_rules="strict", annotation_rules="literal",
    )
    prompt = np._plan_prompt(_brief(), 3, 2250, None, "", bare)
    assert "keep it restrained" in prompt


# ---------------------------------------------------------------------------
# P8 — instruction contradictions: the STOP rule must exempt the locked safety
# report, and the cold open may not be restated verbatim in the story.


def test_stop_rule_exempts_the_flat_safety_report():
    prompt = np._story_prompt(_story_plan(1), 750, "cold open", _horror())
    assert "does NOT count as trailing explanation" in prompt
    assert "never the locked safety response" in prompt


def test_cold_open_must_be_paid_off_not_restated():
    prompt = np._story_prompt(_story_plan(1), 750, "cold open", _horror())
    assert "never restate the cold-open sentence" in prompt


def test_never_returned_ban_names_the_concrete_behavior_alternative():
    profile = resolve_script_profile("true_horror_strict_v1")
    joined = " ".join(profile.avoid_tropes)
    assert "concrete ongoing behavior" in joined
    prompt = np._story_prompt(_story_plan(1), 750, "cold open", _horror())
    assert "announced bare claim" in prompt


# ---------------------------------------------------------------------------
# P4 — threat_identity is a mechanism axis: distinct per compilation, present
# in vocabulary and prompts.


def test_threat_identity_is_a_no_two_share_axis():
    assert "threat_identity" in np._MECHANISM_AXES
    plan = _plan()
    duplicated = plan.model_copy(update={"stories": [
        plan.stories[0],
        plan.stories[1].model_copy(update={"threat_identity": plan.stories[0].threat_identity}),
        plan.stories[2],
    ]})
    errors = validate_plan_preflight(duplicated, 3, _horror())
    assert any("threat_identity" in e for e in errors)


def test_mechanism_vocabulary_lists_threat_identity():
    vocab = np._mechanism_vocabulary()
    assert "threat_identity" in vocab
    assert "lone_stranger" in vocab
    assert "threat_withdraws_uncontested" in vocab


def test_plan_prompt_caps_the_silent_lone_stranger():
    prompt = np._plan_prompt(_brief(), 3, 2250, None, "", _horror())
    assert "threat_identity" in prompt
    assert "At most one story" in prompt


# ---------------------------------------------------------------------------
# P5 — a threat that withdraws uncontested is a valid escape shape, with a
# declared safety response for human threats and a menace note for the writer.


def test_plan_prompt_makes_adult_narrators_the_default():
    """Two plan-stage deaths in a row (2026-07-19) came from minor narrators
    whose safety chain the planner under-planned; the audit killed both,
    correctly, at the cost of a full attempt each."""
    prompt = np._plan_prompt(_brief(), 3, 2250, None, "", _horror())
    assert "age IS the premise" in prompt
    assert "an adult narrator is the" in prompt


def test_plan_prompt_warns_recurring_threats_forbid_not_applicable():
    """Plan-audit killed two attempts in one run (2026-07-18) on this shape: a
    human threat recurring across nights with safety_obligation not_applicable.
    Deliberately NOT a typed gate (single-shift repeat sightings false-positive)
    — the planner is warned up front and the semantic audit enforces it."""
    prompt = np._plan_prompt(_brief(), 3, 2250, None, "", _horror())
    assert "RECURS across separate nights" in prompt
    assert "never a next-day mention" in prompt
    # And repeat_sightings alone must NOT trip the deterministic preflight.
    plan = _plan()
    single_shift = plan.model_copy(update={"stories": [
        plan.stories[0].model_copy(update={
            "progression_mechanism": "repeat_sightings",
            "safety_obligation": "not_applicable",
        }),
        *plan.stories[1:],
    ]})
    errors = validate_plan_preflight(single_shift, 3, _horror())
    assert not any("recurring" in e for e in errors)


def test_withdrawal_with_human_threat_requires_a_safety_response():
    plan = _plan()
    bad = plan.model_copy(update={"stories": [
        plan.stories[0].model_copy(update={
            "escape_mechanism": "threat_withdraws_uncontested",
            "safety_obligation": "not_applicable",
        }),
        *plan.stories[1:],
    ]})
    errors = validate_plan_preflight(bad, 3, _horror())
    assert any("threat_withdraws_uncontested" in e for e in errors)

    declared = plan.model_copy(update={"stories": [
        plan.stories[0].model_copy(update={
            "escape_mechanism": "threat_withdraws_uncontested",
            "safety_obligation": "authorities_contacted",
        }),
        *plan.stories[1:],
    ]})
    errors = validate_plan_preflight(declared, 3, _horror())
    assert not any("threat_withdraws_uncontested" in e for e in errors)


# ---------------------------------------------------------------------------
# P2 — voice seed: the planner demonstrates each narrator's voice; the writer
# CONTINUES it. The seed is deterministically gated so it cannot smuggle
# banned phrasing, numbers, or evidence framing past the narration gates.


def test_plan_prompt_demands_a_satisfiable_voice_seed():
    prompt = np._plan_prompt(_brief(), 3, 2250, None, "", _horror())
    assert "voice_seed" in prompt
    assert "SATISFIABLE under the writer's gates" in prompt
    assert "voice_seed is exempt" in prompt or "EXCEPT voice_seed" in prompt


def test_story_prompt_continues_a_present_voice_seed_and_fences_it_off_page():
    seeded = _story_plan(1).model_copy(update={
        "voice_seed": "I keep my keys on a carabiner. Always have. You learn that the first week.",
    })
    prompt = np._story_prompt(seeded, 750, "cold open", _horror())
    assert "CONTINUE THIS EXACT VOICE" in prompt
    assert "I keep my keys on a carabiner." in prompt
    assert "OFF-PAGE" in prompt
    bare = np._story_prompt(_story_plan(1), 750, "cold open", _horror())
    assert "CONTINUE THIS EXACT VOICE" not in bare


def test_voice_seed_none_coerces_and_defaults_empty():
    plan = _story_plan(1)
    assert plan.voice_seed == ""
    coerced = plan.model_copy(update={"voice_seed": None})
    revalidated = np.NarrativeStoryPlan.model_validate(coerced.model_dump())
    assert revalidated.voice_seed == ""


def test_poisoned_voice_seed_is_blanked_not_fatal():
    """Live 2026-07-18: a seed with one exact number hard-rejected the whole
    plan, the planner's full retry introduced a fresh violation elsewhere, and
    the run died in plan stage. A poisoned seed is a field-level defect: blank
    it (the story falls back to voice_rules) and keep the plan."""
    plan = _plan()

    def _with_seed(seed: str):
        return plan.model_copy(update={"stories": [
            plan.stories[0].model_copy(update={"voice_seed": seed}),
            *plan.stories[1:],
        ]})

    numeric = np._salvage_voice_seeds(
        _with_seed("My shift starts at 11:45. I count 37 doors every night.")
    )
    assert numeric.stories[0].voice_seed == ""

    banned = np._salvage_voice_seeds(
        _with_seed("I told myself it was nothing. Old buildings creak.")
    )
    assert banned.stories[0].voice_seed == ""

    clean_seed = "I keep my keys on a carabiner. Always have. You learn that fast."
    clean = np._salvage_voice_seeds(_with_seed(clean_seed))
    assert clean.stories[0].voice_seed == clean_seed
    # And a blanked seed never becomes a preflight error.
    errors = validate_plan_preflight(numeric, 3, _horror())
    assert not any("voice_seed" in e for e in errors)


def test_story_prompt_renders_withdrawal_as_menace_only_for_that_mechanism():
    withdrawing = _story_plan(1).model_copy(update={
        "escape_mechanism": "threat_withdraws_uncontested",
    })
    prompt = np._story_prompt(withdrawing, 750, "cold open", _horror())
    assert "withdrawing on its own" in prompt
    assert "it chose to leave" in prompt
    normal = np._story_prompt(_story_plan(1), 750, "cold open", _horror())
    assert "withdrawing on its own" not in normal


# ---------------------------------------------------------------------------
# P9 — paraphrase evasion: "I never did ask" escaped the forbidden-ending regex
# on a 100/100 build. The widened branches stay first-person anchored so legal
# non-resolution ("they never found him") remains legitimate.


def test_forbidden_ending_regex_catches_did_and_really_interpolations():
    for ending in (
        "I never did ask.",
        "I never really found out who he was.",
        "We never did go back... actually we never went back to that lot.",
        "I never ever went back.",
    ):
        assert np._FORBIDDEN_ENDING_RE.search(ending), ending


def test_forbidden_ending_regex_spares_third_party_and_mid_story_negation():
    for legitimate in (
        "They never found him.",
        "The police never learned his name.",
        "She never asked me about that night.",
        "I never liked that stretch of road.",
    ):
        assert not np._FORBIDDEN_ENDING_RE.search(legitimate), legitimate


# ---------------------------------------------------------------------------
# P11 — craft bullets live in the profile; the recognition-point variance and
# occupational lens live in the plan prompt.


def test_dread_rules_carry_sound_first_low_resolution_and_delayed_recognition():
    profile = resolve_script_profile("true_horror_strict_v1")
    joined = " ".join(profile.dread_rules)
    assert "through the ears before the eyes" in joined
    assert "low resolution" in joined
    assert "approved replacement for the banned" in joined


def test_plan_prompt_varies_recognition_point_and_routes_lens_through_voice_rules():
    prompt = np._plan_prompt(_brief(), 3, 2250, None, "", _horror())
    assert "Vary the recognition point" in prompt
    assert "only that role would notice" in prompt


def test_trusted_adult_obligation_names_who_counts():
    """Build 20260718_0213: the plan locked trusted_adult_or_witness and the
    writer delivered a gas-station clerk — a bystander the gate correctly
    rejects. The obligation must TELL the writer who qualifies, or this class
    of miss recurs on every trusted-adult plan."""
    plan = _story_plan(1).model_copy(update={
        "safety_obligation": "trusted_adult_or_witness",
    })
    prompt = np._story_prompt(plan, 750, "cold open", _horror())
    assert "STANDING" in prompt
    assert "clerk" in prompt  # the named counter-example
    assert "does not count" in prompt


def test_evidence_none_spells_out_what_nothing_means():
    """Third occurrence of one miss (1635, 2014, 0101): with allowance 'none'
    the writer still adds a corroborating account or report to the aftermath —
    reading 'none' as 'a little'. The prompt now spells out the ban and names
    the craft reason (unconfirmed loneliness IS the dread)."""
    none_plan = _story_plan(1).model_copy(update={"evidence_allowance": "none"})
    prompt = np._story_prompt(none_plan, 750, "cold open", _horror())
    assert "NOTHING confirms the encounter" in prompt
    assert "relief-shift corroboration" in prompt
    allowed = _story_plan(2).model_copy(update={"evidence_allowance": "physical"})
    prompt2 = np._story_prompt(allowed, 750, "cold open", _horror())
    assert "NOTHING confirms the encounter" not in prompt2


def test_spouse_counts_as_a_trusted_adult_but_bare_partner_does_not():
    """Live 2026-07-18 (build 2041): an adult narrator told his wife — the real-
    person response — and the gate failed the story because the matcher only
    knew minors' adults (mom/teacher) and workplace ones (boss)."""
    assert np._RESPONSIBLE_ADULT_RE.search("I told my wife everything that night.")
    assert np._RESPONSIBLE_ADULT_RE.search("My husband met me at the door and I told him.")
    assert np._RESPONSIBLE_ADULT_RE.search("I told my partner when she got home.")
    # A business partner is not a household confidant.
    assert not np._RESPONSIBLE_ADULT_RE.search("I mentioned it to a partner at the firm.")
    # And a household noun DESCRIBING the threat is not a response (live: the
    # artifact says "Nobody's husband, nobody's brother" about the stranger).
    assert not np._RESPONSIBLE_ADULT_RE.search("Nobody's husband, nobody's brother.")


def test_plan_landmarks_are_coordinates_not_suggestions():
    """Third occurrence of one drift class (1635 call-timing, 1903 station
    lights, 2014 turn-at-the-wash): the writer treats a locked place/ordering
    as approximate and three beats collapse at once. Say it plainly."""
    prompt = np._story_prompt(_story_plan(1), 750, "cold open", _horror())
    assert "COORDINATES, not" in prompt
    assert "not before" in prompt
    assert "breaks three beats" in prompt
    # Widened after build 1323: prop states ("propped" became "latched") and
    # companion arrangements ("alongside her mother" became working alone)
    # drifted exactly like landmarks.
    assert "PROP STATES" in prompt
    assert "WHO-IS-WITH-WHOM" in prompt


def test_each_beat_demands_its_own_sentence():
    """Third occurrence of the same terminal failure (0104, 0836, 1557): prose
    that merges decision and completed-escape into one sentence hands the
    compliance auditor an impossible task (two distinct non-overlapping quotes
    from one sentence) and zero-scores the run. The writer is told at the
    source: one sentence per beat."""
    prompt = np._story_prompt(_story_plan(1), 750, "cold open", _horror())
    assert "its OWN sentence" in prompt
    assert "never complete two beats inside one sentence" in prompt


def test_story_prompt_declares_texture_budgets_up_front():
    """Recovery ran 3x on the 20260718_0213 build and the one-word-beat spray
    still survived — the writer only learned the budget AFTER violating it.
    Declaring the deterministic texture budgets in the story prompt lets first
    drafts comply instead of burning recovery calls."""
    prompt = np._story_prompt(_story_plan(1), 750, "cold open", _horror())
    assert "TEXTURE BUDGETS" in prompt
    assert "TWO one-word beat sentences" in prompt
    assert "banned outright" in prompt


def test_final_review_prompt_flags_tts_nonsense_bigrams():
    stories = [_draft(i) for i in range(1, 4)]
    prompt = np._final_review_prompt(_plan(), stories, _horror())
    assert "gate pants" in prompt
