"""P0.1 group 4 — video_intel gets a production caller, or it is dead code.

The handoff put the choice plainly: wire one real vertical slice into the
competitor pipeline, or mark the module experimental/dead — but stop polishing a
module nobody calls. It is wired, on the only path in the system that holds real
competitor transcripts.

These tests pin both halves:

  * the slice runs and the blueprint reaches persistence with its own
    provenance, so a future refactor cannot orphan the module again silently;
  * the three values that were still invented (`video_format="documentary"`,
    `crossfade_seconds=0.5`, a runtime derived from a beat count) are either
    measured or declared as assumptions.
"""

from __future__ import annotations

import pytest

from omnicast.analytics import competitor_intel as ci
from omnicast.analytics.cohort import select_cohort
from omnicast.analytics.transcript import Segment, Transcript
from omnicast.analytics.video_intel import (
    DEFAULT_CROSSFADE_SECONDS,
    UNKNOWN,
    VideoIntelligenceAnalyzer,
)


def _transcript(video_id: str, *, minutes: float = 10.0) -> Transcript:
    """A transcript with real cue timings, so structure is measurable."""
    lines = [
        "Here is the one mistake that costs retirees the most money.",
        "First, the tax bracket everybody gets wrong.",
        "Second, the withdrawal order nobody explains.",
        "Finally, what to do about it this year.",
    ]
    segments = []
    cursor = 0.0
    for line in lines:
        segments.append(Segment(cursor, line, 25.0))
        cursor += 25.0 + 3.0  # a real pause between beats
    return Transcript(
        video_id=video_id,
        text=" ".join(lines),
        source="captions",
        segments=tuple(segments),
    )


# ── the module can now be constructed the way a caller would ────────────────

def test_the_analyzer_no_longer_demands_a_crawler_it_never_used():
    """Requiring an AnalyticsCrawler to run pure functions over a transcript is
    part of why nothing called this module."""
    analyzer = VideoIntelligenceAnalyzer()
    assert analyzer.crawler is None


# ── the three remaining fabrications ────────────────────────────────────────

@pytest.mark.asyncio
async def test_video_format_is_derived_or_unknown_never_documentary():
    analyzer = VideoIntelligenceAnalyzer()
    listicle = await analyzer.build_blueprint("finance", [
        {"title": "5 retirement mistakes", "duration_minutes": 11,
         "structure": {"measured": True, "intro_length": 20,
                       "segment_count": 4, "avg_segment_duration": 150}},
        {"title": "7 tax traps", "duration_minutes": 12,
         "structure": {"measured": True, "intro_length": 18,
                       "segment_count": 4, "avg_segment_duration": 160}},
    ])
    assert listicle.video_format == "listicle"

    nameless = await analyzer.build_blueprint("finance", [
        {"duration_minutes": 11,
         "structure": {"measured": True, "intro_length": 20,
                       "segment_count": 4, "avg_segment_duration": 150}},
    ])
    assert nameless.video_format == UNKNOWN
    assert any("video_format" in n for n in nameless.notes)


@pytest.mark.asyncio
async def test_target_runtime_is_measured_from_real_durations():
    """`segment_count * 2` produced minutes from a count of beats. The sampled
    videos have real durations."""
    analyzer = VideoIntelligenceAnalyzer()
    bp = await analyzer.build_blueprint("finance", [
        {"title": "a", "duration_minutes": 11,
         "structure": {"measured": True, "segment_count": 3,
                       "intro_length": 20, "avg_segment_duration": 150}},
        {"title": "b", "duration_minutes": 13,
         "structure": {"measured": True, "segment_count": 3,
                       "intro_length": 20, "avg_segment_duration": 150}},
        {"title": "c", "duration_minutes": 12,
         "structure": {"measured": True, "segment_count": 3,
                       "intro_length": 20, "avg_segment_duration": 150}},
    ])
    assert bp.target_duration_minutes == 12          # median of the real values
    assert "target_duration_minutes" not in bp.assumed_fields


@pytest.mark.asyncio
async def test_a_missing_duration_is_declared_not_invented():
    analyzer = VideoIntelligenceAnalyzer()
    bp = await analyzer.build_blueprint("finance", [
        {"title": "a", "structure": {"measured": True, "segment_count": 6,
                                     "intro_length": 20,
                                     "avg_segment_duration": 150}},
    ])
    assert bp.target_duration_minutes == 0
    assert "target_duration_minutes" in bp.assumed_fields


@pytest.mark.asyncio
async def test_crossfade_is_always_labelled_as_a_house_default():
    """It is not observable in a transcript at all. Sitting in the constructor
    as a bare 0.5, it read exactly like the measured fields beside it."""
    analyzer = VideoIntelligenceAnalyzer()
    bp = await analyzer.build_blueprint("finance", [
        {"title": "a", "duration_minutes": 10,
         "structure": {"measured": True, "segment_count": 4,
                       "intro_length": 20, "avg_segment_duration": 150}},
    ])
    assert bp.crossfade_seconds == DEFAULT_CROSSFADE_SECONDS
    assert "crossfade_seconds" in bp.assumed_fields


@pytest.mark.asyncio
async def test_visual_fields_are_marked_assumed_when_no_frames_were_seen():
    analyzer = VideoIntelligenceAnalyzer()
    bp = await analyzer.build_blueprint("finance", [
        {"title": "a", "duration_minutes": 10,
         "structure": {"measured": True, "segment_count": 4,
                       "intro_length": 20, "avg_segment_duration": 150}},
    ])
    assert bp.art_style == UNKNOWN
    assert {"art_style", "color_mood", "b_roll_ratio", "text_overlay_freq"} <= set(
        bp.assumed_fields)


# ── the vertical slice ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_the_slice_measures_a_blueprint_from_winner_transcripts():
    rows = [
        {"video_id": "w1", "title": "5 retirement mistakes",
         "duration_minutes": 11.0, "transcript": _transcript("w1")},
        {"video_id": "w2", "title": "7 tax traps to avoid",
         "duration_minutes": 12.0, "transcript": _transcript("w2")},
    ]
    payload, notes = await ci._measure_production("finance", rows)
    assert payload is not None
    assert payload["sample_size"] == 2
    assert payload["video_format"] == "listicle"
    assert payload["target_duration_minutes"] == 12
    assert payload["hook_type"] != UNKNOWN
    # Visual fields were never attempted, and the blueprint says so rather than
    # reporting "cinematic" the way the pre-P0 version did.
    assert payload["art_style"] == UNKNOWN
    assert "crossfade_seconds" in payload["assumed_fields"]
    assert 0.0 < payload["confidence"] < 1.0
    assert notes


@pytest.mark.asyncio
async def test_no_usable_transcript_produces_no_blueprint_and_says_why():
    payload, notes = await ci._measure_production("finance", [])
    assert payload is None
    assert any("no winner transcript" in n for n in notes)


@pytest.mark.asyncio
async def test_learn_scripts_hands_back_the_winner_transcripts_it_paid_for(monkeypatch):
    """The slice must not re-fetch. Transcripts are the most expensive thing in
    the run (captions, then yt-dlp, then Whisper)."""
    cohort = select_cohort({
        "c": [
            {"video_id": "win", "title": "5 retirement mistakes", "views": 100_000,
             "duration_minutes": 11.0, "published_at": "2026-05-01T00:00:00Z"},
            {"video_id": "ctl", "title": "3 market updates", "views": 10_000,
             "duration_minutes": 11.0, "published_at": "2026-05-03T00:00:00Z"},
            {"video_id": "f1", "title": "9 quiet weeks", "views": 9_000,
             "duration_minutes": 11.0, "published_at": "2026-04-20T00:00:00Z"},
        ]
    })
    assert cohort.winners

    fetches: list[str] = []

    async def _fake_transcript(video_id, duration_minutes=0.0):
        fetches.append(video_id)
        return _transcript(video_id)

    class _LLM:
        async def complete(self, system, messages, **kw):
            class R:
                content = "PLAYBOOK"
            return R()

    monkeypatch.setattr(ci, "_fetch_transcript_async", _fake_transcript)

    collected: list[dict] = []
    await ci._learn_scripts(_LLM(), cohort, {}, collect=collected)

    assert [row["video_id"] for row in collected] == ["win"]   # winners only
    assert len(fetches) == len(set(fetches))                   # nothing fetched twice


# ── persistence keeps artifact and provenance together ──────────────────────

class _PreviousRow:
    def __init__(self, cohort_meta: str, **columns):
        self.cohort_meta = cohort_meta
        for key, value in columns.items():
            setattr(self, key, value)


def test_a_blueprint_is_stamped_with_the_run_that_measured_it():
    produced = {"title_playbook": "T", "thumbnail_playbook": "", "script_playbook": ""}
    provenance = {"research_run_id": "run_new", "is_comparable": True}
    _, meta = ci._merge_run(None, produced, provenance,
                            {"production_blueprint": {"confidence": 0.3}})
    assert meta["production_blueprint"] == {"confidence": 0.3}
    assert meta["artifacts"]["production_blueprint"]["research_run_id"] == "run_new"


def test_a_carried_forward_blueprint_keeps_the_old_runs_credentials():
    """The exact laundering `_merge_run` exists to stop, applied to the new
    artifact: a run that measured nothing must not republish last week's
    blueprint under this week's run id."""
    import json

    previous = _PreviousRow(
        json.dumps({
            "production_blueprint": {"confidence": 0.9},
            "artifacts": {"production_blueprint": {"research_run_id": "run_old",
                                                   "is_comparable": False}},
        }),
        title_playbook="", thumbnail_playbook="", script_playbook="",
    )
    _, meta = ci._merge_run(
        previous,
        {"title_playbook": "T", "thumbnail_playbook": "", "script_playbook": ""},
        {"research_run_id": "run_new", "is_comparable": True},
        {"production_blueprint": None},
    )
    assert meta["production_blueprint"] == {"confidence": 0.9}
    assert meta["artifacts"]["production_blueprint"]["research_run_id"] == "run_old"
    assert meta["artifacts"]["production_blueprint"]["is_comparable"] is False
    assert "production_blueprint" in meta["carried_forward"]
