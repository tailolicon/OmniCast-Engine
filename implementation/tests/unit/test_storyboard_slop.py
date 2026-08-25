"""Anti-slop linter + the continuity checks that need a continuity ANCHOR.

Grouped together because both answer the same question: does the board carry
enough information for consecutive shots to read as one scene, or is it a pile
of independently plausible pictures?
"""

from __future__ import annotations

import pytest

from omnicast.storyboard import slop
from omnicast.storyboard.continuity import Severity, check_continuity
from omnicast.storyboard.models import (
    Entity,
    EntityImage,
    EntityKind,
    Frame,
    FrameType,
    Movement,
    ScreenDirection,
    Shot,
    Storyboard,
)


class TestLazyMotion:
    """Clip prompts only. A still prompt has no motion to judge."""

    def test_camera_only_prompt_blocks(self):
        findings = slop.lint("slow push-in, camera pans right", motion=True)
        assert [f.slop_class for f in findings] == [slop.SlopClass.LAZY_MOTION]
        assert slop.blocking_findings(findings)

    def test_named_lazy_phrase_blocks_even_with_context(self):
        findings = slop.lint(
            "In the workshop the camera pans left across the bench",
            motion=True)
        assert any(f.slop_class is slop.SlopClass.LAZY_MOTION for f in findings)

    def test_real_action_passes(self):
        assert slop.lint(
            "Miko hops onto the stool and places both front paws on the "
            "lantern seam; the camera pushes in slowly",
            motion=True) == []

    def test_still_prompts_are_not_motion_checked(self):
        # Same text, no motion flag: a still prompt describing framing is fine.
        assert slop.lint("slow push-in, camera pans right") == []

    def test_repair_points_at_what_changes(self):
        finding = slop.lint("zoom in slowly", motion=True)[0]
        assert "what changes on screen" in finding.repair


class TestRiskySurfaces:
    """filter-vocab.md, split by consequence: identity and marks are a legal
    problem that outlives the render; graphic surfaces are a delivery problem
    the operator may legitimately choose to keep."""

    def test_celebrity_blocks(self):
        findings = slop.lint("a woman on a bench who looks like a celebrity")
        assert any(f.slop_class is slop.SlopClass.IP_RISK for f in findings)
        assert slop.blocking_findings(findings)

    def test_brand_logo_blocks_even_late_in_the_prompt(self):
        findings = slop.lint(
            "A quiet kitchen at dawn, steam rising from a mug, "
            "a cereal box with a brand logo on the counter")
        blocking = slop.blocking_findings(findings)
        assert [f.slop_class for f in blocking] == [slop.SlopClass.IP_RISK]

    def test_repair_names_the_safe_alternative(self):
        finding = next(f for f in slop.lint("show a brand logo")
                       if f.slop_class is slop.SlopClass.IP_RISK)
        assert "generic product mark" in finding.repair

    def test_horror_surface_warns_but_never_blocks(self):
        findings = slop.lint(
            "A still figure slumped against the cellar door, blood pooling on "
            "the concrete, one visible wound on the forearm")
        assert any(f.slop_class is slop.SlopClass.FILTER_RISK for f in findings)
        assert slop.blocking_findings(findings) == []

    def test_filter_risk_does_not_trip_the_density_rule(self):
        findings = slop.lint("a fight, then blood, then an injury, then a knife")
        assert len(findings) > 2
        assert slop.blocking_findings(findings) == []

    def test_filter_risk_in_opening_still_does_not_block(self):
        findings = slop.lint("Blood on the doorframe, seen from the stairwell")
        assert slop.blocking_findings(findings) == []

    def test_clean_prompt_stays_clean(self):
        assert slop.lint(
            "A fox lifts a paper lantern from the workbench; warm lamp light "
            "from the left; the camera pushes in slowly") == []


# --------------------------------------------------------------------------
# Slop linter
# --------------------------------------------------------------------------

class TestSlopClasses:
    @pytest.mark.parametrize("text,cls", [
        ("Cinematic shot of a woman reading", slop.SlopClass.EMPTY_EVALUATOR),
        ("A kitchen, 8K, highly detailed", slop.SlopClass.BORROWED_TOKEN),
        ("A man at a table, no blur, no extra fingers", slop.SlopClass.NEGATION),
        ("The room, moody and quiet", slop.SlopClass.FEEL_SUFFIX),
    ])
    def test_each_class_is_detected(self, text, cls):
        assert any(f.slop_class is cls for f in slop.lint(text))

    def test_a_keyword_dump_is_caught_by_shape_not_by_words(self):
        """Tag salad has no verb and no time axis — nothing for a video model
        to animate. Detected structurally so novel keyword sets still fire."""
        findings = slop.lint("woman, window, rain, blue tones, night, quiet, "
                             "wide angle, film")

        assert any(f.slop_class is slop.SlopClass.TAG_SALAD for f in findings)

    def test_a_real_shooting_brief_is_clean(self):
        clean = ("A woman turns from the railing at sunset; the low sun flares "
                 "behind her hair. Camera: slow push-in to a medium close-up. "
                 "Sound: wind and distant surf.")

        assert slop.lint(clean) == []

    def test_prose_with_commas_is_not_mistaken_for_tag_salad(self):
        """Ordinary sentences use commas too — the discriminator is verbs."""
        prose = ("Minh sets the keys on the table, pulls out the chair, and "
                 "sits down without looking at her.")

        assert not any(f.slop_class is slop.SlopClass.TAG_SALAD
                       for f in slop.lint(prose))

    def test_every_finding_carries_a_concrete_repair(self):
        for f in slop.lint("A cinematic, dramatic, beautiful room"):
            assert f.repair and len(f.repair) > 10


class TestPositionCost:
    def test_slop_in_the_opening_clause_blocks(self):
        findings = slop.lint("Cinematic shot of Minh at the table under a bulb")

        assert slop.blocking_findings(findings)

    def test_one_hedge_in_the_tail_does_not_block(self):
        """A single soft word deep in a constraint tail is not worth a retake."""
        findings = slop.lint(
            "Minh sets the keys on the table under a single hanging bulb, the "
            "room otherwise dark and still, the mood atmospheric.")

        assert findings, "still reported"
        assert not slop.blocking_findings(findings), "but not blocking"

    def test_the_opening_is_a_clause_not_a_character_count(self):
        """Regression: a flat 120-char window called a tail word an opening
        hit purely because the sentence was short."""
        text = ("Minh sets the keys on the table under a single hanging bulb, "
                "the mood atmospheric.")
        tail = next(f for f in slop.lint(text) if f.text.lower() == "atmospheric")

        assert not tail.in_opening

    def test_negation_blocks_from_anywhere(self):
        """Not a position effect — naming a flaw plants it wherever it sits."""
        findings = slop.lint(
            "Minh sets the keys on the table under a single hanging bulb and "
            "looks at the far wall for a while, no blur.")

        assert slop.blocking_findings(findings)

    def test_density_blocks_even_when_every_hit_is_late(self):
        findings = slop.lint(
            "Minh crosses the room to the table, and the light is beautiful, "
            "the mood dramatic, the whole scene stunning and epic.")

        assert slop.blocking_findings(findings)


# --------------------------------------------------------------------------
# Continuity anchors
# --------------------------------------------------------------------------

def _entity(eid, name, kind=EntityKind.CHARACTER):
    return Entity(entity_id=eid, board_id="b", kind=kind, name=name,
                  images=[EntityImage(image_id=f"{eid}_i", entity_id=eid,
                                      path=f"/r/{eid}.png", approved=True)])


def _shot(index, **kw):
    kw.setdefault("location_id", "e_loc")
    return Shot(shot_id=f"s{index}", board_id="b", index=index, **kw)


def _board(shots, frames=None):
    return Storyboard(
        board_id="b", channel_id="ch",
        entities=[_entity("e_loc", "the kitchen", EntityKind.LOCATION)],
        shots=shots,
        frames=frames if frames is not None else
        [Frame(frame_id=f"f{s.index}", shot_id=s.shot_id,
               frame_type=FrameType.KEY, base_prompt="Minh sits at the table.")
         for s in shots])


def _axes(report, severity):
    return {i.axis for i in report.issues if i.severity is severity}


class TestScreenDirection:
    def test_a_lateral_flip_in_one_location_blocks(self):
        """The 180-degree rule. The viewer reads it as the subject turning
        around, and no per-shot prompt carries the axis on its own."""
        shots = [_shot(0, screen_direction=ScreenDirection.LEFT_TO_RIGHT),
                 _shot(1, screen_direction=ScreenDirection.RIGHT_TO_LEFT)]

        report = check_continuity(_board(shots))

        assert "screen_direction" in _axes(report, Severity.HARD)

    def test_declaring_an_axis_reset_clears_it(self):
        shots = [_shot(0, screen_direction=ScreenDirection.LEFT_TO_RIGHT),
                 _shot(1, screen_direction=ScreenDirection.RIGHT_TO_LEFT,
                       declared_changes=["deliberate axis reset, she crosses"])]

        report = check_continuity(_board(shots))

        assert "screen_direction" not in _axes(report, Severity.HARD)

    def test_a_flip_across_a_location_change_is_not_a_flip(self):
        """A cut to somewhere else resets the axis by definition."""
        shots = [_shot(0, screen_direction=ScreenDirection.LEFT_TO_RIGHT),
                 _shot(1, screen_direction=ScreenDirection.RIGHT_TO_LEFT,
                       location_id=None)]

        report = check_continuity(_board(shots))

        assert "screen_direction" not in _axes(report, Severity.HARD)

    def test_toward_and_away_are_the_same_axis(self):
        shots = [_shot(0, screen_direction=ScreenDirection.TOWARD_CAMERA),
                 _shot(1, screen_direction=ScreenDirection.AWAY_FROM_CAMERA)]

        report = check_continuity(_board(shots))

        assert "screen_direction" not in _axes(report, Severity.HARD)

    def test_undeclared_direction_is_reported_once_for_the_board(self):
        report = check_continuity(_board([_shot(0), _shot(1)]))

        board_level = [i for i in report.issues
                       if i.axis == "screen_direction" and i.shot_index == -1]
        assert len(board_level) == 1
        assert not report.blocked


class TestLightAndMotion:
    def test_an_undeclared_light_change_in_one_room_blocks(self):
        shots = [_shot(0, light_key="single bulb overhead"),
                 _shot(1, light_key="daylight through the window")]

        report = check_continuity(_board(shots))

        assert "lighting" in _axes(report, Severity.HARD)

    def test_declaring_the_light_change_clears_it(self):
        shots = [_shot(0, light_key="single bulb overhead"),
                 _shot(1, light_key="daylight through the window",
                       declared_changes=["the lamp goes out and dawn comes up"])]

        report = check_continuity(_board(shots))

        assert "lighting" not in _axes(report, Severity.HARD)

    def test_dropped_open_motion_warns(self):
        """Motion running at the cut must be inherited or the movement stops
        dead — visible, but not worth blocking a render over."""
        shots = [_shot(0, movement=Movement.TRACK,
                       motion_vector="still walking toward the door"),
                 _shot(1)]

        report = check_continuity(_board(shots))

        assert "motion_vector" in _axes(report, Severity.WARN)
        assert "motion_vector" not in _axes(report, Severity.HARD)


class TestEventDensity:
    def test_replaying_a_completed_beat_blocks(self):
        shots = [_shot(0), _shot(1, beats_completed=["Minh sets the keys on "
                                                     "the table"])]
        frames = [Frame(frame_id="f0", shot_id="s0", frame_type=FrameType.KEY,
                        base_prompt="Minh walks in."),
                  Frame(frame_id="f1", shot_id="s1", frame_type=FrameType.KEY,
                        base_prompt="Minh sets the keys down on the table.")]

        report = check_continuity(_board(shots, frames))

        assert "event_density" in _axes(report, Severity.HARD)

    def test_performing_a_reserved_beat_early_blocks(self):
        shots = [_shot(0, beats_reserved=["Lan turns the ledger around to "
                                          "face him"])]
        frames = [Frame(frame_id="f0", shot_id="s0", frame_type=FrameType.KEY,
                        base_prompt="Lan turns the ledger around so it faces "
                                    "him across the table.")]

        report = check_continuity(_board(shots, frames))

        assert "event_density" in _axes(report, Severity.HARD)

    def test_an_unrelated_prompt_does_not_trip_the_firewall(self):
        shots = [_shot(0, beats_reserved=["Lan turns the ledger around"])]
        frames = [Frame(frame_id="f0", shot_id="s0", frame_type=FrameType.KEY,
                        base_prompt="Minh stands in the doorway with his coat "
                                    "still on.")]

        report = check_continuity(_board(shots, frames))

        assert "event_density" not in _axes(report, Severity.HARD)

    def test_a_beat_too_vague_to_judge_is_not_guessed_at(self):
        """A one-word beat would match half the prompts on the board."""
        shots = [_shot(0, beats_reserved=["the reveal"])]
        frames = [Frame(frame_id="f0", shot_id="s0", frame_type=FrameType.KEY,
                        base_prompt="Minh stands in the doorway.")]

        report = check_continuity(_board(shots, frames))

        assert "event_density" not in _axes(report, Severity.HARD)


class TestSlopReachesTheGate:
    def test_a_slop_prompt_blocks_the_board(self):
        frames = [Frame(frame_id="f0", shot_id="s0", frame_type=FrameType.KEY,
                        base_prompt="Cinematic dramatic shot of the kitchen")]

        report = check_continuity(_board([_shot(0)], frames))

        assert "slop" in _axes(report, Severity.HARD)

    def test_a_clean_prompt_does_not(self):
        frames = [Frame(frame_id="f0", shot_id="s0", frame_type=FrameType.KEY,
                        base_prompt="Minh stands in the doorway, one hand still "
                                    "on the frame, the kitchen dark behind him.")]

        report = check_continuity(_board([_shot(0)], frames))

        assert "slop" not in _axes(report, Severity.HARD)
