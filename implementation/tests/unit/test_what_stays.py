"""What stays â€” the mechanisms of fear, read in the corpus, not measured.

The seven stories in the two most-watched videos (3.2M views) each carry a
fact learned too late that re-reads the night ("I likely looked right at
this guy ... and didn't even know it"), a named reason the easy exit is
gone, the narrator inferring what the threat wants, and one thing never
explained, said last. The operator's verdict on our gated plans: competent,
not frightening â€” because nothing in them is learned too late and nothing
is left unexplained.
"""

from __future__ import annotations

import inspect

import omnicast.agents.narrative_pipeline as np
from omnicast.config.narrative_quality import resolve_script_profile


def _horror():
    return np.NamedChannelStrategy.from_quality_profile(resolve_script_profile("true_horror_strict_v1"))


def test_the_four_fields_exist_and_default_empty_for_legacy_plans():
    for f in ("already_line", "no_way_out", "threat_mind", "remainder"):
        assert np.NarrativeStoryPlan.model_fields[f].default == ""


def test_a_ladder_profile_refuses_a_plan_with_none_of_them():
    from tests.unit.test_narrative_unit_pipeline import _plan
    plan = _plan()
    bare = plan.model_copy(update={"stories": [
        st.model_copy(update={"already_line": "", "no_way_out": "", "threat_mind": "", "remainder": ""})
        for st in plan.stories]})
    errs = np.validate_plan_preflight(bare, 3, _horror())
    assert any("already_line is missing" in e for e in errs)
    assert any("remainder is missing" in e for e in errs)
    assert np.validate_plan_preflight(plan, 3, _horror()) == []


def test_a_generic_strategy_does_not_require_them():
    from tests.unit.test_narrative_unit_pipeline import _plan
    plan = _plan()
    bare = plan.model_copy(update={"stories": [
        st.model_copy(update={"already_line": "", "no_way_out": "", "threat_mind": "", "remainder": ""})
        for st in plan.stories]})
    assert not any("is missing" in e for e in np.validate_plan_preflight(bare, 3, None))


def test_the_planner_writer_repair_and_auditor_all_carry_them():
    src = inspect.getsource(np)
    assert "WHAT STAYS. The most-watched accounts in this genre" in src       # planner
    assert "THE ALREADY LINE, learned after, one sentence, no build-up" in src   # writer
    assert "already_line, no_way_out, threat_mind, remainder.\n" in src         # repair keys
    assert "- haunting:" in src                                                 # auditor
    assert "haunting" in str(np.PlanIssue.model_fields["category"].annotation)
    assert "VOICE IS PLAIN" in src


def test_the_fields_are_quotable_plan_text():
    from tests.unit.test_narrative_unit_pipeline import _plan
    item = _plan().stories[0]
    text = np.plan_story_text(item)
    assert item.already_line in text and item.remainder in text


def test_a_performed_tic_in_voice_rules_is_refused_on_ladder_profiles():
    class _S:
        story_id = "story_1"
        voice_rules = ("short declarative sentences; repeats the hedge 'not usually' whenever describing "
                       "his own reactions; describes people by comparison to his uncle's habits")
    class _P:
        stories = [_S()]
    errs = np.voice_tic_problems(_P())
    assert errs and "performed tic" in errs[0]
    _S.voice_rules = "plain, dated, exact clock times; reasons out loud about what each sound could be; one image at most"
    assert np.voice_tic_problems(_P()) == []


def test_the_auditor_knows_an_explanation_is_not_an_already_line():
    src = inspect.getsource(np)
    assert "NEITHER IS AN EXPLANATION" in src


def test_the_writer_gets_room_for_the_story_it_is_asked_for():
    """Two live attempts came back 46% short: every writer-path call was
    capped at 2,600 tokens (~1,900 words) for a 2,600-word target."""
    assert np._writer_max_tokens(2600) >= 5000
    assert np._writer_max_tokens(800) == 2600
    src = inspect.getsource(np)
    assert src.count("max_tokens=2600,") == 0, "a literal writer cap survived"


def test_the_writer_prompt_carries_a_dwell_budget_and_bans_copying_examples():
    from tests.unit.test_narrative_unit_pipeline import _plan
    plan = _plan()
    text = np._story_prompt(plan.stories[0], 2600, plan.cold_open, _horror())
    assert "SHAPE OF THE ACCOUNT" in text
    assert "the worst rung: about" in text
    assert "Never reuse their wording" in text



def test_genre_native_constructions_are_not_slop():
    """Two 'I told myself' per story, four exact clock times, and a rubric that
    scores a single account on its own voice."""
    src = inspect.getsource(np)
    assert "if empty_hits or len(banned_hits) > 2:" in src
    assert np.NamedChannelStrategy.model_fields["precise_clock_limit"].default == 4
    assert "IF THE COMPILATION HAS ONE STORY, there is no lineup to compare" in src
    from omnicast.config.narrative_quality import resolve_script_profile
    assert resolve_script_profile("true_horror_strict_v1").maximum_precise_clock_times >= 3


def test_empty_reassurance_is_slop_and_specific_reassurance_is_the_genre():
    assert np._BANNED_EMPTY_RE.search("I told myself it was nothing.")
    assert np._BANNED_EMPTY_RE.search("I figured it was probably nothing and went back to bed.")
    assert not np._BANNED_EMPTY_RE.search("I told myself it was just a small company delivery.")
    assert not np._BANNED_EMPTY_RE.search("I figured it was another camper who had gone to sleep.")



def test_the_report_beat_is_demanded_at_every_stage():
    """Final editor, 22:19: prints under the window and around the house,
    a working landline, days of silence. The corpus narrator calls and gets
    the half-answer; that beat lives in the plan, the page, and the judges."""
    src = inspect.getsource(np)
    assert "THE REPORT BEAT. After the first sign that cannot be explained away" in src   # planner
    assert "THE REPORT BEAT: after the first sign that cannot be explained away" in src   # writer
    assert "THE PLAN MUST CARRY THE REPORT BEAT" in src                                  # auditor
    assert src.lower().count("days of silence after a sign that cannot be explained away") >= 2  # critic + editor



def test_a_contradiction_across_a_time_skip_is_demoted():
    """22:29: 'did not move' (night five) vs 'went to the door' (night seven)
    filed as a major contradiction; 85/100 blocked against a floor of 84."""
    class _St:
        story_id = "story_1"
        narration = ("The steps stopped outside the back door and I did not move. I did not call out. "
                     "Two nights later the knock came and I went to the door with a plate in my hand.")
    issue = np.StoryIssue(story_id="story_1", severity="major", issue_kind="contradiction",
                          problem="she did not move, then went to the door",
                          evidence_quote="I went to the door", anchor_quote="I did not move",
                          repair_instruction="x", viewer_impact="x", confidence=0.8)
    score = np.NarrativeScorecard(continuity_believability=20, distinct_authentic_voices=15,
                                  dread_escalation=15, plausible_response=8, structural_variety=7,
                                  originality=6, ending_discipline=4, story_issues=[issue])
    out = np._demote_cross_night_contradictions(score, [_St()])
    assert out.story_issues[0].severity == "minor"
    same_scene = _St()
    same_scene.narration = "I did not move. I did not call out. Then I went to the door with a plate in my hand."
    assert np._demote_cross_night_contradictions(score, [same_scene]).story_issues[0].severity == "major"


def test_texture_caps_scale_with_story_length():
    """22:43: a 1,900-word single account failed for two 'the way you...'
    comparisons under a cap written for 750-word compilation stories."""
    src = inspect.getsource(np)
    assert "base * max(1, round(words / 800))" in src
    assert "keep at most {_allow(story, 1)} for its length" in src


def test_the_release_challenger_passes_the_denial_that_fails():
    """22:52: 89/100, every gate and judge passed, and the Opus challenger
    failed 'she supplies an innocent reading of the idling truck, then
    revokes it' — the genre's own beat, banned in paraphrase."""
    axes = dict(np._RELEASE_CHALLENGE_AXES) if hasattr(np, "_RELEASE_CHALLENGE_AXES") else None
    src = inspect.getsource(np)
    assert "EMPTY self-reassurance is the fail" in src
    assert "denial-that-fails with a SPECIFIC alternative is the genre" in src



def test_a_local_challenger_fail_earns_one_repair_and_one_rechallenge():
    """23:26: a corded receiver carried out the front door. One sentence;
    the design abandoned the whole build. Local axes with a quoted line now
    get one bounded repair wave and one re-challenge; premise axes still
    abandon."""
    src = inspect.getsource(np.NarrativeUnitPipeline.run)
    i = src.index('_local_axes = {"physical_possibility", "timeline_consistency", "semantic_repetition", "self_reassurance"}')
    block = src[i:i + 4000]
    assert "if _local_fail and repair_waves < 3:" in block
    assert block.count("await self._release_challenge(") == 1
    assert "topic_alignment" not in block.split("_local_fail = (")[0]


def test_the_dwell_budget_does_not_ask_for_a_denial_on_every_rung():
    """23:57: five denial-that-fails beats in one account, because the budget
    line asked every rung for 'what you told yourself it was'."""
    src = inspect.getsource(np._story_prompt)
    assert "what you told yourself it was, what you did next" not in src
    assert "allowed TWICE in the whole account" in src


def test_the_critic_and_editor_count_denial_beats_before_the_challenger_does():
    """01:53: five denial-that-fails beats reached the Opus challenger (the
    last, most expensive judge) because no earlier judge counted them."""
    src = inspect.getsource(np)
    assert src.count("COUNT THE DENIAL BEATS") >= 2


def test_unfounded_final_editor_majors_are_demoted():
    class _St:
        story_id = "story_1"
        narration = ("Day three I found the print. That afternoon I called the sheriff's non-emergency line "
                     "and a deputy said it sounded like someone checking the house. " + "x " * 400 +
                     "Then the knock came and he tried the handle.")
    mk = lambda txt: np.StoryIssue(story_id="story_1", severity="major", issue_kind="omission",
                                   problem=txt, evidence_quote="the print", repair_instruction="x",
                                   viewer_impact="x", confidence=0.8)
    out = np._demote_unfounded_editor_issues([
        mk("The on-page action matches this exactly. No contradiction found."),
        mk("The narrator fails to contact authorities after discovering the boot print."),
        mk("The narrator walks out holding a corded receiver."),
    ], [_St()])
    assert [i.severity for i in out] == ["minor", "minor", "major"]


def test_first_sign_inside_300_words_and_rungs_on_the_page():
    """Operator: three minutes before the first sign is too long; corpus
    median is ~220 words. And the draft dropped the rung that plants the
    knowledge path with no judge noticing."""
    src = inspect.getsource(np)
    assert src.count("TIMESTAMP THE FIRST SIGN") >= 2
    assert src.count("EVERY LADDER RUNG ON THE PAGE") >= 2
    assert "The FIRST WRONGNESS lands inside the first 300 words" in src
    assert "_setup = min(300, int(target_words * 0.18))" in src


def test_canonical_quote_bridges_typographic_apostrophes():
    """00:41: 'found 0 times' three judges in a row over a curly apostrophe."""
    narr = "I drove to the sheriff\u2019s substation on Route 9 \u2014 fast."
    assert np._canonical_quote(narr, "the sheriff's substation on Route 9 - fast") is not None
    assert np._canonical_quote(narr, "the sheriff's office") is None
