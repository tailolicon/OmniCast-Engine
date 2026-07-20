"""Pins for the 2026-07-17 craft campaign, batch 1 (multi-agent research +
adversarial panel): critic voice-blindness fix, planner/writer rule split,
instruction-contradiction repairs, the threat_identity axis, and the passive
threat-withdrawal escape shape."""

from __future__ import annotations

import pytest

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


def _scorecard(total_gap_from_84: int, issues=None, critical=None):
    """Scorecard whose total lands at 84 - total_gap_from_84 (floor is 84).

    Base dims sum to 80; ending_discipline supplies the remainder (gap <= 4)."""
    assert 0 <= total_gap_from_84 <= 4
    dims = dict(
        continuity_believability=25, distinct_authentic_voices=20,
        dread_escalation=20, plausible_response=10, structural_variety=5,
        originality=0, ending_discipline=4 - total_gap_from_84,
    )
    return np.NarrativeScorecard(
        **dims,
        critical_issues=list(critical or []),
        story_issues=list(issues or []),
    )


def _minor(story_id: str, quote: str = "an exact quote") -> "np.StoryIssue":
    return np.StoryIssue(
        story_id=story_id, severity="minor",
        problem="object state flips mid-scene",
        repair_instruction="make the two lines agree",
        issue_kind="contradiction", evidence_quote=quote,
    )


def test_near_miss_minor_wave_targets_quoted_minors():
    """Live 2026-07-19 mall attempt 2: 83 vs floor 84, gates clean, three
    quoted repairable minors — and repair_writer=0 because repair only ever
    chased gate failures and majors. The one bounded minor wave exists for
    exactly this compilation."""
    gate = np.GateReport()
    strategy = _horror()  # approval_score = editorial_floor = 84
    expected = {"story_1", "story_2", "story_3"}
    score = _scorecard(1, issues=[_minor("story_2"), _minor("story_3")])
    assert score.total_score == 83
    ids = np._near_miss_minor_ids(score, gate, strategy, expected, repair_waves=0)
    assert ids == {"story_2", "story_3"}


def test_near_miss_minor_wave_guards():
    gate = np.GateReport()
    strategy = _horror()
    expected = {"story_1", "story_2", "story_3"}
    near = _scorecard(1, issues=[_minor("story_2")])

    # Only the first wave qualifies — this is a bounded rescue, not a loop.
    assert not np._near_miss_minor_ids(near, gate, strategy, expected, repair_waves=1)
    # A big gap is a weak draft, not a near-miss.
    far = _scorecard(4, issues=[_minor("story_2")])
    assert far.total_score == 80
    assert not np._near_miss_minor_ids(far, gate, strategy, expected, repair_waves=0)
    # At or above the floor there is nothing to rescue.
    at_floor = _scorecard(0, issues=[_minor("story_2")])
    assert at_floor.total_score == 84
    assert not np._near_miss_minor_ids(at_floor, gate, strategy, expected, repair_waves=0)
    # Any major means the normal repair path owns the wave.
    major = _minor("story_1").model_copy(update={"severity": "major"})
    assert not np._near_miss_minor_ids(
        _scorecard(1, issues=[major, _minor("story_2")]),
        gate, strategy, expected, repair_waves=0,
    )
    # A failing gate means this is not an objectively clean compilation.
    failed_gate = np.GateReport(failures=[np._failure("x", "msg", "story_1")])
    assert not np._near_miss_minor_ids(near, failed_gate, strategy, expected, repair_waves=0)
    # An unquoted minor gives the patcher nothing to grab.
    vague = _minor("story_2", quote="")
    assert not np._near_miss_minor_ids(
        _scorecard(1, issues=[vague]), gate, strategy, expected, repair_waves=0
    )


@pytest.mark.asyncio
async def test_unauditable_beats_get_one_rewrite_instead_of_zero_score():
    """Live 2026-07-19 (self-storage 2119, 4th occurrence of the class):
    story_2 merged plan beats, compliance failed 'strictly ordered and
    non-overlapping' twice, and a fully-written compilation died 0/100 with
    zero repair calls. That class now earns one bounded rewrite + re-audit;
    every other contract-failure class still fails closed unchanged."""
    pipe = np.NarrativeUnitPipeline(object(), object(), object(), None)
    plan = _plan()
    stories = [_draft(i) for i in range(1, 4)]
    marker = "story compliance beat evidence must be strictly ordered and non-overlapping"
    pipe._last_compliance_errors = {"story_2": [marker]}

    rewritten = stories[1].model_copy(update={
        "narration": stories[1].narration + " He stepped back first. Then I locked the door."
    })

    async def fake_rewrite(plan_, item, stories_, gate_, original, issues,
                           gate_messages, per_story, strategy, reason):
        assert item.story_id == "story_2"
        assert marker in gate_messages[0]
        assert "OWN sentence" in gate_messages[0]
        return rewritten

    audited: dict = {}

    async def fake_audit(plan_, candidate, strategy, *, only_ids=None, prior=None):
        audited["only_ids"] = only_ids
        return {s.story_id: object() for s in candidate}, True

    pipe._rewrite_fallback = fake_rewrite
    pipe._audit_stories = fake_audit

    out, _gate2, _reviews, ok = await pipe._rescue_unauditable_stories(
        plan, stories, np.GateReport(), {}, 750, _horror(),
    )
    assert ok is True
    assert out[1] is rewritten
    assert audited["only_ids"] == {"story_2"}

    # Any other contract-failure class still fails closed unchanged.
    pipe._last_compliance_errors = {"story_2": ["schema or provider error: boom"]}
    _o, _g, _r, ok2 = await pipe._rescue_unauditable_stories(
        plan, stories, np.GateReport(), {}, 750, _horror(),
    )
    assert ok2 is False

    # A rewrite that dead-ends leaves the fail-closed verdict in place.
    pipe._last_compliance_errors = {"story_2": [marker]}

    async def dead_rewrite(*_a, **_k):
        return None

    pipe._rewrite_fallback = dead_rewrite
    _o, _g, _r, ok3 = await pipe._rescue_unauditable_stories(
        plan, stories, np.GateReport(), {}, 750, _horror(),
    )
    assert ok3 is False


def _major(story_id: str, kind: str) -> "np.StoryIssue":
    return np.StoryIssue(
        story_id=story_id, severity="major", issue_kind=kind,
        problem="synthetic", repair_instruction="fix it", evidence_quote="q",
    )


@pytest.mark.asyncio
async def test_salvage_stacks_both_good_patches_when_wave_is_rejected():
    """Live 2026-07-20 (courier 0719, 82 vs floor 84): a rejected wave held
    TWO clean patches; the single-slot salvage saved one and the discarded
    one's banned phrase stood. Salvage now stacks rounds, heaviest blocker
    first, each accepted round becoming the base for the next."""
    pipe = np.NarrativeUnitPipeline(object(), object(), object(), None)
    plan = _plan()
    stories = [_draft(i) for i in range(1, 4)]
    patched = [
        s.model_copy(update={"narration": s.narration + f" Patched {s.story_id}."})
        for s in stories
    ]
    # story_1 carries a contradiction (weight 40), story_2 a style major (20).
    base = _scorecard(1, issues=[
        _major("story_1", "contradiction"), _major("story_2", "style"),
    ])
    round_scores = iter([
        _scorecard(1, issues=[_major("story_2", "style")]),  # story_1 fixed
        _scorecard(1, issues=[]),                            # story_2 fixed too
    ])
    audit_calls: list[set] = []

    async def fake_audit(plan_, cand, strat, *, only_ids=None, prior=None):
        audit_calls.append(set(only_ids))
        reviews = dict(prior or {})
        for sid in only_ids:
            reviews[sid] = object()
        return reviews, True

    async def fake_score(plan_, cand, gate_, strat, compliance_reviews=None):
        return next(round_scores), True, None

    pipe._audit_stories = fake_audit
    pipe._score_validated = fake_score
    pipe._with_compliance_issues = lambda s, r: s

    base_gate = np.gate_compilation(plan, stories, _horror())
    result = await pipe._salvage_single_patch(
        plan, stories, patched, {"story_1", "story_2"}, base, base_gate,
        _horror(), {},
    )
    assert result is not None
    final_stories = result[0]
    assert "Patched story_1." in final_stories[0].narration
    assert "Patched story_2." in final_stories[1].narration
    # Heaviest blocker re-judged first, then the second stacked on top.
    assert audit_calls == [{"story_1"}, {"story_2"}]


@pytest.mark.asyncio
async def test_salvage_round_rejection_is_skipped_not_fatal():
    """A rejected round must not kill the rescue: the next round tries alone
    on the previous accepted base (here round 1 regresses, round 2 wins)."""
    pipe = np.NarrativeUnitPipeline(object(), object(), object(), None)
    plan = _plan()
    stories = [_draft(i) for i in range(1, 4)]
    patched = [
        s.model_copy(update={"narration": s.narration + f" Patched {s.story_id}."})
        for s in stories
    ]
    base = _scorecard(1, issues=[
        _major("story_1", "contradiction"), _major("story_2", "style"),
    ])
    round_scores = iter([
        _scorecard(1, issues=[  # round 1: WORSE (new major) -> rejected
            _major("story_1", "contradiction"), _major("story_2", "style"),
            _major("story_3", "contradiction"),
        ]),
        _scorecard(1, issues=[_major("story_1", "contradiction")]),  # round 2 wins
    ])

    async def fake_audit(plan_, cand, strat, *, only_ids=None, prior=None):
        reviews = dict(prior or {})
        for sid in only_ids:
            reviews[sid] = object()
        return reviews, True

    async def fake_score(plan_, cand, gate_, strat, compliance_reviews=None):
        return next(round_scores), True, None

    pipe._audit_stories = fake_audit
    pipe._score_validated = fake_score
    pipe._with_compliance_issues = lambda s, r: s

    base_gate = np.gate_compilation(plan, stories, _horror())
    result = await pipe._salvage_single_patch(
        plan, stories, patched, {"story_1", "story_2"}, base, base_gate,
        _horror(), {},
    )
    assert result is not None
    final_stories = result[0]
    assert "Patched story_1." not in final_stories[0].narration  # rejected round
    assert "Patched story_2." in final_stories[1].narration      # accepted round


def test_plan_prompt_rations_the_no_record_aftermath():
    """Live 2026-07-20 (shuttle 0153): three empty record-searches under three
    different aftermath labels. The plan prompt now caps the device at one
    story and names what varied aftermaths can yield instead."""
    prompt = np._plan_prompt(_brief(), 3, 2250, None, "", _horror())
    assert "NO-RECORD aftermath" in prompt
    assert "AT MOST ONE story" in prompt
    assert "one device worn three ways" in prompt


def test_escape_and_ending_must_not_share_an_event():
    """Live 2026-07-20 (self-storage 0232, 6th unauditable-beats case): the
    plan put the SAME moment in escape_action ('flags down the deputy as the
    man slips through a fence gap') and ending_shape ('deputies arrive as the
    man slips through a gap') — one span cannot serve two beats, so the story
    was unauditable no matter how it was written and the rescue rewrite could
    not save it. The aliasing is a plan defect; the rule lives in the plan
    prompt."""
    prompt = np._plan_prompt(_brief(), 3, 2250, None, "", _horror())
    assert "must not SHARE an event" in prompt
    assert "escape chain ends" in prompt
    assert "its own subsequent" in prompt


def test_ritual_coda_slot_is_assigned_to_the_first_story_only():
    """Three consecutive live runs (self-storage 1947, mall 0108) died with the
    shared-ritual-coda gate firing: writers cannot avoid duplicating the coda
    because each only sees its own story. The slot is now assigned at write
    time — only story_1's prompt permits the ritual coda."""
    first = _story_plan(1)
    later = _story_plan(2)
    p1 = np._story_prompt(first, 750, "cold open", _horror())
    p2 = np._story_prompt(later, 750, "cold open", _horror())
    assert "RESERVED for the first story" not in p1
    assert "RESERVED for the first story" in p2
    assert "do NOT close on a ritual or habit change" in p2
    # Live 2026-07-20 (shuttle 0754): story_2 followed the advice with an
    # unanswered detail phrased "I still don't know..." — which the coda-family
    # gate rightly counts as the same closing rhythm. The slot rule must ban
    # the OPENER, not just the ritual.
    assert 'do not OPEN your final sentence' in p2
    assert "I still" in p2


def test_escape_clauses_must_be_timestampable_events():
    """Live 2026-07-20 (airport shuttle 0018, 5th unauditable-beats case): the
    plan's escape chain sandwiched a continuous state ('keeps to the main
    route') between events, the prose delivered the beats in a different order
    — states have no order against events — and compliance could not quote the
    clauses as ordered spans. The trap is set at plan time, so the rule lives
    in the plan prompt."""
    prompt = np._plan_prompt(_brief(), 3, 2250, None, "", _horror())
    assert "PERFORMANCE SEQUENCE" in prompt
    assert "timestampable EVENT" in prompt
    assert "Standing states belong in the continuity_ledger" in prompt


def test_still_watcher_slot_must_earn_a_fresh_angle():
    """Live 2026-07-19 (mall try-5 + self-storage try-1): FIVE consecutive
    plan-audit kills were the same stock still-watcher rendering — glimpsed in
    glass, gone when approached, tapping that stops. The prompt allowed one
    still-watcher slot but never said the slot must earn itself; each stock
    attempt burned a planner call for the audit to reject."""
    prompt = np._plan_prompt(_brief(), 3, 2250, None, "", _horror())
    assert "That one slot must EARN itself" in prompt
    assert "Relocating the trope is not a fresh angle" in prompt
    assert "plan a threat that ACTS" in prompt


def test_escape_dependent_props_must_be_planted_in_the_plan():
    """Live 2026-07-19 self-storage (2 attempts, 0 prose): three prop_staging
    blockers of one shape — escape hinged on a fire door propped 'generally',
    a manual release lever never introduced, a fence service gap no ledger
    entry established. The planner was told not to over-stuff the ledger but
    never told the inverse: plant every prop the escape depends on."""
    prompt = np._plan_prompt(_brief(), 3, 2250, None, "", _horror())
    assert "DEPENDS on" in prompt
    assert "manual release lever" in prompt
    assert "staging contradiction" in prompt


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


def test_shift_lead_counts_as_someone_with_standing():
    """Live 2026-07-19 (mall attempt 1, 83): the narrator called the shift lead
    and told her everything — the standing figure on an overnight crew — and the
    gate failed the story because the matcher knew 'supervisor' but not 'shift
    lead'. The re-audit judged the callback fully satisfying; the false positive
    still poisoned the attempt."""
    assert np._RESPONSIBLE_ADULT_RE.search("I called my shift lead first thing.")
    assert np._RESPONSIBLE_ADULT_RE.search("Our crew chief walked the wing with me.")
    assert np._RESPONSIBLE_ADULT_RE.search("I texted the site leader before I clocked out.")
    # Bare 'lead' carries no standing ('the lead story', 'lead me out').
    assert not np._RESPONSIBLE_ADULT_RE.search("The lead story on the news that night.")


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
