"""The skeleton has to be enforced, per channel, and not merely described.

Two findings drive this file.

First: prose is a suggestion. The finance measurement — our drafts ran a fifth
of the cohort's first-person presence and half its sentence variety — went into
a 5,000-word steering brief twice, and the next draft moved one metric out of
nine.

Second, and the reason this is keyed by channel: two niches measured on the
same ruler want OPPOSITE things. Retirement explainers address the viewer
constantly (`you` 4.7 per 100 words) and reference themselves sparingly (`I`
2.4). First-person horror is the mirror (`you` 0.4, `I` 6.8), and its failure
is excess rather than absence — 24-word sentences against a genre whose entire
distribution runs 10 to 15. A single global rule would have ordered every
horror narrator to start lecturing the audience.
"""

from __future__ import annotations

from omnicast.analytics.skeleton import (
    COHORT_MEDIANS,
    SKELETON_BOUNDS,
    analyse,
    skeleton_problems,
)
from omnicast.models.script import ScriptDraft, ScriptScene, ScriptSegment

FINANCE = "senior_wealth_us"
HORROR = "true_dread_files_us"


def _draft(text: str) -> ScriptDraft:
    """A real draft: the gate reads it through the critic's own canonicaliser,
    which knows about scenes, headings and hooks."""
    return ScriptDraft(
        variant_id="A", brief_title="T", hook="",
        segments=[ScriptSegment(
            index=1, heading="Body", content=text,
            estimated_duration_seconds=len(text.split()) // 2,
            scenes=[ScriptScene(voiceover=text, visual_prompt="desk")],
        )],
    )


# A finance voice with a self, an addressee, and varied rhythm.
ALIVE = (
    "I want to show you something that took me a while to accept. "
    "The earnings test is not a tax. I know how that sounds. "
    "You have seen money vanish from your check and nobody told you where it "
    "went, and when I first read the rule I assumed the same thing you did, "
    "which is that it was gone the way withholding on a paycheck is gone. "
    "It is not. Here is the part I think is badly named. "
    "You get it back. Not all at once, and not as a refund, but at full "
    "retirement age your monthly benefit is recalculated and the months they "
    "held back are credited into it, which is a very different thing from a "
    "tax and deserves a very different name. So why does nobody say that? "
) * 6

# Same information, no narrator, uniform rhythm, no addressee.
BULLETIN = (
    "The earnings test applies to beneficiaries under full retirement age. "
    "The annual exempt amount for 2026 is twenty four thousand four hundred. "
    "Earnings above that amount are subject to withholding at a set rate. "
    "The withholding rate is one dollar for every two dollars above it. "
    "A separate rate applies during the year of full retirement age. "
    "Benefits are recalculated once full retirement age has been reached. "
) * 12

# Horror told the way the genre tells it: anchored, plain, with short bursts.
HORROR_GOOD = (
    "I was 21 when this happened. It was 2017. "
    "I worked nights at a gas station two towns over from where I lived. "
    "The shifts were easy. Mostly snacks and cigarettes. "
    "Nobody came in after two. That night somebody did. "
    "He stood by the cooler and did not pick anything up. "
    "I asked if he needed help. He did not answer. "
    "The lights hummed. My hands went cold. I did not move. "
) * 12

# Horror written as literary prose: long sentences, no anchor, no bursts.
HORROR_PROSE = (
    "Overnight tow work is what I have done most of my adult life, and "
    "repossession is simply the branch of it that pays rather better for the "
    "very same dead hours a person spends waiting on a radio. "
    "You take the calls that come in after midnight because nobody else wants "
    "to be awake for them, and you learn a street by its porch lights long "
    "before you ever learn the house numbers written on any of its mailboxes. "
) * 14


def test_two_channels_want_opposite_things():
    fin, hor = SKELETON_BOUNDS[FINANCE], SKELETON_BOUNDS[HORROR]
    assert fin["you_per_100w"][0] > COHORT_MEDIANS[HORROR]["you_per_100w"], (
        "the finance floor for direct address sits ABOVE the horror cohort's "
        "median — one global rule would have been unmeetable for horror")
    # finance bounds are minimums, horror's are dominated by maximums
    assert all(low is not None for low, _ in fin.values())
    assert sum(high is not None for _, high in hor.values()) >= 2


def test_a_channel_with_no_measured_corpus_is_not_gated():
    """Inventing bounds for an unmeasured niche is the mistake the per-channel
    table exists to prevent."""
    assert skeleton_problems(BULLETIN, "quiet_hours_drama_us") == []
    assert skeleton_problems(BULLETIN, "") == []


def test_bounds_bracket_their_own_cohort_median():
    """A floor above the median, or a ceiling below it, would order the writer
    to be unlike the genre it is competing in."""
    for channel, bounds in SKELETON_BOUNDS.items():
        for key, (low, high) in bounds.items():
            median = COHORT_MEDIANS[channel][key]
            if low is not None:
                assert low < median, f"{channel}.{key}: floor {low} >= median"
            if high is not None:
                assert high > median, f"{channel}.{key}: ceiling {high} <= median"


def test_a_finance_bulletin_is_caught():
    problems = skeleton_problems(BULLETIN, FINANCE)
    assert problems
    joined = " ".join(problems).lower()
    assert "first-person presence" in joined or "direct address" in joined


def test_a_finance_script_with_a_voice_passes():
    assert skeleton_problems(ALIVE, FINANCE) == []


def test_horror_prose_is_caught_for_being_too_literary():
    """The opposite failure: not thin, but written rather than spoken."""
    problems = skeleton_problems(HORROR_PROSE, HORROR)
    joined = " ".join(problems).lower()
    assert "sentence length" in joined
    assert "ceiling" in joined            # a maximum, not a floor
    assert "short-sentence bursts" in joined


def test_horror_told_the_way_the_genre_tells_it_passes():
    assert skeleton_problems(HORROR_GOOD, HORROR) == []


def test_the_wrong_channel_s_bounds_produce_nonsense_on_purpose():
    """Documents why the table is keyed by channel: judged as finance, a
    perfectly good horror script is 'missing' direct address it should never
    have."""
    wrong = skeleton_problems(HORROR_GOOD, FINANCE)
    assert any("direct address" in p.lower() for p in wrong)


def test_the_message_names_the_measurement_the_cohort_and_the_bound():
    for text, channel in ((BULLETIN, FINANCE), (HORROR_PROSE, HORROR)):
        for p in skeleton_problems(text, channel):
            assert "competitors in this niche run" in p
            assert ("floor for this channel is" in p
                    or "ceiling for this channel is" in p)


def test_a_fragment_is_not_judged_on_rhythm():
    assert skeleton_problems("I think this is wrong. You should see why.",
                             FINANCE) == []


def test_rhythm_is_not_judged_on_an_unpunctuated_source():
    """Sentence length measured off the 14-word fallback chunker is the chunk
    size, not a sentence length. 15 of 147 horror captions land there."""
    unpunctuated = " ".join(["word"] * 900)
    problems = skeleton_problems(unpunctuated, HORROR)
    assert not any("sentence length" in p.lower() for p in problems)


def test_the_gate_cuts_spoken_presence_and_nothing_else():
    from omnicast.models.script import CriticDimension, CriticFeedback
    from omnicast.pipeline.steps import _apply_skeleton_gate

    fb = CriticFeedback(
        total_score=80, voiceover_score=56, production_score=24, approved=True,
        dimensions=[
            CriticDimension(name="spoken_presence", score=10, max_score=10,
                            feedback="reads well"),
            CriticDimension(name="accuracy_trust", score=16, max_score=16,
                            feedback="sound"),
        ])

    out, problems = _apply_skeleton_gate(fb, _draft(BULLETIN), FINANCE)
    assert problems
    by_name = {x.name: x.score for x in out.dimensions}
    assert by_name["spoken_presence"] == 5          # halved
    assert by_name["accuracy_trust"] == 16          # untouched
    assert out.voiceover_score == 51
    assert out.total_score == 75


def test_a_breached_bound_blocks_release_rather_than_costing_points():
    """A deduction is not containment. The first version only cut points, and a
    draft under two of three bounds scored 87, lost 5, and shipped at 82 as
    production_ready — the same bulletin with a penalty attached."""
    from omnicast.models.script import CriticDimension, CriticFeedback
    from omnicast.pipeline.steps import _apply_skeleton_gate

    fb = CriticFeedback(
        total_score=87, voiceover_score=63, production_score=24, approved=True,
        dimensions=[CriticDimension(name="spoken_presence", score=10,
                                    max_score=10, feedback="fine")])

    out, problems = _apply_skeleton_gate(fb, _draft(BULLETIN), FINANCE)
    assert problems
    assert out.approved is False
    assert any("spoken skeleton" in r for r in out.rejection_reasons)


def test_a_clean_draft_passes_through_the_gate_unchanged():
    from omnicast.models.script import CriticDimension, CriticFeedback
    from omnicast.pipeline.steps import _apply_skeleton_gate

    fb = CriticFeedback(
        total_score=80, voiceover_score=56, production_score=24, approved=True,
        dimensions=[CriticDimension(name="spoken_presence", score=9,
                                    max_score=10, feedback="good")])

    out, problems = _apply_skeleton_gate(fb, _draft(ALIVE), FINANCE)
    assert problems == []
    assert out is fb


def test_the_narrative_flow_is_wired_too():
    """The horror channel does not use the critic path at all — it runs
    unit_first through gate_compilation, so wiring only the finance flow would
    have left the channel that needs this most ungated."""
    from pathlib import Path

    import omnicast.agents.narrative_pipeline as np
    from omnicast.config.narrative_quality import SCRIPT_PROFILE_REGISTRY

    profile = SCRIPT_PROFILE_REGISTRY["true_horror_strict_v1"]
    assert profile.skeleton_bounds_channel == HORROR
    src = Path(np.__file__).read_text(encoding="utf-8")
    assert "skeleton_out_of_bounds" in src
    assert "skeleton_problems(narration, _sk_channel)" in src


def test_the_profiler_and_the_gate_use_one_ruler():
    from pathlib import Path

    import omnicast.analytics.skeleton as sk

    tool = (Path(sk.__file__).resolve().parents[3].parent / "scripts"
            / "extract_skeleton.py")
    if tool.exists():
        src = tool.read_text(encoding="utf-8")
        assert "from omnicast.analytics.skeleton import" in src
    assert analyse("x", "t", "ours", ALIVE).words > 0
