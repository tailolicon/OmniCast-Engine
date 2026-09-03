"""One idempotent run of the competitor-craft learning chain.

Until now this chain lived in throwaway scripts: label the corpus, match pairs,
parse captions, grade the evidence, compile a playbook, decide whether the
writer may see it. Analysis that only exists as a sequence of ad-hoc commands
cannot be re-run after new data lands, cannot be audited for what it did, and
quietly drifts from what the tests cover.

    label_corpus → match_pairs → analyse VTT → compare_cohort
        → compile playbook → GATE → vault

The gate is the point of the module: a playbook is published to the writer only
when the cohort can carry it. Otherwise the run still produces the artifact and
the report — for a human to read — and says why it was not published.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from omnicast.analytics.cohort_labels import (
    cohort_report,
    label_corpus,
    match_pairs,
)
from omnicast.analytics.craft_forensics import analyse_vtt, compare_cohort
from omnicast.analytics.craft_playbook import (
    compile_craft_playbook,
    compile_writer_playbook,
)

PLAYBOOK_MARKER = "=== MEASURED CRAFT (caption forensics, cohort-derived) ==="

# Publication thresholds. A playbook that reaches the writer influences every
# script; it must rest on more than one channel's habits.
MIN_CHANNELS_FOR_PUBLICATION = 3
MIN_PAIRS_FOR_PUBLICATION = 10


@dataclass
class CraftRunReport:
    channel_id: str
    corpus_videos: int = 0
    captions_on_disk: int = 0
    measured_videos: int = 0
    winners: int = 0
    controls: int = 0
    matched_pairs: int = 0            # pairs the labeller built (all formats)
    matched_pairs_measured: int = 0   # pairs where BOTH sides were actually measured
    channels_compared: int = 0
    snapshot_at: str = ""
    run_id: str = ""
    provenance: dict = field(default_factory=dict)
    rules: list[str] = field(default_factory=list)
    hypotheses: list[str] = field(default_factory=list)
    published: bool = False
    publish_reason: str = ""
    artifacts: dict = field(default_factory=dict)
    pair_quality: dict = field(default_factory=dict)


def run_craft_learning(channel_id: str, root: Path, *,
                       publish: bool = True,
                       min_words: int = 200) -> CraftRunReport:
    """Run the chain end to end. Safe to re-run: every step is derived from
    files on disk, and publication is decided fresh each time."""
    res = root / "output" / "research" / channel_id
    raw_file = res / "raw_videos.json"
    if not raw_file.exists():
        return CraftRunReport(channel_id=channel_id,
                              publish_reason="no raw_videos.json — run discovery first")

    raw = json.loads(raw_file.read_text(encoding="utf-8"))

    # FROZEN SNAPSHOT. `views` in raw_videos.json is a moment in time, but
    # `age_days` was computed from datetime.now() — so the same corpus produced
    # 34 pairs at noon and 35 at midnight with no new data. A run is only
    # reproducible if the clock is part of the snapshot.
    snap_file = res / "corpus_snapshot.json"
    if snap_file.exists():
        snapshot_at = datetime.fromisoformat(
            json.loads(snap_file.read_text(encoding="utf-8"))["snapshot_at"])
    else:
        snapshot_at = datetime.now(timezone.utc)
        snap_file.write_text(json.dumps(
            {"snapshot_at": snapshot_at.isoformat(),
             "raw_videos_sha256": hashlib.sha256(
                 raw_file.read_bytes()).hexdigest(),
             "note": "frozen so every rerun labels the corpus identically"},
            indent=1), encoding="utf-8")
    run_id = hashlib.sha256(
        f"{snapshot_at.isoformat()}|{raw_file.stat().st_size}".encode()
    ).hexdigest()[:12]

    labelled = label_corpus(raw, now=snapshot_at)
    pair_report: dict = {}
    match_pairs(labelled, report=pair_report)
    by_id = {v.video_id: v for v in labelled}

    vtt_dir = res / "_vtt_corpus"
    vtts = sorted(vtt_dir.glob("*.vtt")) if vtt_dir.exists() else []
    crafts = []
    for vtt in vtts:
        meta = by_id.get(vtt.name.split(".")[0])
        if meta is None or meta.fmt != "long":
            continue
        c = analyse_vtt(vtt, video_id=meta.video_id, role=meta.role,
                        channel=meta.channel,
                        matched_control=meta.matched_control)
        if c.words > min_words:
            crafts.append(c)

    measured_ids = {c.video_id for c in crafts}
    pairs_measured = sum(
        1 for c in crafts
        if c.role == "winner" and c.matched_control
        and c.matched_control in measured_ids)

    cohort = compare_cohort(crafts)
    cohort_rep = cohort_report(labelled)
    forensics = {"videos": [c.__dict__ for c in crafts], "cohort": cohort,
                 "cohort_report": cohort_rep, "pair_report": pair_report}
    research_report = compile_craft_playbook(forensics)
    playbook = compile_writer_playbook(forensics)

    # THE GENRE FLOOR IS RESEARCH, AND IT STAYS OUT OF THE PRODUCTION ARTIFACT.
    #
    # An earlier version of this appended the hand-written floor to the
    # playbook with a header saying it was qualitative and untested. That is
    # not containment. The Writer is handed `script_playbook` as instructions;
    # a section that opens "what EVERY video in this niche does" will be
    # obeyed, and a provenance field the Writer never reads cannot stop it.
    # The whole point of the grading machinery is that untested observations
    # do not reach generation by accident.
    #
    # So the file is recorded — path, hash, grade — and the operator may quote
    # it deliberately in a steering brief, which is a channel where a human is
    # accountable for the claim. It is never merged into the intel the vault
    # publishes.
    floor_path = res / "genre_floor.md"
    genre_floor = (floor_path.read_text(encoding="utf-8")
                   if floor_path.exists() else "")

    report = CraftRunReport(
        channel_id=channel_id,
        corpus_videos=sum(len(v) for v in raw.values()),
        captions_on_disk=len(vtts),
        measured_videos=len(crafts),
        winners=sum(1 for c in crafts if c.role == "winner"),
        controls=sum(1 for c in crafts if c.role == "control"),
        matched_pairs=cohort_rep.get("matched_pairs", 0),
        matched_pairs_measured=pairs_measured,
        snapshot_at=snapshot_at.isoformat(),
        run_id=run_id,
        channels_compared=max(
            (m.get("channels_compared", 0) for m in cohort["metrics"].values()),
            default=0),
        rules=[k for k, m in cohort["metrics"].items()
               if m.get("evidence_grade") == "rule"],
        hypotheses=[k for k, m in cohort["metrics"].items()
                    if m.get("evidence_grade") == "hypothesis"],
        pair_quality=cohort_rep.get("pair_quality", {}),
    )

    f_path = res / "craft_forensics_current.json"
    p_path = res / "craft_playbook_current.md"
    research_path = res / "craft_research_report_current.md"
    f_path.write_text(json.dumps(forensics, ensure_ascii=False, indent=1),
                      encoding="utf-8")
    p_path.write_text(playbook, encoding="utf-8")
    research_path.write_text(research_report, encoding="utf-8")
    report.artifacts = {
        "forensics": str(f_path),
        "playbook": str(p_path),
        "research_report": str(research_path),
    }

    # GATE ON WHAT WAS ACTUALLY TESTED. `matched_pairs` counts every pair the
    # labeller built — including Shorts pairs that the craft analysis never
    # touches. The gate must count pairs whose BOTH sides carry a measured
    # transcript, or it certifies a sample size that did not participate.
    ok = (report.channels_compared >= MIN_CHANNELS_FOR_PUBLICATION
          and report.matched_pairs_measured >= MIN_PAIRS_FOR_PUBLICATION)
    if not ok:
        report.publish_reason = (
            f"NOT published: {report.channels_compared}/"
            f"{MIN_CHANNELS_FOR_PUBLICATION} channels compared, "
            f"{report.matched_pairs_measured}/{MIN_PAIRS_FOR_PUBLICATION} "
            f"measured long-form pairs (labeller built "
            f"{report.matched_pairs} pairs across all formats)")
    elif not publish:
        report.publish_reason = "publish=False (dry run)"
    else:
        provenance = {
            "source": "craft_pipeline",
            "research_run_id": run_id,
            "generated_at": snapshot_at.isoformat(),
            "snapshot_at": snapshot_at.isoformat(),
            "is_comparable": True,
            "comparability": "matched_pairs",
            "channels_compared": report.channels_compared,
            "matched_pairs_measured": report.matched_pairs_measured,
            "winner_count": report.winners,
            "control_count": report.controls,
            "rules": report.rules,
            "hypotheses": report.hypotheses,
            "artifact_path": str(p_path),
            "artifact_sha256": hashlib.sha256(
                playbook.encode("utf-8")).hexdigest(),
            # Recorded, NOT shipped. `production_eligible` is the field that
            # does the work: it says this text is not in the artifact above and
            # must not be pasted into it later.
            "genre_floor": ({
                "source": "notebooklm_manual_session",
                "path": str(floor_path),
                "sha256": hashlib.sha256(
                    genre_floor.encode("utf-8")).hexdigest(),
                "evidence_grade": "qualitative_untested",
                "has_control_group": False,
                "production_eligible": False,
            } if genre_floor else None),
        }
        n = _write_playbook_to_vault(channel_id, playbook, root, provenance)
        report.published = True
        report.publish_reason = f"published to {n} vault scope row(s)"
        report.provenance = provenance

    (res / "craft_run_report.json").write_text(
        json.dumps(asdict(report), ensure_ascii=False, indent=1), encoding="utf-8")
    return report


def _write_playbook_to_vault(channel_id: str, playbook: str, root: Path,
                             provenance: dict) -> int:
    """Publish the craft block AND its provenance, together, through the vault
    contract.

    An earlier version ran a bare `UPDATE ... SET script_playbook = ?`. The
    text changed; `cohort_meta` did not. So new text sat under an older run's
    `research_run_id`, `generated_at` and `is_comparable` — and `intel_gate`,
    which reads provenance to decide whether a playbook may be used, approved
    the new text on another artifact's credentials. The vault module already
    documents this exact failure (`_merge_run`: "an artifact and its provenance
    move TOGETHER"); the pipeline was bypassing it.
    """
    db_path = root / "output" / "vault.db"
    if not db_path.exists():
        return 0
    from omnicast.vault import db as _vdb

    block = f"{PLAYBOOK_MARKER}\n{playbook}\n"
    db = sqlite3.connect(db_path)
    try:
        niches = [r[0] for r in db.execute(
            "select niche from competitor_intel where niche like ?",
            (f"%{channel_id}%",)).fetchall()]
    finally:
        db.close()

    written = 0
    for niche in niches:
        intel = _vdb.get_competitor_intel(niche, db_path)
        if intel is None:
            continue
        # ``cohort_meta.artifacts.script_playbook`` contains exactly one
        # provenance record, so ``script_playbook`` must contain exactly that
        # artifact. Preserving old learner prose above the marker launders it
        # under this measured run's credentials and the gate approves both.
        intel.script_playbook = block

        # PROVENANCE TRAVELS WITH THE TEXT. The craft block is a different
        # artifact from the learner's title/thumbnail playbooks, so it carries
        # its own run record inside cohort_meta rather than inheriting theirs.
        try:
            meta = json.loads(getattr(intel, "cohort_meta", "") or "{}")
        except Exception:
            meta = {}
        meta.setdefault("artifacts", {})["script_playbook"] = provenance
        intel.cohort_meta = json.dumps(meta, ensure_ascii=False)
        intel.updated_at = provenance["generated_at"]
        _vdb.upsert_competitor_intel(intel, db_path)
        written += 1

    if written:
        # The writer caches intel for 60s; without this a script generated
        # right after a learning run still uses the superseded playbook.
        try:
            from omnicast.agents.writer import invalidate_competitor_intel_cache

            invalidate_competitor_intel_cache()
        except Exception:
            pass
    return written
