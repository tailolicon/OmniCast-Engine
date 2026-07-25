"""P0 brief §15/§7 — the production mode router.

The review's question, verbatim: does this scene need stock, a real photo, a
chart, an AI reconstruction, character animation, a motion graphic, a screen
capture — or no picture at all, just a hold? Nothing in the pipeline asked it.

The tests below care less about classification accuracy (a keyword router will
never be perfect) than about the three properties that make it safe to put in
front of a renderer: it only routes to modes we can produce, it says when it
guessed, and it flags what needs disclosure.
"""

from __future__ import annotations

import pytest

from omnicast.media.production_router import (
    AI_ILLUSTRATION,
    ALL_MODES,
    ANIMATION,
    FALLBACKS,
    INFOGRAPHIC,
    MODE_REQUIREMENTS,
    REAL_EVIDENCE,
    RECONSTRUCTION,
    SCREEN_CAPTURE,
    SILENCE_HOLD,
    STOCK,
    TALKING_HEAD,
    capabilities_from_channel,
    classify_scene,
    route_scene,
    route_storyboard,
    summarise,
)

# What the engine can do out of the box: no camera, no crew, no animator.
DEFAULT_CAPS = {"screen_capture"}


@pytest.mark.parametrize("text,expected", [
    ("Retirement costs rose 42% in a decade", INFOGRAPHIC),
    ("Click the settings menu and open the tab you need", SCREEN_CAPTURE),
    ("According to the study, half of them never claimed it", REAL_EVIDENCE),
    ("In 1348 the ships reached the harbour", RECONSTRUCTION),
    ("A city street at dusk, people walking", STOCK),
    ("...", SILENCE_HOLD),
])
def test_each_signal_routes_to_its_own_grammar(text, expected):
    mode, confidence, _evidence = classify_scene(text)
    assert mode == expected
    assert confidence > 0.4


def test_a_scene_with_no_signal_is_defaulted_and_says_so():
    """"No rule fired" is not evidence for illustration. A reviewer has to be
    able to tell a classified scene from a defaulted one."""
    route = route_scene(0, "And that changes everything.", capabilities=DEFAULT_CAPS)
    assert route.mode == AI_ILLUSTRATION
    assert route.confidence <= 0.4
    assert any("defaulted" in n for n in route.notes)


def test_a_statistic_beats_a_date_because_priority_is_a_decision():
    """A scene that quotes a number AND names a year is a chart, not a
    dramatisation. Rule order encodes that, so it gets a test."""
    mode, _c, _e = classify_scene("In 1929 the market fell 89% in three years")
    assert mode == INFOGRAPHIC


def test_the_classification_carries_the_phrase_that_caused_it():
    _mode, _confidence, evidence = classify_scene("It grew by 300% last year")
    assert evidence


# ── it only routes to modes we can actually produce ─────────────────────────

def test_a_talking_head_scene_is_never_routed_to_a_pipeline_with_no_presenter():
    """Returning `talking_head` to a renderer that has no face has not solved
    the problem; it has moved the failure one stage later."""
    route = route_scene(0, "I'm standing here on camera to explain it",
                        capabilities=DEFAULT_CAPS)
    assert route.requested_mode == TALKING_HEAD
    assert route.mode != TALKING_HEAD
    assert route.was_substituted is True
    assert "face_cam" in route.fallback_reason


def test_animation_is_not_faked_with_a_pile_of_ai_frames_silently():
    """§7.1 is explicit that character animation is a subsystem, not a prompt.
    The substitution is allowed; hiding it is not."""
    route = route_scene(0, "Our character leaps across the gap",
                        capabilities=DEFAULT_CAPS)
    assert route.requested_mode == ANIMATION
    assert route.mode == AI_ILLUSTRATION
    assert route.fallback_reason


def test_a_declared_capability_unlocks_its_mode():
    channel = type("C", (), {"supported_production": ["character_animation"]})()
    caps = capabilities_from_channel(channel)
    route = route_scene(0, "Our character leaps across the gap", capabilities=caps)
    assert route.mode == ANIMATION
    assert route.was_substituted is False


def test_substituting_a_reconstruction_for_evidence_warns_about_the_script():
    """The dangerous case: the narration says "the original footage" and the
    screen shows something we generated."""
    route = route_scene(0, "The original footage shows him leaving at nine",
                        capabilities=DEFAULT_CAPS)
    assert route.requested_mode == REAL_EVIDENCE
    assert route.mode == RECONSTRUCTION
    assert any("must not describe it as footage" in n for n in route.notes)


def test_every_fallback_chain_terminates_somewhere_producible():
    for mode in ALL_MODES:
        chain = FALLBACKS.get(mode, ())
        if MODE_REQUIREMENTS[mode] - DEFAULT_CAPS:
            assert any(not (MODE_REQUIREMENTS[c] - DEFAULT_CAPS) for c in chain), mode


def test_screen_capture_is_available_by_default_because_it_is_true():
    route = route_scene(0, "Click the dashboard and log in",
                        capabilities=capabilities_from_channel(object()))
    assert route.mode == SCREEN_CAPTURE


# ── disclosure ──────────────────────────────────────────────────────────────

def test_a_synthetic_visual_of_a_real_event_is_flagged_for_disclosure():
    route = route_scene(0, "In 1348 the ships reached the harbour",
                        capabilities=DEFAULT_CAPS, depicts_real_events=True)
    assert route.requires_disclosure is True
    assert any("disclosure" in n for n in route.notes)


def test_the_same_scene_in_fiction_needs_no_such_flag():
    route = route_scene(0, "In 1348 the ships reached the harbour",
                        capabilities=DEFAULT_CAPS, depicts_real_events=False)
    assert route.requires_disclosure is False


def test_stock_footage_of_a_real_event_is_not_a_synthetic_claim():
    route = route_scene(0, "A city street at dusk, people walking",
                        capabilities=DEFAULT_CAPS, depicts_real_events=True)
    assert route.mode == STOCK
    assert route.requires_disclosure is False


# ── whole boards ────────────────────────────────────────────────────────────

def _board():
    return [
        {"narration": "Retirement costs rose 42% in a decade"},
        {"narration": "In 1348 the ships reached the harbour"},
        {"narration": "And that changes everything."},
        {"narration": "I'm standing here on camera"},
        {"narration": "..."},
    ]


def test_a_board_is_routed_scene_by_scene_and_summarised():
    routes = route_storyboard(_board(), capabilities=DEFAULT_CAPS)
    assert len(routes) == 5
    report = summarise(routes)
    assert report["scenes"] == 5
    assert report["modes"][INFOGRAPHIC] == 1
    assert report["substituted_count"] >= 1
    assert report["defaulted_count"] == 1
    assert 0.0 < report["classified_ratio"] < 1.0


def test_routes_map_onto_the_storyboard_vocabulary_the_renderers_already_use():
    routes = route_storyboard(_board(), capabilities=DEFAULT_CAPS)
    assert {r.visual_type for r in routes} <= {"stock_video", "generated_image", "hold"}


def test_a_malformed_scene_does_not_abort_the_board():
    """One bad row must cost one row. A discovery run aborting on a single
    malformed entry is a failure mode this repo has already paid for once."""
    routes = route_storyboard([{"narration": "It grew by 300%"}, None, "oops"],
                              capabilities=DEFAULT_CAPS)
    assert len(routes) == 3
    assert routes[0].mode == INFOGRAPHIC
