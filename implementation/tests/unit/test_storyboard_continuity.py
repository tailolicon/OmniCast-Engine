"""Continuity gate — what blocks a board, what only warns, and why.

The split matters more than the individual checks. Identity is a closed door:
there is no story reason for the same character in the same role to be backed
by a different face file, and "the script said so" is exactly the excuse that
lets drift ship. Wardrobe and location are doors with a handle: they change on
purpose all the time, and a shot that declares the change is not defective.
"""

from __future__ import annotations

import pytest

from omnicast.storyboard.continuity import Severity, check_continuity
from omnicast.storyboard.models import (
    Angle,
    CameraShot,
    Entity,
    EntityImage,
    EntityKind,
    Frame,
    FrameType,
    Movement,
    RefMapping,
    RefRole,
    Shot,
    ShotEntityRef,
    Storyboard,
)


def _entity(eid, name, kind=EntityKind.CHARACTER, *, approved=True, **kw):
    return Entity(entity_id=eid, board_id="b", kind=kind, name=name,
                  images=[EntityImage(image_id=f"{eid}_i", entity_id=eid,
                                      path=f"/r/{eid}.png", approved=approved)],
                  **kw)


def _shot(index, *, cast=(), location="e_loc", **kw):
    return Shot(shot_id=f"s{index}", board_id="b", index=index,
                location_id=location,
                cast=[ShotEntityRef(entity_id=e, index=i)
                      for i, e in enumerate(cast)],
                camera_shot=kw.pop("camera_shot", CameraShot.MS),
                angle=kw.pop("angle", Angle.EYE_LEVEL),
                movement=kw.pop("movement", Movement.STATIC), **kw)


def _frame(shot_id, mappings, ftype=FrameType.KEY):
    return Frame(frame_id=f"f_{shot_id}_{ftype.value}", shot_id=shot_id,
                 frame_type=ftype, mappings=mappings)


def _map(eid, name, path, *, kind=EntityKind.CHARACTER, role=RefRole.IDENTITY):
    return RefMapping(token="[IMAGE 1]", entity_id=eid, name=name, kind=kind,
                      role=role, path=path)


def _board(entities, shots, frames):
    return Storyboard(board_id="b", channel_id="ch", entities=entities,
                      shots=shots, frames=frames)


@pytest.fixture
def two_shots():
    entities = [_entity("e_minh", "Minh"),
                _entity("e_loc", "the kitchen", EntityKind.LOCATION)]
    shots = [_shot(0, cast=["e_minh"]), _shot(1, cast=["e_minh"])]
    return entities, shots


def _axes(report, severity):
    return {i.axis for i in report.issues if i.severity is severity}


class TestIdentityDrift:
    def test_the_same_character_bound_to_two_files_blocks(self, two_shots):
        entities, shots = two_shots
        frames = [_frame("s0", [_map("e_minh", "Minh", "/r/a.png")]),
                  _frame("s1", [_map("e_minh", "Minh", "/r/b.png")])]

        report = check_continuity(_board(entities, shots, frames))

        assert report.blocked
        issue = next(i for i in report.hard if i.axis == "identity")
        assert "/r/a.png" in issue.evidence and "/r/b.png" in issue.evidence

    def test_declaring_a_change_does_not_excuse_identity_drift(self, two_shots):
        """A closed door: no declaration re-opens it."""
        entities, shots = two_shots
        shots[1] = shots[1].model_copy(update={"declared_changes": [
            "she changes into a uniform", "cut to a new location",
            "intentional next shot", "he takes off the coat"]})
        frames = [_frame("s0", [_map("e_minh", "Minh", "/r/a.png")]),
                  _frame("s1", [_map("e_minh", "Minh", "/r/b.png")])]

        assert check_continuity(_board(entities, shots, frames)).blocked

    def test_the_same_file_across_shots_is_clean(self, two_shots):
        entities, shots = two_shots
        frames = [_frame("s0", [_map("e_minh", "Minh", "/r/a.png")]),
                  _frame("s1", [_map("e_minh", "Minh", "/r/a.png")])]

        assert "identity" not in _axes(check_continuity(
            _board(entities, shots, frames)), Severity.HARD)


class TestDeclarableAxes:
    def test_undeclared_location_change_blocks(self, two_shots):
        entities, shots = two_shots
        frames = [
            _frame("s0", [_map("e_loc", "the kitchen", "/r/k1.png",
                               kind=EntityKind.LOCATION,
                               role=RefRole.ENVIRONMENT)]),
            _frame("s1", [_map("e_loc", "the kitchen", "/r/k2.png",
                               kind=EntityKind.LOCATION,
                               role=RefRole.ENVIRONMENT)]),
        ]

        assert "location" in _axes(check_continuity(
            _board(entities, shots, frames)), Severity.HARD)

    def test_declaring_the_move_clears_it(self, two_shots):
        entities, shots = two_shots
        shots[1] = shots[1].model_copy(update={
            "declared_changes": ["cut to the alley outside"]})
        frames = [
            _frame("s0", [_map("e_loc", "the kitchen", "/r/k1.png",
                               kind=EntityKind.LOCATION,
                               role=RefRole.ENVIRONMENT)]),
            _frame("s1", [_map("e_loc", "the kitchen", "/r/k2.png",
                               kind=EntityKind.LOCATION,
                               role=RefRole.ENVIRONMENT)]),
        ]

        assert "location" not in _axes(check_continuity(
            _board(entities, shots, frames)), Severity.HARD)


class TestCast:
    def test_an_entity_with_no_approved_image_blocks(self):
        entities = [_entity("e_minh", "Minh", approved=False),
                    _entity("e_loc", "the kitchen", EntityKind.LOCATION)]
        shots = [_shot(0, cast=["e_minh"])]

        report = check_continuity(_board(entities, shots,
                                         [_frame("s0", [])]))

        assert any(i.axis == "identity" and "no approved reference image"
                   in i.detail for i in report.hard)

    def test_an_unresolved_merge_conflict_blocks(self):
        entities = [_entity("e_minh", "Minh", conflicts=["is this the driver?"]),
                    _entity("e_loc", "the kitchen", EntityKind.LOCATION)]
        shots = [_shot(0, cast=["e_minh"])]

        report = check_continuity(_board(entities, shots, [_frame("s0", [])]))

        assert any(i.axis == "cast" for i in report.hard)

    def test_a_shot_naming_an_entity_outside_the_registry_blocks(self):
        entities = [_entity("e_loc", "the kitchen", EntityKind.LOCATION)]
        shots = [_shot(0, cast=["e_ghost"])]

        report = check_continuity(_board(entities, shots, [_frame("s0", [])]))

        assert any(i.axis == "cast" and "e_ghost" in i.evidence
                   for i in report.hard)


class TestChain:
    def test_a_parent_that_does_not_exist_blocks(self):
        entities = [_entity("e_loc", "L", EntityKind.LOCATION)]
        shots = [_shot(0), _shot(1, parent_shot_id="s_nope")]

        report = check_continuity(_board(entities, shots,
                                         [_frame("s0", []), _frame("s1", [])]))

        assert any(i.axis == "chain" for i in report.hard)

    def test_lineage_running_backwards_blocks(self):
        entities = [_entity("e_loc", "L", EntityKind.LOCATION)]
        shots = [_shot(0, parent_shot_id="s1"), _shot(1)]

        report = check_continuity(_board(entities, shots,
                                         [_frame("s0", []), _frame("s1", [])]))

        assert any(i.axis == "chain" and "backwards" in i.detail
                   for i in report.hard)

    def test_an_unverifiable_join_only_warns(self):
        """The predecessor never recorded its ending — worth saying, not worth
        blocking a render over."""
        entities = [_entity("e_loc", "L", EntityKind.LOCATION)]
        shots = [_shot(0),
                 _shot(1, parent_shot_id="s0",
                       planned_start_state="he is already inside")]

        report = check_continuity(_board(entities, shots,
                                         [_frame("s0", []), _frame("s1", [])]))

        assert not report.blocked
        assert "chain" in _axes(report, Severity.WARN)


class TestStructure:
    def test_a_board_with_no_shots_blocks(self):
        assert check_continuity(_board([], [], [])).blocked

    def test_duplicate_shot_indexes_block(self):
        entities = [_entity("e_loc", "L", EntityKind.LOCATION)]
        shots = [_shot(0), _shot(0).model_copy(update={"shot_id": "sX"})]

        report = check_continuity(_board(entities, shots, [_frame("s0", [])]))

        assert any(i.axis == "board" for i in report.hard)

    def test_a_shot_with_no_frames_blocks(self):
        entities = [_entity("e_loc", "L", EntityKind.LOCATION)]
        assert check_continuity(_board(entities, [_shot(0)], [])).blocked

    def test_a_moving_shot_missing_its_last_frame_only_warns(self):
        entities = [_entity("e_loc", "L", EntityKind.LOCATION)]
        shots = [_shot(0, movement=Movement.DOLLY_IN)]
        frames = [_frame("s0", [], FrameType.FIRST)]

        report = check_continuity(_board(entities, shots, frames))

        assert not report.blocked
        assert "frames" in _axes(report, Severity.WARN)

    def test_three_identical_camera_setups_in_a_row_warn(self):
        entities = [_entity("e_loc", "L", EntityKind.LOCATION)]
        shots = [_shot(i) for i in range(3)]
        frames = [_frame(f"s{i}", []) for i in range(3)]

        report = check_continuity(_board(entities, shots, frames))

        assert not report.blocked
        assert "camera" in _axes(report, Severity.WARN)

    def test_an_unanchored_place_only_warns(self):
        entities = [_entity("e_minh", "Minh")]
        shots = [_shot(0, cast=["e_minh"], location=None)]

        report = check_continuity(_board(entities, shots, [_frame("s0", [])]))

        assert "location" in _axes(report, Severity.WARN)
