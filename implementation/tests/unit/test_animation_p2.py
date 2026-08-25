"""P2 §15/§7.1 — the animation subsystem.

The review's sentence this package is built around: generating a pile of AI
images and crossfading them is not animation. So the tests check two things —
that the computable parts are actually computed correctly, and that the package
never lets itself be mistaken for a renderer it is not.
"""

from __future__ import annotations

import pytest

from omnicast.animation import (
    EASINGS,
    VISEMES,
    CharacterBible,
    Keyframe,
    anticipation_beats,
    check_continuity,
    comic_timing_report,
    ease,
    load_bible,
    readiness,
    squash_and_stretch,
    text_to_visemes,
    visemes_for_transcript,
)
from omnicast.animation.bible import UNBUILT_PARTS
from omnicast.animation.timing import MIN_BEAT_GAP_SECONDS, interpolate

BIBLE_CONFIG = {
    "character_id": "nan",
    "name": "Nan",
    "identity": {"silhouette": "round, short", "hair": "grey bun",
                 "outfit": "blue cardigan", "age_read": "late 60s",
                 "line_style": "thick ink, no hatching"},
    "poses": [{"id": "stand", "description": "neutral standing"},
              {"id": "point", "description": "pointing at a chart"}],
    "expressions": [{"id": "worried", "intensity": 0.7},
                    {"id": "relieved", "intensity": 0.4}],
    "forbidden": ["photorealistic skin"],
}


# ── the bible ───────────────────────────────────────────────────────────────

def test_a_declared_bible_loads_with_its_inventory():
    bible = load_bible(BIBLE_CONFIG)
    assert bible.is_usable is True
    assert bible.pose_ids == {"stand", "point"}
    assert bible.expression_ids == {"worried", "relieved"}


def test_an_incomplete_bible_names_the_traits_that_are_missing():
    """Identity traits are what make the character the same character after a
    cut. A bible without them cannot hold anything together."""
    bible = load_bible({"character_id": "nan", "identity": {"hair": "grey bun"}})
    assert bible.is_usable is False
    assert set(bible.missing_identity) == {"silhouette", "outfit", "age_read",
                                           "line_style"}
    assert any("same character after a cut" in n for n in bible.notes)


def test_a_bible_is_never_invented_from_nothing():
    bible = load_bible(None)
    assert bible.character_id == ""
    assert bible.poses == []
    assert bible.is_usable is False


def test_a_duplicate_pose_is_reported_rather_than_silently_overwritten():
    bible = load_bible({**BIBLE_CONFIG,
                        "poses": [{"id": "stand"}, {"id": "stand"}]})
    assert len(bible.poses) == 1
    assert any("more than once" in n for n in bible.notes)


# ── continuity ──────────────────────────────────────────────────────────────

def test_continuity_names_every_violation_instead_of_scoring_them():
    """"Continuity: 0.83" tells an operator nothing they can act on."""
    issues = check_continuity([
        {"pose": "stand", "expression": "worried"},
        {"pose": "cartwheel"},
        {"expression": "furious"},
        {"character_id": "someone_else"},
        {"narration": "a photorealistic skin close-up"},
    ], load_bible(BIBLE_CONFIG))
    kinds = {i.kind for i in issues}
    assert kinds == {"unknown_pose", "unknown_expression", "wrong_character",
                     "forbidden_element"}
    assert all(i.detail for i in issues)


def test_a_clean_storyboard_produces_no_issues():
    assert check_continuity([{"pose": "point", "expression": "relieved"}],
                            load_bible(BIBLE_CONFIG)) == []


def test_an_unusable_bible_blocks_checking_rather_than_passing_everything():
    issues = check_continuity([{"pose": "anything"}], load_bible({}))
    assert [i.kind for i in issues] == ["no_usable_bible"]


def test_an_unreadable_scene_costs_one_scene_not_the_whole_check():
    issues = check_continuity([None, {"pose": "cartwheel"}],
                              load_bible(BIBLE_CONFIG))
    assert {i.kind for i in issues} == {"unreadable_scene", "unknown_pose"}


# ── it never claims to be a renderer ────────────────────────────────────────

def test_the_package_states_that_it_renders_nothing():
    """`video_intel` was once mistaken for a working analyzer for two sessions.
    This one says what it is."""
    state = readiness()
    assert state["renders_frames"] is False
    assert set(UNBUILT_PARTS) <= set(state["unbuilt"])
    assert "rigging" in state["unbuilt"]
    assert "not animation" in state["note"]


def test_the_router_still_refuses_animation_without_a_declared_capability():
    """The P1 refusal must survive P2: a specification is not a capability."""
    from omnicast.media.production_router import ANIMATION, route_scene

    route = route_scene(0, "Our character leaps across the gap",
                        capabilities={"screen_capture"})
    assert route.requested_mode == ANIMATION
    assert route.mode != ANIMATION
    assert route.fallback_reason


# ── timing ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("kind", EASINGS)
def test_every_easing_starts_at_zero_and_ends_at_one(kind):
    assert ease(kind, 0.0) == pytest.approx(0.0, abs=1e-6)
    assert ease(kind, 1.0) == pytest.approx(1.0, abs=1e-6)


def test_anticipation_goes_negative_before_it_goes_forward():
    """Clamping it to [0,1] would remove the only thing that makes it
    anticipation."""
    early = ease("anticipate", 0.1)
    assert early < 0.0


def test_overshoot_passes_the_target_before_settling():
    assert max(ease("overshoot", t / 100) for t in range(1, 100)) > 1.0
    assert ease("overshoot", 1.0) == pytest.approx(1.0)


def test_squash_and_stretch_preserves_volume():
    """A squash that does not conserve volume is scaling, and it reads as a
    rendering bug rather than as weight."""
    for factor in (0.6, 0.8, 1.0, 1.4, 2.0):
        x, y = squash_and_stretch(factor)
        assert x * y == pytest.approx(1.0, abs=1e-3)


def test_a_nonsense_scale_is_the_identity_not_a_crash():
    assert squash_and_stretch(0) == (1.0, 1.0)
    assert squash_and_stretch(-2) == (1.0, 1.0)
    assert squash_and_stretch("x") == (1.0, 1.0)
    assert squash_and_stretch(float("inf")) == (1.0, 1.0)


def test_anticipation_beats_produce_a_real_three_frame_move():
    frames = anticipation_beats(1.0, 2.0)
    assert [round(k.time, 2) for k in frames] == [1.0, 1.25, 2.0]
    assert frames[1].value < 0.0
    assert frames[-1].value == pytest.approx(1.0)


def test_a_move_that_does_not_move_returns_nothing():
    assert anticipation_beats(2.0, 2.0) is None
    assert anticipation_beats(2.0, 1.0) is None
    assert anticipation_beats(None, 1.0) is None


def test_interpolation_holds_the_ends_and_eases_between_them():
    frames = [Keyframe(0.0, 0.0), Keyframe(2.0, 10.0, easing="linear")]
    assert interpolate(frames, -5) == 0.0
    assert interpolate(frames, 99) == 10.0
    assert interpolate(frames, 1.0) == pytest.approx(5.0)
    assert interpolate([], 1.0) is None


def test_comic_timing_measures_spacing_and_refuses_to_judge_the_joke():
    report = comic_timing_report([0.0, 0.1, 1.5, 9.0])
    assert report.beats == 4
    assert report.too_tight == [0]
    assert report.too_slack == [2]
    assert "not a number" in report.as_dict()["note"]


def test_one_beat_cannot_have_timing():
    report = comic_timing_report([1.0])
    assert report.is_measurable is False
    assert report.median_gap is None
    assert any("at least one interval" in n for n in report.notes)


def test_comic_timing_ignores_unusable_beat_times():
    report = comic_timing_report([0.0, "x", None, float("nan"), MIN_BEAT_GAP_SECONDS * 3])
    assert report.beats == 2


# ── lip sync ────────────────────────────────────────────────────────────────

def test_visemes_cover_the_cue_and_nothing_beyond_it():
    cues = text_to_visemes("hello", 1.0, 0.5)
    assert cues
    assert cues[0].start == pytest.approx(1.0)
    assert cues[-1].end == pytest.approx(1.5)
    assert all(c.viseme in VISEMES for c in cues)


def test_lips_close_for_m_b_p():
    cues = text_to_visemes("mama", 0.0, 1.0)
    assert "MBP" in [c.viseme for c in cues]


def test_silence_produces_a_rest_not_a_random_shape():
    assert [c.viseme for c in text_to_visemes("...", 0.0, 1.0)] == ["rest"]
    assert text_to_visemes("hello", 0.0, 0) == []


def test_shapes_too_brief_to_see_are_merged_not_chattered():
    """A mouth changing shape every 12ms is not lip sync; a renderer would
    faithfully reproduce it as chatter."""
    cues = text_to_visemes("abcdefghijklmnop", 0.0, 0.08)
    assert all(c.duration >= 1.0 / 24.0 - 1e-6 for c in cues[:-1])


def test_a_transcript_becomes_a_track_with_rests_in_the_gaps():
    from omnicast.analytics.transcript import Segment, Transcript

    transcript = Transcript(
        video_id="v", text="hello there", source="test",
        segments=(Segment(0.0, "hello", 1.0), Segment(3.0, "there", 1.0)))
    track = visemes_for_transcript(transcript)
    assert track
    assert any(c.viseme == "rest" and c.start >= 1.0 for c in track)


def test_every_cue_declares_that_it_is_an_estimate():
    """Real phoneme timing needs a forced aligner. A renderer — or a reviewer —
    must be able to tell which this is."""
    cues = text_to_visemes("hello", 0.0, 1.0)
    assert all(c.source == "grapheme_estimate" for c in cues)


def test_a_transcript_without_timings_yields_no_track():
    class _Bare:
        segments = ()

    assert visemes_for_transcript(_Bare()) == []
