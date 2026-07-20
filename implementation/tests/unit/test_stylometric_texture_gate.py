"""Cross-story surface-texture gate (craft campaign P3 + P10).

The typed-mechanism axes guarantee three DIFFERENT premises; this gate guards the
sentence-level HABITS that make three different premises read in one author's
voice — the tics the 2026-07-17 corpus autopsy found verbatim across all nine
stories (menace-by-negation, one-word beats, "the way you...", "out of habit",
"I still" codas, soma clichés). Every check is a local rephrase, so a failure is
always repairable by a targeted patch; whole-text rhythm stays advisory."""

from __future__ import annotations

import omnicast.agents.narrative_pipeline as np
from omnicast.agents.narrative_pipeline import (
    NamedChannelStrategy,
    gate_compilation,
)
from omnicast.config.narrative_quality import resolve_script_profile

from tests.unit.test_narrative_unit_pipeline import _plan, _draft


def _horror() -> NamedChannelStrategy:
    return NamedChannelStrategy.from_quality_profile(
        resolve_script_profile("true_horror_strict_v1")
    )


def _compilation(narrations: dict[str, str]):
    plan = _plan()
    stories = [
        _draft(i).model_copy(update={"narration": narrations[f"story_{i}"]})
        for i in range(1, 4)
    ]
    return plan, stories


def _clean(seed: str, words: int = 720) -> str:
    """Neutral narration with none of the flagged habits.

    The seed is woven through every filler unit (not just its head) so that no
    five-word run repeats across two seeds — otherwise the filler itself is a
    verbatim cross-story phrase and trips the shared-phrase check. Unit length
    stays at six words so story/total word-count gates are unaffected."""
    body = " ".join(f"{seed}{n:02d} ordinary {seed} detail here there" for n in range(words // 6))
    return f"I worked the {seed} route that week. {body}. We got through it."


def _codes(report) -> set[str]:
    return {f.code for f in report.failures}


def _flag_codes(report) -> set[str]:
    return {f.code for f in report.editorial_flags}


# ---------------------------------------------------------------------------
# Opt-in: the gate is silent unless the profile turns it on.


def test_gate_is_off_by_default_strategy():
    plan, stories = _compilation({
        "story_1": _clean("alpha") + " Out of habit, I checked. Out of habit, I looked.",
        "story_2": _clean("bravo"),
        "story_3": _clean("charlie"),
    })
    bare = NamedChannelStrategy(
        strategy_id="bare", writer_rules="- x", critic_rules="y", annotation_rules="z",
    )
    report = gate_compilation(plan, stories, bare)
    assert not any("texture" in c or "tic" in c for c in _codes(report))


def test_true_horror_profile_enables_the_gate():
    assert _horror().stylometric_texture_gate is True


# ---------------------------------------------------------------------------
# Rationed house tics: allowed once across the compilation, not twice.


def test_rationed_tic_is_allowed_once_but_not_twice():
    once = _compilation({
        "story_1": _clean("alpha") + " I locked up out of habit.",
        "story_2": _clean("bravo"),
        "story_3": _clean("charlie"),
    })
    assert "stylometric_rationed_tic" not in _codes(gate_compilation(*once, _horror()))

    twice = _compilation({
        "story_1": _clean("alpha") + " I locked up out of habit.",
        "story_2": _clean("bravo") + " She waved out of habit.",
        "story_3": _clean("charlie"),
    })
    report = gate_compilation(*twice, _horror())
    assert "stylometric_rationed_tic" in _codes(report)
    # Minimal attribution: the SECOND occurrence's story is named, not the first.
    tic = next(f for f in report.failures if f.code == "stylometric_rationed_tic")
    assert tic.story_ids == ["story_2"]
    assert "out of habit" in tic.message


# ---------------------------------------------------------------------------
# Fully-banned clichés: zero allowed, even once.


def test_body_acted_before_mind_tic_catches_paraphrases_across_stories():
    """Found by reading the 2026-07-18 diner release: the 'my hands moved before
    my brain caught up' panic beat recurred across two stories in different
    words. The rationed family must catch the paraphrase, not just one wording."""
    plan, stories = _compilation({
        "story_1": _clean("alpha") + " My hands kind of took over before my brain caught up.",
        "story_2": _clean("bravo") + " My hands moved before I did, and I was out the door.",
        "story_3": _clean("charlie"),
    })
    report = gate_compilation(plan, stories, _horror())
    tic = [f for f in report.failures if f.code == "stylometric_rationed_tic"]
    assert tic, "the body-before-mind paraphrase must be rationed across stories"
    assert tic[0].story_ids == ["story_2"]  # second occurrence is the one to change


def test_i_like_the_preference_declaration_is_rationed_across_stories():
    """Live 2026-07-19 (mall attempt 2, 81): story_1 opened on 'I like the
    quiet part of the job' and story_2 established its narrator with the same
    'I like the ___' declaration — only the Opus challenger caught the shared
    habit. One narrator may own the move; the second is the tic."""
    once = _compilation({
        "story_1": _clean("alpha") + " I like the quiet part of the job, usually.",
        "story_2": _clean("bravo"),
        "story_3": _clean("charlie"),
    })
    assert "stylometric_rationed_tic" not in _codes(gate_compilation(*once, _horror()))

    twice = _compilation({
        "story_1": _clean("alpha") + " I like the quiet part of the job, usually.",
        "story_2": _clean("bravo") + " I liked the early loop best, before the town woke up.",
        "story_3": _clean("charlie"),
    })
    report = gate_compilation(*twice, _horror())
    tic = [f for f in report.failures if f.code == "stylometric_rationed_tic"
           and "preference" in f.message]
    assert tic, "the shared 'I like the ...' declaration must be rationed"
    assert tic[0].story_ids == ["story_2"]

    # Negated preference is not the declaration ("I didn't like the look of it").
    negated = _compilation({
        "story_1": _clean("alpha") + " I like the quiet part of the job, usually.",
        "story_2": _clean("bravo") + " I didn't like the look of the dock door.",
        "story_3": _clean("charlie"),
    })
    report2 = gate_compilation(*negated, _horror())
    assert not [f for f in report2.failures
                if f.code == "stylometric_rationed_tic" and "preference" in f.message]


def test_no_record_aftermath_device_is_rationed_across_stories():
    """Live 2026-07-20 (shuttle 0153): all three stories closed on an empty
    records check under three DIFFERENT aftermath labels — the typed axis
    cannot see a shared surface device. One story may own it."""
    once = _compilation({
        "story_1": _clean("alpha") + " Dispatch said there was nothing on file for that stop.",
        "story_2": _clean("bravo"),
        "story_3": _clean("charlie"),
    })
    hits = [f for f in gate_compilation(*once, _horror()).failures
            if f.code == "stylometric_rationed_tic" and "no-record" in f.message]
    assert not hits

    twice = _compilation({
        "story_1": _clean("alpha") + " Dispatch said there was nothing on file for that stop.",
        "story_2": _clean("bravo") + " The pickup sheet never matched a name to him.",
        "story_3": _clean("charlie"),
    })
    report = gate_compilation(*twice, _horror())
    tic = [f for f in report.failures
           if f.code == "stylometric_rationed_tic" and "no-record" in f.message]
    assert tic, "the shared no-record device must be rationed"
    assert tic[0].story_ids == ["story_2"]


def test_heard_before_saw_scaffold_is_rationed_across_stories():
    """Live 2026-07-20 ×2 (shuttle 1850, courier hospital re-judge): the
    required ears-before-eyes beat converges all three writers on the literal
    'heard X before I saw Y' construction. The beat stays required; the
    wording is rationed to one narrator."""
    once = _compilation({
        "story_1": _clean("alpha") + " I heard the cart before I saw him at all.",
        "story_2": _clean("bravo"),
        "story_3": _clean("charlie"),
    })
    hits = [f for f in gate_compilation(*once, _horror()).failures
            if f.code == "stylometric_rationed_tic" and "scaffold" in f.message]
    assert not hits

    twice = _compilation({
        "story_1": _clean("alpha") + " I heard the cart before I saw him at all.",
        "story_2": _clean("bravo") + " I heard the gate chain before I ever saw the truck.",
        "story_3": _clean("charlie"),
    })
    report = gate_compilation(*twice, _horror())
    tic = [f for f in report.failures
           if f.code == "stylometric_rationed_tic" and "scaffold" in f.message]
    assert tic, "the shared heard-before-saw scaffold must be rationed"
    assert tic[0].story_ids == ["story_2"]


def test_composure_claim_is_rationed_across_stories():
    """Live 2026-07-19 mall attempt 2 (critic minor): two narrators asserted
    composure with the same stock 'I don't spook/scare' device at their most
    exposed beat. Classic wordings are rationed deterministically; paraphrases
    stay the critic's job."""
    once = _compilation({
        "story_1": _clean("alpha") + " I don't spook on the job, never have.",
        "story_2": _clean("bravo"),
        "story_3": _clean("charlie"),
    })
    codes = [f for f in gate_compilation(*once, _horror()).failures
             if f.code == "stylometric_rationed_tic" and "composure" in f.message]
    assert not codes

    twice = _compilation({
        "story_1": _clean("alpha") + " I don't spook on the job, never have.",
        "story_2": _clean("bravo") + " I never scare easy, but that night was different.",
        "story_3": _clean("charlie"),
    })
    report = gate_compilation(*twice, _horror())
    tic = [f for f in report.failures
           if f.code == "stylometric_rationed_tic" and "composure" in f.message]
    assert tic, "the shared composure claim must be rationed"
    assert tic[0].story_ids == ["story_2"]


def test_soma_cliche_fails_on_first_use():
    plan, stories = _compilation({
        "story_1": _clean("alpha") + " My heart pounded in my chest.",
        "story_2": _clean("bravo"),
        "story_3": _clean("charlie"),
    })
    report = gate_compilation(plan, stories, _horror())
    assert "stylometric_cliche" in _codes(report)
    f = next(f for f in report.failures if f.code == "stylometric_cliche")
    assert f.story_ids == ["story_1"]


def test_dramatic_irony_tell_is_banned():
    plan, stories = _compilation({
        "story_1": _clean("alpha") + " Little did I know what waited.",
        "story_2": _clean("bravo"),
        "story_3": _clean("charlie"),
    })
    assert "stylometric_cliche" in _codes(gate_compilation(plan, stories, _horror()))


# ---------------------------------------------------------------------------
# Per-story habits: "the way you...", one-word beats, negation fragments.


def test_the_way_you_comparison_capped_per_story():
    plan, stories = _compilation({
        "story_1": _clean("alpha")
        + " It moved the way you move when watched. It stared the way you stare down prey.",
        "story_2": _clean("bravo"),
        "story_3": _clean("charlie"),
    })
    report = gate_compilation(plan, stories, _horror())
    assert "stylometric_the_way" in _codes(report)


def test_single_the_way_you_is_allowed():
    plan, stories = _compilation({
        "story_1": _clean("alpha") + " It moved the way you move when someone is watching.",
        "story_2": _clean("bravo"),
        "story_3": _clean("charlie"),
    })
    assert "stylometric_the_way" not in _codes(gate_compilation(plan, stories, _horror()))


def test_one_word_beat_spray_fails_but_a_couple_passes():
    spray = _compilation({
        "story_1": _clean("alpha") + " Quiet. Empty. Still. Nothing. Wrong.",
        "story_2": _clean("bravo"),
        "story_3": _clean("charlie"),
    })
    assert "stylometric_oneword_beat" in _codes(gate_compilation(*spray, _horror()))

    couple = _compilation({
        "story_1": _clean("alpha") + " Quiet. The lot sat there under the lights.",
        "story_2": _clean("bravo"),
        "story_3": _clean("charlie"),
    })
    assert "stylometric_oneword_beat" not in _codes(gate_compilation(*couple, _horror()))


# ---------------------------------------------------------------------------
# "I still" coda anaphora shared across stories.


def test_i_still_coda_shared_across_two_stories_fails_the_later_ones():
    plan, stories = _compilation({
        "story_1": _clean("alpha") + " I still take the long way home now.",
        "story_2": _clean("bravo") + " I still lock both doors every night.",
        "story_3": _clean("charlie"),
    })
    report = gate_compilation(plan, stories, _horror())
    assert "stylometric_shared_coda" in _codes(report)
    f = next(f for f in report.failures if f.code == "stylometric_shared_coda")
    # First occurrence keeps its coda; the later duplicate is the one to change.
    assert f.story_ids == ["story_2"]


def test_changed_ritual_coda_family_shared_across_stories_fails():
    """Live 2026-07-19 (78/100): all three stories closed on the interchangeable
    'now I always perform this small ritual' shape under three different
    aftermath labels. The coda family covers the paraphrases, not one wording."""
    plan, stories = _compilation({
        "story_1": _clean("alpha") + "\n\nNow I park under the light and count the rows.",
        "story_2": _clean("bravo") + "\n\nI always check the back seat now.",
        "story_3": _clean("charlie"),
    })
    report = gate_compilation(plan, stories, _horror())
    hits = [f for f in report.failures if f.code == "stylometric_shared_coda"]
    assert hits and hits[0].story_ids == ["story_2"]
    assert "Now I park" in hits[0].message  # both moves quoted


def test_i_still_coda_in_one_story_is_fine():
    plan, stories = _compilation({
        "story_1": _clean("alpha") + " I still take the long way home now.",
        "story_2": _clean("bravo"),
        "story_3": _clean("charlie"),
    })
    assert "stylometric_shared_coda" not in _codes(gate_compilation(plan, stories, _horror()))


# ---------------------------------------------------------------------------
# Negation-reversal rhythm and simile density (P10).


def test_negation_reversal_rhythm_capped_per_story():
    plan, stories = _compilation({
        "story_1": _clean("alpha")
        + " It was no accident. It was chosen. It was not just odd, but wrong.",
        "story_2": _clean("bravo"),
        "story_3": _clean("charlie"),
    })
    assert "stylometric_negation_reversal" in _codes(gate_compilation(plan, stories, _horror()))


def test_single_negation_reversal_is_allowed():
    plan, stories = _compilation({
        "story_1": _clean("alpha") + " It was no accident. It was deliberate.",
        "story_2": _clean("bravo"),
        "story_3": _clean("charlie"),
    })
    assert "stylometric_negation_reversal" not in _codes(gate_compilation(plan, stories, _horror()))


def test_negation_triad_shared_across_stories_fails_the_later_one():
    """Caught live by the critic on 20260718_0917 after the reversal regex
    missed it: 'No hey, no here's your order, no wave.' in two stories."""
    plan, stories = _compilation({
        "story_1": _clean("alpha") + " No hey, no wave, no anything.",
        "story_2": _clean("bravo") + " Not a sound, not a step, not a word from him.",
        "story_3": _clean("charlie"),
    })
    report = gate_compilation(plan, stories, _horror())
    triads = [f for f in report.failures if f.code == "stylometric_negation_triad"]
    assert triads and triads[0].story_ids == ["story_2"]
    # Both offending texts are quoted so the repair is never blind (an unquoted
    # cross-story triad survived 7 repair calls on build 2357).
    assert "No hey" in triads[0].message
    assert "Not a sound" in triads[0].message


def test_single_negation_triad_in_one_story_is_a_legitimate_beat():
    plan, stories = _compilation({
        "story_1": _clean("alpha") + " No hey, no wave, no anything.",
        "story_2": _clean("bravo"),
        "story_3": _clean("charlie"),
    })
    assert "stylometric_negation_triad" not in _codes(gate_compilation(plan, stories, _horror()))


def test_simile_density_is_advisory_not_blocking():
    heavy = " ".join(f"It moved like a {w} shadow." for w in
                     ("slow", "cold", "grey", "thin", "long", "low", "flat", "still"))
    plan, stories = _compilation({
        "story_1": _clean("alpha") + " " + heavy,
        "story_2": _clean("bravo"),
        "story_3": _clean("charlie"),
    })
    report = gate_compilation(plan, stories, _horror())
    assert "stylometric_simile_density" in _flag_codes(report)
    # Advisory: it must NOT be a hard failure that blocks release.
    assert "stylometric_simile_density" not in _codes(report)


# ---------------------------------------------------------------------------
# A genuinely varied compilation passes clean — the gate rejects sameness, not craft.


def test_varied_compilation_passes_the_texture_gate():
    plan, stories = _compilation({
        "story_1": _clean("alpha") + " I checked the lock and went home.",
        "story_2": _clean("bravo") + " The bus pulled away and that was that.",
        "story_3": _clean("charlie") + " My boss believed me, which surprised me.",
    })
    report = gate_compilation(plan, stories, _horror())
    assert not any(c.startswith("stylometric_") for c in _codes(report))


def test_still_watcher_pose_contradicting_threat_identity_fails():
    """Live 2026-07-19 (ranger 0101): an unseen_ambiguous story rendered 'a
    shape... standing square to the cabin' — fully seen, fully still, straight
    from the banned trope, and no layer caught it. With the plan in hand the
    gate can check the pose against the story's own identity label."""
    plan, stories = _compilation({
        "story_1": _clean("alpha"),
        "story_2": _clean("bravo"),
        "story_3": _clean("charlie")
        + " A shape stood at the tree line, standing square to the cabin without moving.",
    })
    # story_3's identity in the fixture is "group" — not the lone_stranger slot.
    report = gate_compilation(plan, stories, _horror())
    hits = [f for f in report.failures if f.code == "stylometric_still_watcher"]
    assert hits and hits[0].story_ids == ["story_3"]
    assert "group" in hits[0].message


def test_lone_stranger_story_may_render_one_still_watcher():
    plan, stories = _compilation({
        "story_1": _clean("alpha")
        + " He stood square to the door, still, hands at his sides.",
        "story_2": _clean("bravo"),
        "story_3": _clean("charlie"),
    })
    # story_1's fixture identity IS lone_stranger — the one allowed slot.
    report = gate_compilation(plan, stories, _horror())
    assert "stylometric_still_watcher" not in _codes(report)


def test_two_stories_rendering_the_still_watcher_fails_the_later_one():
    plan, stories = _compilation({
        "story_1": _clean("alpha") + " He stood square to the door, still as posts.",
        "story_2": _clean("bravo"),
        "story_3": _clean("charlie"),
    })
    # Force story_2 to ALSO render the pose while being lone_stranger-slot...
    # fixture identities: story_1 lone_stranger, story_2 known_regular — a
    # known_regular claiming the pose contradicts its label instead.
    plan2, stories2 = _compilation({
        "story_1": _clean("alpha") + " He stood square to the door, standing still.",
        "story_2": _clean("bravo") + " Del stood there motionless, standing without moving at all.",
        "story_3": _clean("charlie"),
    })
    report = gate_compilation(plan2, stories2, _horror())
    hits = [f for f in report.failures if f.code == "stylometric_still_watcher"]
    assert hits and hits[0].story_ids == ["story_2"]


def test_the_way_something_variant_is_now_counted():
    plan, stories = _compilation({
        "story_1": _clean("alpha")
        + " It left the way something leaves a room. It waited the way someone waits for a bus.",
        "story_2": _clean("bravo"),
        "story_3": _clean("charlie"),
    })
    assert "stylometric_the_way" in _codes(gate_compilation(plan, stories, _horror()))


def test_banned_phrase_failure_quotes_every_occurrence():
    """Live 2026-07-18 (build 1526): one sentence held 'telling myself' twice;
    the unquoted gate message let three repairs and a rewrite die blind fixing
    only the first. The message must quote EVERY hit."""
    plan, stories = _compilation({
        "story_1": _clean("alpha")
        + " I was telling myself I was overreacting, no, I wasn't telling myself anything.",
        "story_2": _clean("bravo"),
        "story_3": _clean("charlie"),
    })
    report = gate_compilation(plan, stories, _horror())
    banned = [f for f in report.failures if f.code == "banned_self_reassurance"]
    assert banned
    assert "2 time(s)" in banned[0].message
    assert banned[0].message.count("telling myself") >= 2
    assert "EVERY occurrence" in banned[0].message


# ---------------------------------------------------------------------------
# A stylometric failure must be REPAIRABLE — attributed to a story and not in
# the unrecoverable set — so the repair wave can rewrite it instead of dead-
# locking the release loop.


def test_stylometric_failures_are_recoverable_by_the_repair_wave():
    plan, stories = _compilation({
        "story_1": _clean("alpha") + " My heart pounded. Quiet. Empty. Still. Nothing. Wrong.",
        "story_2": _clean("bravo"),
        "story_3": _clean("charlie"),
    })
    report = gate_compilation(plan, stories, _horror())
    tex = [f for f in report.failures if f.code.startswith("stylometric_")]
    assert tex, "expected at least one stylometric failure to test recovery routing"
    for f in tex:
        assert f.code not in np._UNRECOVERABLE_GATE_CODES
        assert f.code not in np._COMPILATION_LEVEL_GATE_CODES
        assert f.story_ids, "a recoverable failure must name the story to repair"
    recovery_ids = np._story_recovery_ids(plan, report)
    assert "story_1" in recovery_ids


# ---------------------------------------------------------------------------
# Generic verbatim phrase reuse (live 2026-07-20 front desk, 74/100).
# Checks above name ONE tic each and were all added reactively; the critic kept
# finding new instances the whitelist could not see. This check matches the
# SHAPE — any rare five-word run shared by two narrators.


def test_verbatim_phrase_shared_across_stories_fails_the_later_one():
    """'hands loose at his sides' described two unrelated men in one
    compilation; no named-tic check could see it."""
    plan, stories = _compilation({
        "story_1": _clean("alpha")
        + " He stood with his hands loose at his sides, watching the counter.",
        "story_2": _clean("bravo")
        + " He stepped back with his hands loose at his sides.",
        "story_3": _clean("charlie"),
    })
    report = gate_compilation(plan, stories, _horror())
    shared = [f for f in report.failures if f.code == "stylometric_shared_phrase"]
    assert shared and shared[0].story_ids == ["story_2"]
    assert "hands loose at his sides" in shared[0].message
    assert "story_1" in shared[0].message


def test_phrase_used_repeatedly_inside_one_story_is_that_narrators_own_habit():
    plan, stories = _compilation({
        "story_1": _clean("alpha")
        + " His hands hung loose at his sides. Still loose at his sides, both of them.",
        "story_2": _clean("bravo"),
        "story_3": _clean("charlie"),
    })
    assert "stylometric_shared_phrase" not in _codes(
        gate_compilation(plan, stories, _horror())
    )


def test_shared_function_word_run_is_not_a_shared_phrase():
    """'and I went back to the' carries no voice — flagging it would deadlock
    the repair wave on unfixable connective tissue."""
    plan, stories = _compilation({
        "story_1": _clean("alpha") + " So I went back to the one I had.",
        "story_2": _clean("bravo") + " So I went back to the one I had.",
        "story_3": _clean("charlie"),
    })
    assert "stylometric_shared_phrase" not in _codes(
        gate_compilation(plan, stories, _horror())
    )


def test_shared_domain_vocabulary_from_the_locked_plans_is_exempt():
    """Three narrators on one topic must be free to name the same workplace."""
    plan, stories = _compilation({
        "story_1": _clean("alpha") + " " + _plan().stories[0].setting,
        "story_2": _clean("bravo") + " " + _plan().stories[0].setting,
        "story_3": _clean("charlie"),
    })
    assert "stylometric_shared_phrase" not in _codes(
        gate_compilation(plan, stories, _horror())
    )


def test_shared_phrase_failure_is_repairable_by_the_repair_wave():
    plan, stories = _compilation({
        "story_1": _clean("alpha") + " The cooler seal clicked twice behind me.",
        "story_2": _clean("bravo") + " The cooler seal clicked twice behind me.",
        "story_3": _clean("charlie"),
    })
    report = gate_compilation(plan, stories, _horror())
    shared = [f for f in report.failures if f.code == "stylometric_shared_phrase"]
    assert shared
    for f in shared:
        assert f.code not in np._UNRECOVERABLE_GATE_CODES
        assert f.code not in np._COMPILATION_LEVEL_GATE_CODES
    assert "story_2" in np._story_recovery_ids(plan, report)


def test_procedural_idiom_two_workers_share_independently_is_not_a_habit():
    """Precision lever, measured by replaying the check over the channel's
    66-script corpus: a shared five-word run carrying only two content words is
    procedural idiom ('and put it in park'), not a voice tic. Flagging it spent
    repair waves rewriting prose that read fine."""
    plan, stories = _compilation({
        "story_1": _clean("alpha") + " I pulled in and put it in park.",
        "story_2": _clean("bravo") + " I rolled up and put it in park.",
        "story_3": _clean("charlie"),
    })
    assert "stylometric_shared_phrase" not in _codes(
        gate_compilation(plan, stories, _horror())
    )


def test_every_shared_phrase_is_quoted_not_just_the_first():
    """One quoted phrase per story sent the repair wave back for a second pass
    on the same story; a story that shares two phrases must list both."""
    plan, stories = _compilation({
        "story_1": _clean("alpha")
        + " His hands hung loose at his sides. The porch light came on behind him.",
        "story_2": _clean("bravo")
        + " He stood with his hands hung loose at his sides."
        + " Later the porch light came on for no reason.",
        "story_3": _clean("charlie"),
    })
    report = gate_compilation(plan, stories, _horror())
    shared = [f for f in report.failures if f.code == "stylometric_shared_phrase"]
    assert shared and shared[0].story_ids == ["story_2"]
    assert "hands hung loose at his sides" in shared[0].message
    assert "porch light came on" in shared[0].message
    assert "2 phrase(s)" in shared[0].message
    assert "EVERY occurrence" in shared[0].message
