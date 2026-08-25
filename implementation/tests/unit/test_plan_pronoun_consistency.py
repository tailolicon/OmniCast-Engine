"""A narrator has one gender, and that is a machine's job to check.

Live 2026-08-04: a plan described its narrator as "He drives … I've hauled"
and then wrote "She backs" into escape_action. plan_audit caught it correctly,
but that spent a paid audit call and one of only two attempts on a
contradiction nobody needed judgement to see. Preflight runs before any paid
call; this belongs there.

The check is deliberately narrow. escape_action legitimately mentions the
threat, who in this genre is usually a man, so a naive scan would block good
plans — and a false positive here is worse than the bug, because it stops
generation entirely.
"""

from __future__ import annotations

from omnicast.agents.narrative_pipeline import narrator_pronoun_conflicts


class _Story:
    def __init__(self, sid, narrator_profile="", voice_seed="",
                 escape_action=""):
        self.story_id = sid
        self.narrator_profile = narrator_profile
        self.voice_seed = voice_seed
        self.escape_action = escape_action
        self.target_words = 0


class _Plan:
    def __init__(self, stories, total=4500):
        self.stories = stories
        self.target_word_count = total


def _pronoun_errors(**kw) -> list[str]:
    return narrator_pronoun_conflicts(_Plan([_Story("story_1", **kw)]))


def test_the_observed_contradiction_is_caught():
    errors = _pronoun_errors(
        narrator_profile="He drives an overnight rural route.",
        voice_seed="I've hauled this road for years.",
        escape_action="She backs down the gravel lane.")
    assert errors and "story_1" in errors[0]


def test_a_consistent_narrator_passes():
    assert _pronoun_errors(
        narrator_profile="He drives an overnight rural route.",
        voice_seed="I've hauled this road for years.",
        escape_action="He backs down the gravel lane.") == []


def test_a_female_narrator_is_equally_fine():
    assert _pronoun_errors(
        narrator_profile="She drives an overnight rural route.",
        escape_action="She reverses onto the county road.") == []


def test_a_threat_of_the_other_gender_is_not_a_contradiction():
    """The escape usually happens WITH the threat in frame. If the field names
    both, the check has nothing unambiguous to compare and must stay quiet —
    that is what plan_audit is for."""
    assert _pronoun_errors(
        narrator_profile="She drives an overnight rural route.",
        escape_action="She reverses while he walks toward the cab.") == []


def test_a_genderless_plan_is_not_invented_into_a_conflict():
    assert _pronoun_errors(
        narrator_profile="Drives an overnight rural route.",
        escape_action="Reverses onto the county road.") == []


def test_it_runs_before_any_paid_call():
    """The whole point: catching this at plan_audit costs an audit call and one
    of two attempts."""
    import inspect

    from omnicast.agents import narrative_pipeline as np

    src = inspect.getsource(np.validate_plan_preflight)
    assert "narrator_pronoun_conflicts(plan)" in src, (
        "the check must run inside preflight, which is the stage that happens "
        "before any paid story drafting call")
    assert "before any paid" in (
        inspect.getdoc(np.validate_plan_preflight) or "").lower()


def test_the_word_boundaries_survive():
    """A shell heredoc once wrote these two escapes as literal 0x08 bytes. The
    regex still compiled, "he" matched inside "the", every field read as both
    genders, and the check silently never fired — the worst kind of broken."""
    import inspect

    from omnicast.agents import narrative_pipeline as np

    src = inspect.getsource(np.narrator_pronoun_conflicts)
    assert "\x08" not in src, "control characters in a regex literal"
    assert r"\b(he|him|his)\b" in src
    assert r"\b(she|her|hers)\b" in src
    # and the behaviour those boundaries protect
    assert np.narrator_pronoun_conflicts(
        type("P", (), {"stories": [type("S", (), {
            "story_id": "story_1",
            "narrator_profile": "The driver takes the route.",
            "voice_seed": "",
            "escape_action": "The truck pulls away.",
        })()]})()) == [], "'the' must not read as a gendered pronoun"


# ── salvage ─────────────────────────────────────────────────────────────────
# Detecting the slip only saves the paid audit call; the concept is still
# thrown away. The narrator's gender is settled by narrator_profile and
# voice_seed, and escape_action is that same person acting, so rewriting the
# pronoun is exactly the fix plan_audit itself proposed — "change 'She' to
# 'He'". Nothing creative is at stake, and this module already salvages
# cold_open and voice_seed the same way.

def _real_story(**over):
    from omnicast.agents.narrative_pipeline import NarrativeStoryPlan
    base = dict(
        story_id="story_1", title="T",
        narrator_profile="He drives an overnight rural route",
        setting="road", setup_requirement="gate code changed", threat="a man",
        threat_type="human",
        escape_action="She backs down the gravel lane.",
        ending_shape="never again", voice_rules="clipped",
        voice_seed="I've hauled this road for years.",
        continuity_ledger=[
            "hook_timeline: third night on route",
            "people_objects: one man one van",
            "locations_exits: gate lane road",
            "props_threat_position: man inside gate",
            "response_escape: reverses at once",
        ],
        threat_mechanism="blocks_path",
        progression_mechanism="silent_stillness",
        escape_mechanism="flee_to_occupied_place",
        aftermath_mechanism="no_explanation_offered",
        threat_identity="lone_stranger")
    base.update(over)
    return NarrativeStoryPlan(**base)


def _salvaged(**over) -> str:
    from omnicast.agents.narrative_pipeline import (
        CompilationPlan, _salvage_narrator_pronouns)
    plan = CompilationPlan(topic="t", cold_open="c", target_word_count=4500,
                           stories=[_real_story(**over)])
    return _salvage_narrator_pronouns(plan).stories[0].escape_action


def test_the_pronoun_is_realigned_not_merely_reported():
    assert _salvaged() == "He backs down the gravel lane."


def test_capitalisation_survives_the_swap():
    """A sentence that opens on the pronoun must not come back lower-case."""
    assert _salvaged(
        escape_action="She backs out and drives.") == "He backs out and drives."


def test_the_ambiguous_pronouns_are_not_guessed_at():
    """English does not map these one-to-one: "her" is an object ("follows
    her") and a possessive ("her hands"), and "his" has the mirror problem. A
    first version turned "Her hands shake" into "Him hands shake". A reported
    slip costs one audit call; a corrupted one ships."""
    text = "She backs out. Her hands shake."
    assert _salvaged(escape_action=text) == text

    male_amb = "He backs out. His hands shake."
    assert _salvaged(narrator_profile="She drives an overnight rural route",
                     voice_seed="I have hauled this road for years.",
                     escape_action=male_amb) == male_amb


def test_an_ambiguous_sentence_is_left_alone():
    """Once the threat is in the same sentence, a blind swap would change the
    wrong person. That case belongs to the auditor, not to a regex."""
    text = "She reverses while he walks toward the cab."
    assert _salvaged(escape_action=text) == text


def test_an_already_consistent_plan_is_untouched():
    text = "He backs down the gravel lane."
    assert _salvaged(escape_action=text) == text


def test_salvage_runs_before_preflight_rejects_the_plan():
    import inspect

    from omnicast.agents import narrative_pipeline as np

    src = inspect.getsource(np)
    i_salvage = src.index("_salvage_narrator_pronouns(candidate_plan)")
    i_preflight = src.index("preflight = validate_plan_preflight(candidate_plan")
    assert i_salvage < i_preflight, (
        "salvaging after the gate that rejects for it would fix nothing")


def test_an_object_pronoun_for_the_dispatcher_is_not_a_narrator_conflict():
    """Run 15, repaired plan: 'prying stops when the man hears her say deputies
    are close' — 'her' is the dispatcher. Only subject pronouns in the escape
    are the narrator's."""
    class _S:
        story_id = "story_1"
        narrator_profile = "29-year-old man between apartment leases, staying at his uncle's farmhouse"
        voice_seed = "I've never been much of a night owl."
        escape_action = ("Locks himself in the hall bathroom already on the phone with 911; prying stops "
                         "when the man hears her say deputies are close, footsteps retreat down the gravel.")

    class _P:
        stories = [_S()]

    import omnicast.agents.narrative_pipeline as np
    assert np.narrator_pronoun_conflicts(_P()) == []
