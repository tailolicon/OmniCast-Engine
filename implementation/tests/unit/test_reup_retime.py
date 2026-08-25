"""Retime helpers: tempo chaining and subtitle timeline shifting."""

from __future__ import annotations

from pathlib import Path

from omnicast.reup.audio.rate_align import build_align_plan
from omnicast.reup.media.retime import (
    RetimedSegment,
    RetimeResult,
    _atempo_chain,
    shift_subtitle_rows,
)


def _result(segments):
    return RetimeResult(
        video_path=Path("v.mp4"),
        voice_track_path=Path("a.wav"),
        duration_ms=segments[-1].end_ms if segments else 0,
        segments=segments,
    )


def test_atempo_passes_a_single_factor_through():
    assert _atempo_chain(1.2) == "atempo=1.20000"


def test_atempo_chains_beyond_the_per_filter_limit():
    # atempo caps at 2.0 per instance, so 2.5x must become 2.0 * 1.25.
    assert _atempo_chain(2.5) == "atempo=2.0,atempo=1.25000"


def test_subtitles_move_onto_the_stretched_timeline():
    # Original row sat at 2000-3000; its segment now occupies 2200-3541.
    segments = [
        RetimedSegment(0, Path("v0"), Path("a0"), 0, 2_200),
        RetimedSegment(1, Path("v1"), Path("a1"), 2_200, 3_541),
    ]
    rows = [
        {"segment_index": 0, "start_ms": 0, "end_ms": 1_800, "text": "a"},
        {"segment_index": 1, "start_ms": 2_000, "end_ms": 3_000, "text": "b"},
    ]
    shifted = shift_subtitle_rows(rows, _result(segments))
    assert [(r["start_ms"], r["end_ms"]) for r in shifted] == [(0, 2_200), (2_200, 3_541)]


def test_shifting_preserves_other_row_fields():
    segments = [RetimedSegment(0, Path("v0"), Path("a0"), 0, 500)]
    rows = [{"segment_index": 0, "start_ms": 0, "end_ms": 100, "text": "xin chào"}]
    assert shift_subtitle_rows(rows, _result(segments))[0]["text"] == "xin chào"


def test_rows_outside_the_plan_are_dropped_not_left_behind():
    # A row left at its original time would drift further out of sync with
    # every stretch before it, which is worse than losing the line.
    segments = [RetimedSegment(0, Path("v0"), Path("a0"), 0, 500)]
    rows = [
        {"segment_index": 0, "start_ms": 0, "end_ms": 100},
        {"segment_index": 9, "start_ms": 9_000, "end_ms": 9_500},
    ]
    shifted = shift_subtitle_rows(rows, _result(segments))
    assert [r["segment_index"] for r in shifted] == [0]


def test_plan_and_shifted_timeline_agree():
    clips = [(0, 0, 2_000, 4_000), (1, 2_000, 4_000, 1_000)]
    plan = build_align_plan(clips, video_duration_ms=4_000)
    cursor, segments = 0, []
    for seg in plan.segments:
        segments.append(
            RetimedSegment(seg.segment_index, Path("v"), Path("a"), cursor, cursor + seg.target_ms)
        )
        cursor += seg.target_ms
    rows = [{"segment_index": i, "start_ms": 0, "end_ms": 1} for i in (0, 1)]
    shifted = shift_subtitle_rows(rows, _result(segments))
    assert shifted[0]["end_ms"] == shifted[1]["start_ms"], "no gap between lines"
    assert shifted[-1]["end_ms"] == plan.output_duration_ms


def test_timeline_survives_a_round_trip(tmp_path):
    from omnicast.reup.media.retime import (
        RetimeResult, RetimedSegment, load_timeline, save_timeline,
    )

    result = RetimeResult(
        video_path=tmp_path / "v.mp4", voice_track_path=tmp_path / "a.wav",
        duration_ms=555833,
        segments=[_seg(tmp_path, 0, 0, 1200), _seg(tmp_path, 1, 1200, 3000)],
    )
    save_timeline(tmp_path, result)
    assert load_timeline(tmp_path) == {0: (0, 1200), 1: (1200, 3000)}


def test_missing_timeline_reads_as_none(tmp_path):
    from omnicast.reup.media.retime import load_timeline

    assert load_timeline(tmp_path) is None


def test_shifting_onto_a_loaded_timeline_matches_the_live_shift(tmp_path):
    # The re-export path reads the timeline from disk; it must land rows in
    # exactly the same place as the in-process shift the runner does.
    from omnicast.reup.media.retime import (
        RetimeResult, RetimedSegment, load_timeline, save_timeline,
        shift_rows_to_timeline, shift_subtitle_rows,
    )

    result = RetimeResult(
        video_path=tmp_path / "v.mp4", voice_track_path=tmp_path / "a.wav",
        duration_ms=9000,
        segments=[_seg(tmp_path, 0, 0, 2000), _seg(tmp_path, 1, 2000, 5200)],
    )
    rows = [{"segment_index": 0, "start_ms": 0, "end_ms": 1500, "subtitle_text": "a"},
            {"segment_index": 1, "start_ms": 1500, "end_ms": 3000, "subtitle_text": "b"}]
    save_timeline(tmp_path, result)
    assert shift_rows_to_timeline(rows, load_timeline(tmp_path)) == shift_subtitle_rows(rows, result)


def test_rows_outside_the_plan_are_dropped_not_left_behind(tmp_path):
    from omnicast.reup.media.retime import shift_rows_to_timeline

    rows = [{"segment_index": 0, "start_ms": 0, "end_ms": 100},
            {"segment_index": 9, "start_ms": 100, "end_ms": 200}]
    shifted = shift_rows_to_timeline(rows, {0: (0, 300)})
    assert [r["segment_index"] for r in shifted] == [0]


def _seg(tmp_path, index, start_ms, end_ms):
    from omnicast.reup.media.retime import RetimedSegment

    return RetimedSegment(
        segment_index=index,
        video_path=tmp_path / f"{index}.mp4",
        audio_path=tmp_path / f"{index}.wav",
        start_ms=start_ms,
        end_ms=end_ms,
    )


def test_slow_node_guard_fires_only_on_a_genuinely_slow_transfer(monkeypatch):
    """Douyin's play URL 302s onto a PCDN node; a bad draw crawls.

    Measured: 0.28 MB/s from a bad node vs ~6 MB/s from a healthy one on the
    same link, and parallel ranges are slower still (per-IP throttling), so
    abandoning the node is the only lever that helps.
    """
    import time as _time

    from omnicast.ingest.douyin._vendor.storage import file_manager as fm

    fm._slow_rerolls.clear()
    ten_seconds_ago = _time.monotonic() - 10
    big = 90 * 1024 * 1024

    assert fm._too_slow("slow.mp4", 3_000_000, ten_seconds_ago, big) is True
    assert fm._too_slow("fast.mp4", 60_000_000, ten_seconds_ago, big) is False


def test_the_guard_waits_out_connection_warmup():
    import time as _time

    from omnicast.ingest.douyin._vendor.storage import file_manager as fm

    fm._slow_rerolls.clear()
    # Two seconds in, throughput says more about TCP ramp-up than the node.
    assert fm._too_slow("x.mp4", 1000, _time.monotonic() - 2, 90 * 1024 * 1024) is False


def test_small_files_are_never_judged():
    import time as _time

    from omnicast.ingest.douyin._vendor.storage import file_manager as fm

    fm._slow_rerolls.clear()
    assert fm._too_slow("cover.jpg", 100, _time.monotonic() - 30, 200_000) is False


def test_the_guard_gives_up_rather_than_looping_forever():
    # If every node is slow, a download that crawls still beats one that never
    # finishes because it keeps abandoning itself.
    import time as _time

    from omnicast.ingest.douyin._vendor.storage import file_manager as fm

    fm._slow_rerolls.clear()
    old = _time.monotonic() - 30
    fired = [fm._too_slow("v.mp4", 1000, old, 90 * 1024 * 1024) for _ in range(6)]
    assert fired.count(True) == fm._SLOW_MAX_REROLLS
    assert fired[-1] is False


def test_the_floor_can_be_switched_off(monkeypatch):
    import time as _time

    from omnicast.ingest.douyin._vendor.storage import file_manager as fm

    fm._slow_rerolls.clear()
    monkeypatch.setattr(fm, "_SLOW_FLOOR_BPS", 0.0)
    assert fm._too_slow("v.mp4", 1, _time.monotonic() - 60, 90 * 1024 * 1024) is False


def test_the_opening_before_the_first_line_is_kept():
    """The retimer only emits planned slots, so anything unplanned is cut.

    Slots run from a line's start to the next line's start, which covers the
    gaps BETWEEN lines but never the stretch before the first one. On a real
    video the first line began at 6.1s and the export lost that opening.
    """
    from omnicast.reup.audio.rate_align import LEAD_IN_INDEX, build_align_plan

    plan = build_align_plan([(0, 6100, 7440, 1300)], video_duration_ms=584_300)
    first = plan.segments[0]
    assert first.segment_index == LEAD_IN_INDEX
    assert (first.source_start_ms, first.source_end_ms) == (0, 6100)
    assert first.audio_speed == 1.0 and first.video_pts == 1.0, "the intro plays at normal speed"


def test_the_whole_source_is_covered_with_no_holes():
    from omnicast.reup.audio.rate_align import build_align_plan

    plan = build_align_plan(
        [(0, 6100, 7440, 1300), (1, 20_000, 21_000, 900), (2, 40_000, 41_000, 800)],
        video_duration_ms=60_000,
    )
    spans = [(s.source_start_ms, s.source_end_ms) for s in plan.segments]
    assert spans[0][0] == 0, "starts at the very beginning"
    covered = 0
    cursor = 0
    for start, _ in spans:
        assert start == cursor or start >= cursor, "slots must not overlap backwards"
        cursor = start
    # Each slot runs to the next slot's start, so summing slot_ms reaches the end.
    assert sum(s.slot_ms for s in plan.segments) == 60_000


def test_a_video_that_opens_on_dialogue_gets_no_lead_in():
    from omnicast.reup.audio.rate_align import build_align_plan

    plan = build_align_plan([(0, 0, 1500, 1400)], video_duration_ms=30_000)
    assert len(plan.segments) == 1, "nothing to preserve, so no extra slot"


def test_the_lead_in_never_shifts_a_subtitle():
    from omnicast.reup.audio.rate_align import LEAD_IN_INDEX
    from omnicast.reup.media.retime import shift_rows_to_timeline

    rows = [{"segment_index": 0, "start_ms": 6100, "end_ms": 7440}]
    shifted = shift_rows_to_timeline(rows, {LEAD_IN_INDEX: (0, 6100), 0: (6100, 7440)})
    assert len(shifted) == 1 and shifted[0]["segment_index"] == 0
