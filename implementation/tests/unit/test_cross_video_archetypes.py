"""Cross-VIDEO archetype fingerprint (craft campaign P7).

The within-video no-two-share gate cannot see prior videos; a channel that
publishes the same threat/escape archetype every week reads as one generator.
This records the typed archetypes per released compilation and feeds them
forward so the next planner varies the lineup. Backward-compatible: channels
that pass no archetypes keep the exact old fingerprint shape."""

from __future__ import annotations

import json

from omnicast.agents import cross_video as xv


def test_fingerprint_without_archetypes_is_unchanged():
    fp = xv.fingerprint("A quiet night. Denise checked the lock. Denise left.")
    assert "archetypes" not in fp  # old shape preserved exactly
    assert set(fp) == {"names", "motifs"}


def test_fingerprint_records_archetypes_when_supplied():
    fp = xv.fingerprint(
        "text",
        archetypes=["lone_stranger/barricade_in_place", "group/flee_to_occupied_place"],
    )
    assert fp["archetypes"] == [
        "group/flee_to_occupied_place", "lone_stranger/barricade_in_place",
    ]


def test_recent_archetypes_feeds_forward_from_history(tmp_path):
    store = tmp_path / "fp.json"
    xv.record("ch", xv.fingerprint("t1", archetypes=["lone_stranger/barricade_in_place"]), store)
    xv.record("ch", xv.fingerprint("t2", archetypes=["lone_stranger/vehicle_escape"]), store)
    recent = xv.recent_archetypes("ch", store)
    assert "lone_stranger/barricade_in_place" in recent
    assert "lone_stranger/vehicle_escape" in recent


def test_recent_archetypes_empty_for_unknown_channel(tmp_path):
    assert xv.recent_archetypes("nobody", tmp_path / "fp.json") == []


def test_check_and_record_persists_archetypes(tmp_path):
    store = tmp_path / "fp.json"
    xv.check_and_record("ch", "Denise walked home. Denise slept.",
                        store, archetypes=["known_regular/call_for_help"])
    data = json.loads(store.read_text(encoding="utf-8"))
    assert data["ch"][-1]["archetypes"] == ["known_regular/call_for_help"]


def test_old_records_without_archetypes_do_not_crash_recent(tmp_path):
    store = tmp_path / "fp.json"
    store.write_text(json.dumps({"ch": [{"names": ["Denise"], "motifs": []}]}), encoding="utf-8")
    assert xv.recent_archetypes("ch", store) == []  # missing key tolerated
