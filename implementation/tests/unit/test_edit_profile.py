"""Measured editing profile — the competitor's cut, not our house habit.

`av_forensics` could always measure how a video was cut; the competitor half
never ran, so the renderer's defaults (a 0.15s fade on every shot, an 18-word
beat) were never checked against anyone. The cohort turned out to cut straight
(dissolves ≈ 2%) and to hold shots ~4.9s against our defaults. These tests pin
the profile and the fact that the renderer reads it.
"""

from __future__ import annotations

from pathlib import Path

from omnicast.analytics.edit_profile import build_profile

FORENSICS = {
    "w1": {"role": "winner", "median_shot_seconds": 4.9, "cuts_per_minute": 7.6,
           "silence_ratio": 0.05, "integrated_lufs": -22.3,
           "transition_mix": {"cut": 102, "dissolve": 2},
           "motion_mix": {"drift": 0.69, "static": 0.24, "dynamic": 0.07},
           "text_overlay_proxy": 0.46, "duration_seconds": 700.0,
           "not_measured": {"sfx_taxonomy": "needs a classifier"}},
    "w2": {"role": "winner", "median_shot_seconds": 5.1, "cuts_per_minute": 2.8,
           "silence_ratio": 0.15, "integrated_lufs": -21.0,
           "transition_mix": {"cut": 40, "dissolve": 1},
           "motion_mix": {"drift": 0.70, "static": 0.25, "dynamic": 0.05},
           "text_overlay_proxy": 0.60, "duration_seconds": 720.0,
           "not_measured": {}},
    "c1": {"role": "control", "median_shot_seconds": 10.8, "cuts_per_minute": 3.0,
           "silence_ratio": 0.20, "integrated_lufs": -31.8,
           "transition_mix": {"cut": 20, "dissolve": 6},
           "motion_mix": {"drift": 0.5, "static": 0.5},
           "text_overlay_proxy": 0.3, "duration_seconds": 470.0,
           "not_measured": {}},
}


def test_profile_separates_winner_and_control_shot_length():
    p = build_profile(FORENSICS)
    assert p.winner_count == 2 and p.control_count == 1
    assert p.median_shot_seconds == 5.0
    assert p.control_median_shot_seconds == 10.8


def test_dissolve_share_reflects_straight_cutting():
    p = build_profile(FORENSICS)
    assert p.dissolve_share is not None and p.dissolve_share < 0.05


def test_directives_state_only_what_was_measured():
    """The first version asserted 'winners re-frame twice as often' (the
    cut-rate data says otherwise), 'no whooshes, no wipes' (SFX unclassified)
    and 'pauses are not filled with music swells' (non-speech audio
    unmeasured). Those inferences must not come back."""
    p = build_profile(FORENSICS)
    text = " ".join(p.as_directives())
    assert "Median shot length" in text
    assert "Speech-silence" in text
    assert "%" in text
    # measured-limit disclosures
    assert "NOT measured" in text
    assert "PROXY" in text or "proxy" in text
    # banned inferences
    for claim in ("twice as often", "No whooshes", "no wipes", "music swells"):
        assert claim not in text


def test_sufficiency_gate_marks_a_thin_cohort_as_non_production():
    """5 winners / 2 controls / 2 matched pairs reached the renderer once."""
    p = build_profile(FORENSICS)
    assert p.is_production_grade is False
    assert "NOT production-grade" in p.as_directives()[0]


def test_unmeasured_fields_are_carried_not_guessed():
    p = build_profile(FORENSICS)
    assert "sfx_taxonomy" in p.unmeasured


def test_empty_cohort_yields_empty_profile():
    p = build_profile({"c1": FORENSICS["c1"]})
    assert p.winner_count == 0 and p.median_shot_seconds is None
    # only the sufficiency banner — no measurement lines
    assert len(p.as_directives()) == 1
    assert "NOT production-grade" in p.as_directives()[0]


def test_renderer_reads_the_measured_profile():
    """A measurement nothing consumes is a note, not a behaviour."""
    import channel_render

    src = (Path(channel_render.__file__).resolve().parent
           / "render_real_video.py").read_text(encoding="utf-8")
    assert "edit_profile.json" in src
    assert "EDIT_FADE" in src
    # the straight-cut decision must be data-driven, not hardcoded away
    assert "dissolve_share" in src


def test_fade_default_is_the_house_value_not_the_ungated_finding():
    """A gate that only blocks the override is not a gate.

    The module default was moved to 0.0 ("the cohort cuts straight") — a
    finding from 5 winners / 2 controls that the profile gate then refused.
    Production had already adopted it, because the gate could stop the profile
    from overriding but could not restore a default that had been changed."""
    import render_real_video as rrv

    assert rrv.EDIT_FADE_DEFAULT == 0.15
    assert rrv.EDIT_FADE == rrv.EDIT_FADE_DEFAULT

    import channel_render

    src = (Path(channel_render.__file__).resolve().parent
           / "render_real_video.py").read_text(encoding="utf-8")
    # the gated branch must RESTORE the default, not merely skip the override
    gate = src.index('_ok = _chan >= 3 and _pairs >= 10')
    restore = src.index('globals()["EDIT_FADE"] = EDIT_FADE_DEFAULT')
    override = src.index('globals()["EDIT_FADE"] = 0.0')
    assert gate < restore < override
