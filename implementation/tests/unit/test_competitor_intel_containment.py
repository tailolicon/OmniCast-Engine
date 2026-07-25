"""Containment fixes for the competitor-intel pipeline (P0.1 group 1).

Three defects, all of the same family — something expensive or something wrong
happening quietly:

  1. `learn_for_channel` is awaited from inside the FastAPI app, but it ran
     caption downloads, yt-dlp, Whisper, ten thumbnail downloads and two
     synchronous vision SDKs directly on the event loop. One caption-less video
     could freeze every other request on the worker for minutes.
  2. The vault upsert kept the OLD script playbook when a run produced none, but
     replaced `cohort_meta` with the NEW run's provenance — so a playbook
     learned with no control group could later read as verified.
  3. Nothing recorded which research run produced which artifact.
"""

from __future__ import annotations

import asyncio
import json
import time

from omnicast.analytics import competitor_intel as ci
from omnicast.analytics.transcript import Transcript


class _Row:
    """Stand-in for a vault CompetitorIntel row."""

    def __init__(self, **kw):
        self.title_playbook = kw.get("title_playbook", "")
        self.thumbnail_playbook = kw.get("thumbnail_playbook", "")
        self.script_playbook = kw.get("script_playbook", "")
        self.cohort_meta = kw.get("cohort_meta", "")
        self.updated_at = kw.get("updated_at", "")


# ── 1. The event loop stays free ─────────────────────────────────────────────

async def _loop_ticks_while(coro) -> tuple[object, int]:
    """Run `coro` and count how many times the event loop got a turn.

    A blocking call inside a coroutine starves this counter; a properly
    off-loaded one does not."""
    ticks = 0
    task = asyncio.ensure_future(coro)
    while not task.done():
        await asyncio.sleep(0.001)
        ticks += 1
    return task.result(), ticks


async def test_transcript_fetch_does_not_block_the_event_loop(monkeypatch):
    def _slow(video_id, duration_minutes=0.0):
        time.sleep(0.15)          # stands in for yt-dlp + Whisper
        return Transcript(video_id=video_id, text="words", source="asr")

    monkeypatch.setattr(ci, "_fetch_transcript", _slow)
    result, ticks = await _loop_ticks_while(ci._fetch_transcript_async("v1", 10.0))
    assert result.source == "asr"
    assert ticks > 10, "event loop was starved during the transcript fetch"


async def test_thumbnail_learning_does_not_block_the_event_loop(monkeypatch):
    def _slow(cohort, by_id, **kwargs):
        time.sleep(0.15)          # stands in for 10 downloads + a vision SDK
        return "THUMB PLAYBOOK"

    monkeypatch.setattr(ci, "_learn_thumbnails", _slow)
    result, ticks = await _loop_ticks_while(ci._learn_thumbnails_async(None, {}))
    assert result == "THUMB PLAYBOOK"
    assert ticks > 10, "event loop was starved during thumbnail analysis"


async def test_blocking_entry_points_are_documented_as_blocking():
    """The sync functions stay callable from scripts — but a future caller has
    to be told which door they are opening."""
    assert "BLOCKING" in (ci._fetch_transcript.__doc__ or "")
    assert "BLOCKING" in (ci._learn_thumbnails.__doc__ or "")


# ── 2 & 3. An artifact and its provenance move together ──────────────────────

RUN = {"research_run_id": "run_new", "generated_at": "2026-07-25T00:00:00+00:00",
       "is_comparable": True, "winner_count": 8, "control_count": 8}


def test_every_artifact_this_run_made_carries_this_run_id():
    artifacts, meta = ci._merge_run(
        None, {"title_playbook": "T", "thumbnail_playbook": "H", "script_playbook": "S"}, RUN)
    assert artifacts["script_playbook"] == "S"
    for field in ci.ARTIFACT_FIELDS:
        assert meta["artifacts"][field]["research_run_id"] == "run_new"
    assert meta["carried_forward"] == []


def test_carried_forward_playbook_keeps_its_OWN_provenance():
    """The core fix. A run that produced no script playbook keeps the previous
    one — and keeps its run id, its timestamp and its comparability. Handing it
    the new cohort's metadata is how an uncontrolled playbook became 'verified'."""
    previous = _Row(
        script_playbook="[UNCONTROLLED — ...]\nold script playbook",
        cohort_meta=json.dumps({
            "research_run_id": "run_old",
            "artifacts": {"script_playbook": {
                "research_run_id": "run_old",
                "generated_at": "2026-01-01T00:00:00+00:00",
                "is_comparable": False,
                "winner_count": 3, "control_count": 0}},
        }),
    )
    artifacts, meta = ci._merge_run(
        previous, {"title_playbook": "T", "thumbnail_playbook": "", "script_playbook": ""}, RUN)

    assert artifacts["script_playbook"].endswith("old script playbook")
    script_meta = meta["artifacts"]["script_playbook"]
    assert script_meta["research_run_id"] == "run_old"       # NOT run_new
    assert script_meta["is_comparable"] is False             # NOT this run's True
    assert script_meta["generated_at"] == "2026-01-01T00:00:00+00:00"
    assert meta["artifacts"]["title_playbook"]["research_run_id"] == "run_new"
    assert meta["carried_forward"] == ["thumbnail_playbook", "script_playbook"] or \
           meta["carried_forward"] == ["script_playbook"]


def test_pre_migration_row_without_artifact_records_falls_back_to_its_own_run():
    """Rows written before per-artifact provenance existed must still not
    inherit the CURRENT run's credentials."""
    previous = _Row(
        script_playbook="legacy playbook",
        cohort_meta=json.dumps({"research_run_id": "run_legacy",
                                "is_comparable": False, "winner_count": 5}),
    )
    _, meta = ci._merge_run(previous, {"script_playbook": ""}, RUN)
    script_meta = meta["artifacts"]["script_playbook"]
    assert script_meta["research_run_id"] == "run_legacy"
    assert script_meta["is_comparable"] is False


def test_unreadable_previous_metadata_does_not_leak_this_runs_provenance():
    previous = _Row(script_playbook="text", cohort_meta="{not json")
    _, meta = ci._merge_run(previous, {"script_playbook": ""}, RUN)
    assert meta["artifacts"]["script_playbook"].get("research_run_id") != "run_new"


def test_fresh_artifact_replaces_the_old_one_entirely():
    previous = _Row(script_playbook="old",
                    cohort_meta=json.dumps({"research_run_id": "run_old"}))
    artifacts, meta = ci._merge_run(previous, {"script_playbook": "new"}, RUN)
    assert artifacts["script_playbook"] == "new"
    assert meta["artifacts"]["script_playbook"]["research_run_id"] == "run_new"
    assert "script_playbook" not in meta["carried_forward"]


def test_nothing_anywhere_yields_empty_not_missing_keys():
    artifacts, meta = ci._merge_run(None, {}, RUN)
    assert set(artifacts) == set(ci.ARTIFACT_FIELDS)
    assert all(v == "" for v in artifacts.values())
