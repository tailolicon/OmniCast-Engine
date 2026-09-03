"""Reference binding — the contract that makes an attached image mean something.

Every test here pins a way the binding can silently produce a plausible prompt
that points at the wrong picture. Silently is the operative word: none of these
raise, and all of them ship a video with the wrong face in it.
"""

from __future__ import annotations

import pytest

from omnicast.storyboard import binding
from omnicast.storyboard.models import (
    CameraShot,
    Entity,
    EntityImage,
    EntityKind,
    ImageSource,
    Movement,
    RefRole,
    Shot,
    ShotEntityRef,
    Storyboard,
)


def _img(entity_id: str, path: str, *, role=RefRole.IDENTITY, approved=True,
         source=ImageSource.GENERATED, view="front") -> EntityImage:
    return EntityImage(image_id=f"{entity_id}_{view}", entity_id=entity_id,
                       path=path, view=view, role=role, approved=approved,
                       source=source)


def _entity(entity_id: str, name: str, kind=EntityKind.CHARACTER, *,
            aliases=None, images=None, **kw) -> Entity:
    return Entity(entity_id=entity_id, board_id="b", kind=kind, name=name,
                  aliases=aliases or [], images=images or [], **kw)


@pytest.fixture
def board() -> Storyboard:
    entities = [
        _entity("e_minh", "Minh", aliases=["the driver"],
                images=[_img("e_minh", "/r/minh.png")]),
        _entity("e_minhanh", "Minh Anh",
                images=[_img("e_minhanh", "/r/minhanh.png")]),
        _entity("e_kitchen", "the kitchen", EntityKind.LOCATION,
                images=[_img("e_kitchen", "/r/kitchen.png",
                             role=RefRole.ENVIRONMENT, view="establishing")]),
        _entity("e_ledger", "the ledger", EntityKind.PROP,
                images=[_img("e_ledger", "/r/ledger.png", role=RefRole.PROP)]),
    ]
    shot = Shot(shot_id="s1", board_id="b", index=0, location_id="e_kitchen",
                cast=[ShotEntityRef(entity_id="e_minh", index=0),
                      ShotEntityRef(entity_id="e_minhanh", index=1),
                      ShotEntityRef(entity_id="e_ledger", index=2)],
                camera_shot=CameraShot.MS, movement=Movement.STATIC)
    return Storyboard(board_id="b", channel_id="ch", entities=entities,
                      shots=[shot])


def test_longer_name_is_substituted_before_the_name_it_contains(board):
    """"Minh" replacing first would leave "[IMAGE 1] Anh" — a phantom person."""
    maps, _ = binding.build_mappings(board.shots[0], board)
    out = binding.bind_prompt("Minh Anh looks at Minh", maps, board)

    assert "Anh" not in out
    minh = next(m for m in maps if m.name == "Minh")
    minh_anh = next(m for m in maps if m.name == "Minh Anh")
    assert out == f"{minh_anh.token} looks at {minh.token}"


def test_an_alias_binds_to_the_same_token_as_the_canonical_name(board):
    maps, _ = binding.build_mappings(board.shots[0], board)
    minh = next(m for m in maps if m.name == "Minh")
    assert binding.bind_prompt("the driver waits", maps, board) == \
        f"{minh.token} waits"


def test_an_unmapped_longer_name_is_left_intact(board):
    """Regression. With only Minh bound, "Minh Anh" must survive whole.

    The first implementation sorted only the MAPPED spellings, so the shorter
    bound name ate the front of the longer unbound one and the prompt shipped
    "[IMAGE 1] Anh" — a phantom character, and one the unbound-name check could
    no longer recognise well enough to report.
    """
    shot = board.shots[0].model_copy(update={
        "cast": [ShotEntityRef(entity_id="e_minh", index=0)],
        "location_id": None})
    b = board.model_copy(update={"shots": [shot]})
    maps, _ = binding.build_mappings(shot, b)

    out = binding.bind_prompt("Minh looks at Minh Anh", maps, b)

    assert out == "[IMAGE 1] looks at Minh Anh"
    assert "[IMAGE 1] Anh" not in out


def test_a_name_inside_a_longer_word_is_not_substituted(board):
    """Word boundaries: "Minhang" is a place, not a token slot."""
    maps, _ = binding.build_mappings(board.shots[0], board)
    assert "Minhang" in binding.bind_prompt("Minhang district", maps, board)


def test_every_reference_row_states_what_must_not_transfer(board):
    """An identity portrait that does not say 'ignore its background' donates
    its background."""
    maps, _ = binding.build_mappings(board.shots[0], board)
    table = binding.reference_table(maps)

    assert "controls identity ONLY" in table
    assert "ignore background" in table
    kitchen = next(m for m in maps if m.kind is EntityKind.LOCATION)
    assert f"{kitchen.token} = the kitchen (location)" in table
    assert "controls environment ONLY" in table
    assert "any person" in table


def test_operator_images_outrank_generated_ones(board):
    """A human uploaded a face; a later generation pass must not outvote it."""
    entity = board.entity("e_minh")
    both = entity.model_copy(update={"images": [
        _img("e_minh", "/r/generated.png", source=ImageSource.GENERATED),
        _img("e_minh", "/r/operator.png", source=ImageSource.OPERATOR,
             view="operator"),
    ]})
    b = board.model_copy(update={
        "entities": [both if e.entity_id == "e_minh" else e
                     for e in board.entities]})

    maps, _ = binding.build_mappings(b.shots[0], b)
    assert next(m for m in maps if m.name == "Minh").path == "/r/operator.png"


def test_an_entity_without_an_approved_image_is_dropped_and_named(board):
    unapproved = board.entity("e_minh").model_copy(update={
        "images": [_img("e_minh", "/r/minh.png", approved=False)]})
    b = board.model_copy(update={
        "entities": [unapproved if e.entity_id == "e_minh" else e
                     for e in board.entities]})

    maps, dropped = binding.build_mappings(b.shots[0], b)

    assert all(m.entity_id != "e_minh" for m in maps)
    assert any("Minh" in d and "no approved reference image" in d for d in dropped)


def test_the_reference_cap_spends_itself_on_faces_and_reports_the_rest(board):
    """Characters outrank props: a two-image budget buys the two people."""
    maps, dropped = binding.build_mappings(board.shots[0], board, max_refs=2)

    assert [m.kind for m in maps] == [EntityKind.CHARACTER, EntityKind.CHARACTER]
    assert dropped, "a silent cap reads downstream as 'we had no reference'"
    assert any("cap" in d for d in dropped)


def test_tokens_are_numbered_from_one_in_attachment_order(board):
    maps, _ = binding.build_mappings(board.shots[0], board)
    assert [m.token for m in maps][:3] == ["[IMAGE 1]", "[IMAGE 2]", "[IMAGE 3]"]


class TestBindingIssues:
    def test_a_token_with_no_image_behind_it_is_reported(self, board):
        maps, _ = binding.build_mappings(board.shots[0], board)
        rendered = binding.compose_rendered_prompt(
            base_prompt="Minh in [IMAGE 9]", mappings=maps, board=board)

        issues = binding.binding_issues(rendered_prompt=rendered,
                                        mappings=maps, board=board)
        assert any("[IMAGE 9]" in i and "points at nothing" in i for i in issues)

    def test_an_attached_image_no_sentence_uses_is_reported(self, board):
        maps, _ = binding.build_mappings(board.shots[0], board)
        rendered = binding.compose_rendered_prompt(
            base_prompt="Minh alone.", mappings=maps, board=board)

        issues = binding.binding_issues(rendered_prompt=rendered,
                                        mappings=maps, board=board)
        assert any("never referenced in the scene text" in i for i in issues)

    def test_an_unbound_cast_name_is_reported(self, board):
        """The model reads the name, invents that person, and ships the face."""
        shot = board.shots[0].model_copy(update={
            "cast": [ShotEntityRef(entity_id="e_minh", index=0)],
            "location_id": None})
        b = board.model_copy(update={"shots": [shot]})
        maps, _ = binding.build_mappings(shot, b)

        rendered = binding.compose_rendered_prompt(
            base_prompt="Minh looks at Minh Anh", mappings=maps, board=b)
        issues = binding.binding_issues(rendered_prompt=rendered,
                                        mappings=maps, board=b)

        assert any("Minh Anh" in i and "invent" in i for i in issues)

    def test_a_sound_binding_reports_nothing(self, board):
        maps, _ = binding.build_mappings(board.shots[0], board)
        rendered = binding.compose_rendered_prompt(
            base_prompt="Minh and Minh Anh hold the ledger in the kitchen",
            mappings=maps, board=board)

        assert binding.binding_issues(rendered_prompt=rendered, mappings=maps,
                                      board=board) == []


def test_the_reference_table_precedes_the_scene_text(board):
    """The model must know what a token means before it reads a sentence
    containing it."""
    maps, _ = binding.build_mappings(board.shots[0], board)
    rendered = binding.compose_rendered_prompt(
        base_prompt="Minh waits", mappings=maps, style_prompt="16mm grain",
        board=board)

    assert rendered.index("## REFERENCE IMAGES") < rendered.index("## SCENE")
    assert rendered.index("## SCENE") < rendered.index("## STYLE")
