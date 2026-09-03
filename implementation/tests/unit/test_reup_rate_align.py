"""Rate-alignment planner: the rule that keeps a dub's delivery even.

Measured motivation (real 8'20" Douyin video, 362 lines): Vietnamese speech ran
1.48x longer than the Chinese slots, so the old fit-into-slot behaviour sped 90%
of lines by a different amount each — median 1.52x, worst 3.22x.
"""

from __future__ import annotations

import pytest

from omnicast.reup.audio.rate_align import (
    DEFAULT_MAX_AUDIO_SPEED,
    build_align_plan,
    build_setpts_filter,
)


def _plan(clips, *, video_ms=10_000, cap=DEFAULT_MAX_AUDIO_SPEED):
    return build_align_plan(clips, video_duration_ms=video_ms, max_audio_speed=cap)


def test_clip_shorter_than_slot_is_left_alone():
    # (index, start, end, clip_duration)
    plan = _plan([(0, 0, 2_000, 1_200)], video_ms=2_000)
    seg = plan.segments[0]
    assert seg.audio_speed == 1.0
    assert seg.video_pts == 1.0
    assert seg.target_ms == 2_000  # mixer pads the remaining 800 ms


def test_small_overrun_is_absorbed_by_audio_only():
    # 2_200 ms of speech in a 2_000 ms slot -> 1.1x, under the cap.
    plan = _plan([(0, 0, 2_000, 2_200)], video_ms=2_000)
    seg = plan.segments[0]
    assert seg.audio_speed == pytest.approx(1.1, abs=1e-3)
    assert seg.video_pts == 1.0, "video must not move for a sub-cap overrun"


def test_large_overrun_caps_audio_and_stretches_video():
    # 4_000 ms into a 2_000 ms slot would need 2.0x — well past the cap.
    plan = _plan([(0, 0, 2_000, 4_000)], video_ms=2_000)
    seg = plan.segments[0]
    assert seg.audio_speed == pytest.approx(1.2, abs=1e-3)
    # Audio at 1.2x still needs 3_333 ms, so the video carries 1.667x.
    assert seg.target_ms == pytest.approx(3_333, abs=2)
    assert seg.video_pts == pytest.approx(1.667, abs=1e-2)


def test_audio_speed_never_exceeds_the_cap():
    # A pathological 5x overrun must still leave the voice at the cap.
    plan = _plan([(0, 0, 1_000, 5_000)], video_ms=1_000)
    assert plan.segments[0].audio_speed == pytest.approx(1.2, abs=1e-3)
    assert max(s.audio_speed for s in plan.segments) <= DEFAULT_MAX_AUDIO_SPEED + 1e-6


def test_slot_extends_to_the_next_line_not_its_own_end():
    # Line 0 ends at 1_000 but line 1 only starts at 3_000: the 2 s gap is free
    # room, so 2_500 ms of speech needs no speed change at all.
    plan = _plan([(0, 0, 1_000, 2_500), (1, 3_000, 4_000, 500)], video_ms=5_000)
    first = plan.segments[0]
    assert first.slot_ms == 3_000
    assert first.audio_speed == 1.0


def test_last_line_borrows_room_up_to_the_end_of_the_video():
    plan = _plan([(0, 8_000, 8_500, 1_800)], video_ms=10_000)
    # Selected by segment index, not position: a video whose dialogue starts
    # late also gets a lead-in slot first, to keep its opening.
    line = next(s for s in plan.segments if s.segment_index == 0)
    assert line.slot_ms == 2_000
    assert line.audio_speed == 1.0


def test_segments_are_planned_in_timeline_order():
    plan = _plan(
        [(2, 4_000, 5_000, 500), (0, 0, 1_000, 500), (1, 2_000, 3_000, 500)],
        video_ms=6_000,
    )
    assert [s.segment_index for s in plan.segments] == [0, 1, 2]


def test_output_duration_and_stretch_ratio_are_reported():
    plan = _plan([(0, 0, 2_000, 4_000)], video_ms=2_000)
    assert plan.output_duration_ms > plan.source_duration_ms
    assert plan.stretch_ratio == pytest.approx(1.667, abs=1e-2)
    assert plan.summary()["video_stretched"] == 1


def test_a_higher_cap_trades_voice_speed_for_a_shorter_video():
    clips = [(0, 0, 2_000, 4_000)]
    tight = _plan(clips, video_ms=2_000, cap=1.2)
    loose = _plan(clips, video_ms=2_000, cap=1.6)
    assert loose.output_duration_ms < tight.output_duration_ms
    assert loose.segments[0].audio_speed > tight.segments[0].audio_speed


def test_cap_below_one_is_rejected():
    with pytest.raises(ValueError):
        _plan([(0, 0, 1_000, 1_000)], cap=0.9)


def test_setpts_filter_is_a_noop_when_the_video_is_not_stretched():
    assert build_setpts_filter(1.0) == "setpts=PTS"


def test_setpts_filter_nudges_past_the_target():
    # ffmpeg PTS retiming is not frame-exact; landing short would clip speech.
    assert build_setpts_filter(1.5).startswith("setpts=1.505")


def test_an_overlong_line_cannot_freeze_the_shot():
    """Step 4 hands the whole overrun to the picture, unbounded.

    A long line against a short gap turned that shot into extreme slow motion.
    pyvideotrans carries `max_video_pts_rate` (configure/config.py:373) for
    exactly this; we had no ceiling.
    """
    from omnicast.reup.audio.rate_align import build_align_plan

    # 30s of speech against a 1s gap would otherwise stretch the video 25x.
    plan = build_align_plan(
        [(0, 0, 500, 30_000), (1, 1_000, 1_500, 400)],
        video_duration_ms=5_000, max_video_pts=10.0,
    )
    line = next(s for s in plan.segments if s.segment_index == 0)
    assert line.video_pts <= 10.0
    assert line.audio_speed == 1.2, "the voice still holds at its own cap"


def test_the_cap_does_not_touch_ordinary_lines():
    from omnicast.reup.audio.rate_align import build_align_plan

    plan = build_align_plan([(0, 0, 2_000, 2_100)], video_duration_ms=10_000)
    assert plan.segments[0].video_pts == 1.0, "fits the slot, nothing to stretch"


def test_a_nonsense_cap_is_rejected():
    from omnicast.reup.audio.rate_align import build_align_plan

    with pytest.raises(ValueError):
        build_align_plan([(0, 0, 100, 100)], video_duration_ms=1_000, max_video_pts=0.5)
