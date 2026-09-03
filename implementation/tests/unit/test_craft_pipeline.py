"""The learning chain as one idempotent unit.

Before this module the chain existed only as a sequence of ad-hoc scripts:
nothing re-ran it when new captions landed, nothing recorded what it did, and
the publication decision lived in whoever was typing. These tests pin the
chain and — more importantly — the gate that stands between a thin cohort and
the writer's prompt.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from omnicast.analytics.craft_pipeline import PLAYBOOK_MARKER, run_craft_learning

NOW = datetime.now(timezone.utc)

VTT_TEMPLATE = """WEBVTT

00:00:00.000 --> 00:00:06.000
So you might be wondering about this {word} and what it means for you.

00:00:30.000 --> 00:00:36.000
The IRS just released a report and {word} is the number that matters here.

00:02:00.000 --> 00:02:08.000
Now the second thing to know is that {word} costs about $2,040 a month today.

00:04:00.000 --> 00:04:09.000
Let me show you how to work out your own {word} number before the deadline.
"""


def _seed(root: Path, channel: str = "ch1", *, channels: int = 3,
          per_channel: int = 6) -> None:
    res = root / "output" / "research" / channel
    (res / "_vtt_corpus").mkdir(parents=True, exist_ok=True)
    raw: dict[str, list[dict]] = {}
    for c in range(channels):
        handle = f"@chan{c}"
        items = []
        for i in range(per_channel):
            vid = f"c{c}v{i}"
            fast = i < per_channel // 2
            items.append({
                "video_id": vid,
                "title": f"Video {vid}",
                "views": 90_000 if fast else 4_000,
                "duration_minutes": 12.0,
                "published_at": (NOW - timedelta(days=100 + i)).isoformat(),
            })
            (res / "_vtt_corpus" / f"{vid}.en.vtt").write_text(
                VTT_TEMPLATE.format(word=("faster" if fast else "slower") * 40),
                encoding="utf-8")
        raw[handle] = items
    (res / "raw_videos.json").write_text(json.dumps(raw), encoding="utf-8")


def _seed_vault(root: Path, playbook: str, *, cohort_meta: str = "") -> Path:
    """Real vault schema + one intel row. The pipeline publishes through the
    vault contract, so a hand-rolled two-column table is not a valid stand-in."""
    from omnicast.vault import db as vdb

    db_path = root / "output" / "vault.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    vdb.init_db(db_path)
    con = sqlite3.connect(db_path)
    con.execute(
        "insert into competitor_intel (niche, title_playbook, "
        "thumbnail_playbook, script_playbook, sample_titles, sample_count, "
        "cohort_meta, updated_at) values (?,?,?,?,?,?,?,?)",
        ("finance|ch1|*|*|us", "T", "TH", playbook, "[]", 0,
         cohort_meta or json.dumps({"research_run_id": "OLD_RUN",
                                    "generated_at": "2026-01-01T00:00:00+00:00",
                                    "is_comparable": False}), "2026-01-01"))
    con.commit(); con.close()
    return db_path


def test_chain_runs_end_to_end_and_records_what_it_did(tmp_path):
    _seed(tmp_path)
    rep = run_craft_learning("ch1", tmp_path, publish=False, min_words=20)
    assert rep.corpus_videos == 18
    assert rep.measured_videos > 0
    assert rep.winners and rep.controls
    assert Path(rep.artifacts["forensics"]).exists()
    assert Path(rep.artifacts["playbook"]).exists()
    saved = json.loads((tmp_path / "output" / "research" / "ch1"
                        / "craft_run_report.json").read_text(encoding="utf-8"))
    assert saved["measured_videos"] == rep.measured_videos


def test_thin_cohort_is_never_published(tmp_path):
    """One channel cannot speak for a niche."""
    _seed(tmp_path, channels=1, per_channel=6)
    rep = run_craft_learning("ch1", tmp_path, publish=True, min_words=20)
    assert rep.published is False
    assert "NOT published" in rep.publish_reason


def test_publication_writes_the_playbook_into_the_vault(tmp_path):
    _seed(tmp_path, channels=4, per_channel=8)
    db_path = _seed_vault(tmp_path, "EXISTING PROSE")

    rep = run_craft_learning("ch1", tmp_path, publish=True, min_words=20)
    assert rep.published is True, rep.publish_reason

    db = sqlite3.connect(db_path)
    pb, meta = db.execute(
        "select script_playbook, cohort_meta from competitor_intel").fetchone()
    db.close()
    # One text artifact gets one provenance record. Preserving old prose here
    # would let unrelated/untested instructions ride under this run's measured
    # credentials.
    assert not pb.startswith("EXISTING PROSE")
    assert pb.startswith(PLAYBOOK_MARKER)
    assert "PRODUCTION-ELIGIBLE" in pb

    # PROVENANCE MOVES WITH THE TEXT. A bare UPDATE left new text sitting under
    # an older run's id and comparability, so the gate could approve it on
    # another artifact's credentials.
    prov = json.loads(meta)["artifacts"]["script_playbook"]
    assert prov["research_run_id"] == rep.run_id
    assert prov["research_run_id"] != "OLD_RUN"
    assert prov["snapshot_at"] == rep.snapshot_at
    assert prov["matched_pairs_measured"] == rep.matched_pairs_measured
    assert prov["artifact_sha256"]


def test_rerunning_replaces_the_block_instead_of_stacking(tmp_path):
    """Idempotence: two runs must not leave two craft blocks."""
    _seed(tmp_path, channels=4, per_channel=8)
    db_path = _seed_vault(tmp_path, "BASE")

    run_craft_learning("ch1", tmp_path, publish=True, min_words=20)
    run_craft_learning("ch1", tmp_path, publish=True, min_words=20)

    db = sqlite3.connect(db_path)
    pb = db.execute("select script_playbook from competitor_intel").fetchone()[0]
    db.close()
    assert pb.count(PLAYBOOK_MARKER) == 1
    assert not pb.startswith("BASE")


def test_unmeasured_genre_floor_is_advisory_only_not_writer_input(tmp_path):
    """A warning label is not containment.

    The Writer receives the whole script_playbook as instructions. Appending a
    hand-written "EVERY video does this" floor makes the model follow it even
    when provenance calls it qualitative_untested. Preserve the candidate and
    its provenance for research, but do not put it in the production artifact
    or the vault row that the Writer consumes.
    """
    _seed(tmp_path, channels=4, per_channel=8)
    db_path = _seed_vault(tmp_path, "BASE")
    res = tmp_path / "output" / "research" / "ch1"
    res.mkdir(parents=True, exist_ok=True)
    (res / "genre_floor.md").write_text(
        "── GENRE FLOOR ──\n  1. REFUSE TO WORSHIP THE MATH.\n",
        encoding="utf-8")

    rep = run_craft_learning("ch1", tmp_path, publish=True, min_words=20)
    assert rep.published, rep.publish_reason
    text = (res / "craft_playbook_current.md").read_text(encoding="utf-8")
    assert "GENRE FLOOR" not in text

    db = sqlite3.connect(db_path)
    published = db.execute(
        "select script_playbook from competitor_intel").fetchone()[0]
    db.close()
    assert "GENRE FLOOR" not in published

    floor = rep.provenance["genre_floor"]
    assert floor["evidence_grade"] == "qualitative_untested"
    assert floor["has_control_group"] is False
    assert floor["sha256"]
    assert floor["production_eligible"] is False


def test_no_genre_floor_file_is_simply_absent(tmp_path):
    _seed(tmp_path, channels=4, per_channel=8)
    _seed_vault(tmp_path, "BASE")
    rep = run_craft_learning("ch1", tmp_path, publish=True, min_words=20)
    assert rep.provenance["genre_floor"] is None


def test_missing_corpus_is_reported_not_crashed(tmp_path):
    rep = run_craft_learning("nope", tmp_path, publish=True)
    assert rep.published is False
    assert "run discovery first" in rep.publish_reason


def test_snapshot_is_frozen_so_reruns_label_identically(tmp_path):
    """`views` are a frozen snapshot but age was read from the wall clock, so
    the same corpus produced 34 pairs at noon and 35 at midnight."""
    _seed(tmp_path, channels=3, per_channel=6)
    first = run_craft_learning("ch1", tmp_path, publish=False, min_words=20)
    snap = json.loads((tmp_path / "output" / "research" / "ch1"
                       / "corpus_snapshot.json").read_text(encoding="utf-8"))
    assert snap["snapshot_at"] == first.snapshot_at
    assert snap["raw_videos_sha256"]

    second = run_craft_learning("ch1", tmp_path, publish=False, min_words=20)
    assert second.snapshot_at == first.snapshot_at
    assert second.run_id == first.run_id
    assert second.matched_pairs == first.matched_pairs
    assert second.matched_pairs_measured == first.matched_pairs_measured


def test_gate_counts_measured_pairs_not_labelled_pairs(tmp_path):
    """The labeller also pairs Shorts, which the craft analysis never reads.
    Gating on that number certifies a sample that did not participate."""
    _seed(tmp_path, channels=3, per_channel=6)
    res = tmp_path / "output" / "research" / "ch1"
    # delete every control caption: pairs still exist, measured pairs collapse
    raw = json.loads((res / "raw_videos.json").read_text(encoding="utf-8"))
    for items in raw.values():
        for v in items[len(items) // 2:]:
            for f in (res / "_vtt_corpus").glob(f"{v['video_id']}*.vtt"):
                f.unlink()

    rep = run_craft_learning("ch1", tmp_path, publish=True, min_words=20)
    assert rep.matched_pairs_measured < rep.matched_pairs
    assert rep.published is False
    assert "measured long-form pairs" in rep.publish_reason
