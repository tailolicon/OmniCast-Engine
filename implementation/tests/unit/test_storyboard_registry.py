"""Registry construction — reconcile, merge, persist.

The theme: the LLM proposes and the deterministic layer decides. Each test
below is a way a plausible-looking draft would otherwise reach the image
provider with a cast that does not hold together.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from omnicast.storyboard import store
from omnicast.storyboard.extract import entity_id_for, reconcile_draft
from omnicast.storyboard.merge import apply_merges
from omnicast.storyboard.models import BoardStatus, EntityKind
from omnicast.storyboard.schemas import (
    DraftEntity,
    DraftShot,
    ExtractionDraft,
    MergeProposal,
    MergeResult,
)

SCRIPT = ("Minh parked the van. The driver stepped into the kitchen light. "
          "Lan was already waiting.")


def _reconcile(draft, **kw):
    return reconcile_draft(draft, board_id="b1", channel_id="ch",
                           source_script=SCRIPT, **kw)


class TestReconcile:
    def test_each_kind_survives_as_itself(self):
        """Regression: a case-insensitive coercion that upper-cased everything
        made every costume/location/prop fail to parse and fall back to
        `character`, and the shot pass then re-created each one under its real
        kind — so the registry came out with every entity duplicated."""
        draft = ExtractionDraft(entities=[
            DraftEntity(name="Minh", kind="character"),
            DraftEntity(name="grey coat", kind="costume"),
            DraftEntity(name="the kitchen", kind="location"),
            DraftEntity(name="van keys", kind="prop"),
        ], shots=[DraftShot(index=0, title="t", location_name="the kitchen",
                            character_names=["Minh"],
                            costume_names=["grey coat"],
                            prop_names=["van keys"])])

        board = _reconcile(draft)

        assert {(e.kind, e.name) for e in board.entities} == {
            (EntityKind.CHARACTER, "Minh"),
            (EntityKind.COSTUME, "grey coat"),
            (EntityKind.LOCATION, "the kitchen"),
            (EntityKind.PROP, "van keys"),
        }

    def test_a_shot_referencing_an_undeclared_name_creates_it_and_says_so(self):
        draft = ExtractionDraft(entities=[], shots=[
            DraftShot(index=0, title="t", character_names=["Lan"],
                      location_name="the porch")])

        board = _reconcile(draft)

        assert board.by_name("Lan") is not None
        assert board.by_name("the porch") is not None
        assert any("auto-created" in n for n in board.notes)

    def test_duplicate_spellings_fold_into_one_entity(self):
        draft = ExtractionDraft(entities=[
            DraftEntity(name="Minh", kind="character", description="40s"),
            DraftEntity(name="MINH", kind="character"),
        ], shots=[DraftShot(index=0, title="t", character_names=["Minh"])])

        board = _reconcile(draft)

        assert len([e for e in board.entities
                    if e.kind is EntityKind.CHARACTER]) == 1
        assert board.entities[0].description == "40s"

    def test_verbatim_names_are_never_normalized(self):
        """Folding is for LOOKUP only. Rewriting the stored name would break
        substitution against a prompt that spells it the original way."""
        draft = ExtractionDraft(
            entities=[DraftEntity(name="Bà Tư （già）", kind="character")],
            shots=[DraftShot(index=0, title="t",
                             character_names=["Bà Tư （già）"])])

        board = _reconcile(draft)

        assert board.entities[0].name == "Bà Tư （già）"

    def test_index_gaps_are_closed_and_reported(self):
        draft = ExtractionDraft(entities=[], shots=[
            DraftShot(index=0, title="a"), DraftShot(index=7, title="b")])

        board = _reconcile(draft)

        assert [s.index for s in board.shots] == [0, 1]
        assert any("renumbered" in n for n in board.notes)

    def test_an_unknown_camera_token_falls_back_and_is_reported(self):
        draft = ExtractionDraft(entities=[], shots=[
            DraftShot(index=0, title="a", camera_shot="SUPER_CLOSE")])

        board = _reconcile(draft)

        assert board.shots[0].camera_shot.value == "MS"
        assert any("SUPER_CLOSE" in n for n in board.notes)

    def test_shots_chain_to_their_predecessor(self):
        draft = ExtractionDraft(entities=[], shots=[
            DraftShot(index=0, title="a"), DraftShot(index=1, title="b")])

        board = _reconcile(draft)

        assert board.shots[0].parent_shot_id is None
        assert board.shots[1].parent_shot_id == board.shots[0].shot_id

    def test_ids_are_derived_from_content_so_a_rerun_keeps_approvals(self):
        draft = ExtractionDraft(
            entities=[DraftEntity(name="Minh", kind="character")],
            shots=[DraftShot(index=0, title="t", character_names=["Minh"])])

        first, second = _reconcile(draft), _reconcile(draft)

        assert first.by_name("Minh").entity_id == second.by_name("Minh").entity_id
        assert first.by_name("Minh").entity_id == entity_id_for(
            "b1", EntityKind.CHARACTER, "Minh")

    def test_an_entity_no_shot_uses_is_reported_not_deleted(self):
        draft = ExtractionDraft(
            entities=[DraftEntity(name="ghost", kind="character")],
            shots=[DraftShot(index=0, title="t")])

        board = _reconcile(draft)

        assert board.by_name("ghost") is not None
        assert any("no shot" in n and "ghost" in n for n in board.notes)


@pytest.fixture
def board():
    draft = ExtractionDraft(entities=[
        DraftEntity(name="Minh", kind="character"),
        DraftEntity(name="the driver", kind="character"),
        DraftEntity(name="Lan", kind="character"),
        DraftEntity(name="grey coat", kind="costume"),
    ], shots=[
        DraftShot(index=0, title="a", character_names=["Minh"]),
        DraftShot(index=1, title="b", character_names=["the driver", "Lan"],
                  costume_names=["grey coat"]),
    ])
    return _reconcile(draft)


class TestMerge:
    def test_a_quoted_high_confidence_merge_folds_the_duplicate(self, board):
        result = MergeResult(merges=[MergeProposal(
            canonical_name="Minh", duplicate_names=["the driver"],
            kind="character", confidence=0.95,
            evidence="The driver stepped into the kitchen light.")])

        merged = apply_merges(board, result, source_script=SCRIPT)

        assert merged.by_name("the driver").entity_id == \
            merged.by_name("Minh").entity_id
        assert "the driver" in merged.by_name("Minh").aliases
        assert all(e.name != "the driver" for e in merged.entities)

    def test_the_folded_name_is_rewritten_in_every_shot(self, board):
        result = MergeResult(merges=[MergeProposal(
            canonical_name="Minh", duplicate_names=["the driver"],
            confidence=0.95,
            evidence="The driver stepped into the kitchen light.")])

        merged = apply_merges(board, result, source_script=SCRIPT)
        minh_id = merged.by_name("Minh").entity_id

        assert minh_id in merged.shots[1].entity_ids()
        assert all(e.entity_id != board.by_name("the driver").entity_id
                   for e in merged.entities)

    @pytest.mark.parametrize("proposal,reason", [
        (MergeProposal(canonical_name="Minh", duplicate_names=["Lan"],
                       confidence=0.4, evidence="Lan was already waiting."),
         "below the"),
        (MergeProposal(canonical_name="Minh", duplicate_names=["Lan"],
                       confidence=0.99, evidence="Lan is Minh's alias."),
         "does not occur in the script"),
        (MergeProposal(canonical_name="Minh", duplicate_names=["Lan"],
                       confidence=0.99, evidence=""),
         "no evidence"),
        (MergeProposal(canonical_name="Minh", duplicate_names=["grey coat"],
                       confidence=0.99, evidence="Minh parked the van."),
         "cannot be the same entity"),
    ])
    def test_a_refused_merge_keeps_both_and_records_a_conflict(
            self, board, proposal, reason):
        """A wrong merge deletes a character. Every refusal must survive as
        something a human is forced to look at."""
        merged = apply_merges(board, MergeResult(merges=[proposal]),
                              source_script=SCRIPT)

        for name in [proposal.canonical_name, *proposal.duplicate_names]:
            assert merged.by_name(name) is not None
        flagged = [e for e in merged.entities if e.conflicts]
        assert flagged, "a silent refusal is indistinguishable from agreement"
        assert any(reason in c for e in flagged for c in e.conflicts)

    def test_an_unresolved_conflict_blocks_cast_readiness(self, board):
        merged = apply_merges(board, MergeResult(merges=[MergeProposal(
            canonical_name="Minh", duplicate_names=["Lan"], confidence=0.4,
            evidence="Lan was already waiting.")]), source_script=SCRIPT)

        assert not merged.cast_ready

    def test_an_empty_result_changes_nothing(self, board):
        merged = apply_merges(board, MergeResult(), source_script=SCRIPT)

        assert {e.entity_id for e in merged.entities} == \
            {e.entity_id for e in board.entities}


class TestStore:
    def test_a_board_survives_a_round_trip(self, board):
        db = Path(tempfile.mkdtemp()) / "vault.db"
        parked = board.model_copy(update={"status": BoardStatus.CAST_PENDING,
                                          "style_prompt": "16mm grain"})

        store.save_board(parked, db)
        back = store.load_board(board.board_id, db)

        assert back is not None
        assert back.status is BoardStatus.CAST_PENDING
        assert back.style_prompt == "16mm grain"
        assert {e.name for e in back.entities} == {e.name for e in board.entities}
        assert [s.index for s in back.shots] == [s.index for s in board.shots]
        assert back.shots[1].entity_ids() == board.shots[1].entity_ids()

    def test_saving_twice_replaces_rather_than_duplicates(self, board):
        db = Path(tempfile.mkdtemp()) / "vault.db"
        store.save_board(board, db)
        store.save_board(board, db)

        back = store.load_board(board.board_id, db)
        assert len(back.entities) == len(board.entities)
        assert len(store.list_boards(path=db)) == 1

    def test_the_same_script_resolves_to_the_same_board(self, board):
        db = Path(tempfile.mkdtemp()) / "vault.db"
        store.save_board(board, db)

        found = store.find_board_by_script("ch", board.script_hash, db)

        assert found == board.board_id

    def test_a_missing_board_reads_as_none(self):
        db = Path(tempfile.mkdtemp()) / "vault.db"
        assert store.load_board("nope", db) is None
