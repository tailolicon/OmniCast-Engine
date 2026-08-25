"""Plan how to reconcile a Vietnamese dub with Chinese source timing.

The ported `voiceover_track.build_fit_filter` squeezes every clip into its
original subtitle slot with an uncapped `atempo`. Measured on a real 8'20"
Douyin video: Vietnamese speech ran 725 s against 490 s of slots (1.48x), so
90% of lines were sped up, median 1.52x and worst 3.22x — every line by a
different amount, which is what makes the delivery lurch.

`pyvideotrans/task/_rate.py` solves it the other way round: cap how fast the
voice may be pushed and absorb the rest by slowing the *video*. This module is
that rule, as a pure planner:

1. Give each line the silence up to the next line's start. ffmpeg cannot retime
   a fragment shorter than a frame, and gaps are free room. (Upstream note:
   "应该提前将当前字幕和下条字幕的空隙都给当前字幕".)
2. Clip fits the slot -> nothing to do; pad with silence.
3. Overruns by <= `max_audio_speed` -> speed the audio only; imperceptible.
4. Overruns by more -> hold audio at `max_audio_speed` and stretch the video by
   whatever is left.

Upstream splits the excess half-and-half between audio and video instead of
capping. Capping is what keeps the voice at one steady rate, which was the
point; `max_audio_speed` is the dial between the two behaviours.
"""

from __future__ import annotations

from dataclasses import dataclass

# Marks the slot that carries the video before the first line of dialogue.
# Deliberately not a real segment index, so subtitle shifting ignores it.
LEAD_IN_INDEX = -1

# 1.2x is upstream's threshold for "fast enough that nobody notices".
DEFAULT_MAX_AUDIO_SPEED = 1.2

# Step 4 hands the whole overrun to the picture, with nothing stopping it. One
# long line against a short gap therefore turns that shot into extreme slow
# motion — and the audit found we had no ceiling at all where pyvideotrans
# carries `max_video_pts_rate` (configure/config.py:373, default 10). Past this
# the line is simply allowed to run over the next one: a slightly late subtitle
# reads far better than a frozen shot.
DEFAULT_MAX_VIDEO_PTS = 10.0

# ffmpeg's PTS retiming is not frame-exact; upstream nudges the factor up by
# this much so a segment never lands short of its target.
PTS_NUDGE = 0.005


@dataclass(slots=True)
class AlignedSegment:
    segment_index: int
    source_start_ms: int
    source_end_ms: int
    clip_duration_ms: int
    slot_ms: int
    target_ms: int
    audio_speed: float
    video_pts: float

    @property
    def needs_audio_speedup(self) -> bool:
        return self.audio_speed > 1.001

    @property
    def needs_video_stretch(self) -> bool:
        return self.video_pts > 1.001


@dataclass(slots=True)
class AlignPlan:
    segments: list[AlignedSegment]
    source_duration_ms: int
    output_duration_ms: int
    max_audio_speed: float

    @property
    def stretch_ratio(self) -> float:
        if not self.source_duration_ms:
            return 1.0
        return self.output_duration_ms / self.source_duration_ms

    def summary(self) -> dict[str, object]:
        sped = [s.audio_speed for s in self.segments if s.needs_audio_speedup]
        stretched = [s.video_pts for s in self.segments if s.needs_video_stretch]
        return {
            "segments": len(self.segments),
            "audio_sped_up": len(sped),
            "max_audio_speed_used": round(max(sped), 3) if sped else 1.0,
            "video_stretched": len(stretched),
            "max_video_pts": round(max(stretched), 3) if stretched else 1.0,
            "source_seconds": round(self.source_duration_ms / 1000, 1),
            "output_seconds": round(self.output_duration_ms / 1000, 1),
            "stretch_ratio": round(self.stretch_ratio, 3),
        }


def build_align_plan(
    clips: list[tuple[int, int, int, int]],
    *,
    video_duration_ms: int,
    max_audio_speed: float = DEFAULT_MAX_AUDIO_SPEED,
    max_video_pts: float = DEFAULT_MAX_VIDEO_PTS,
) -> AlignPlan:
    """Plan audio/video retiming.

    `clips` is `(segment_index, start_ms, end_ms, clip_duration_ms)` per line,
    where `clip_duration_ms` is the synthesised speech length.
    """
    if max_audio_speed < 1.0:
        raise ValueError("max_audio_speed must be >= 1.0")
    if max_video_pts < 1.0:
        raise ValueError("max_video_pts must be >= 1.0")

    ordered = sorted(clips, key=lambda c: (c[1], c[0]))
    planned: list[AlignedSegment] = []

    # Every slot below starts at its own line and runs to the next one, so the
    # gaps BETWEEN lines are covered — but nothing covers the stretch before the
    # first line, and the retimer only emits planned slots. On a measured video
    # the first line began at 6.1s and those six seconds of opening were simply
    # missing from the export. A lead-in slot keeps them, at natural speed with
    # silence over it. `segment_index=-1` matches no subtitle row, which is
    # right: there is no dialogue here to move.
    if ordered and ordered[0][1] > 0:
        lead_ms = min(ordered[0][1], video_duration_ms)
        planned.append(
            AlignedSegment(
                segment_index=LEAD_IN_INDEX,
                source_start_ms=0,
                source_end_ms=lead_ms,
                slot_ms=lead_ms,
                target_ms=lead_ms,
                clip_duration_ms=0,
                audio_speed=1.0,
                video_pts=1.0,
            )
        )

    for position, (index, start_ms, end_ms, clip_ms) in enumerate(ordered):
        # Step 1 — the slot runs to the next line, not to this line's own end.
        next_start = (
            ordered[position + 1][1] if position + 1 < len(ordered) else video_duration_ms
        )
        slot_ms = max(1, next_start - start_ms)
        clip_ms = max(0, clip_ms)

        if clip_ms <= slot_ms:
            # Step 2 — room to spare; the mixer pads the remainder with silence.
            audio_speed, target_ms = 1.0, slot_ms
        else:
            needed = clip_ms / slot_ms
            if needed <= max_audio_speed:
                # Step 3 — a nudge in tempo covers it.
                audio_speed, target_ms = needed, slot_ms
            else:
                # Step 4 — hold the voice at the cap; the video takes the rest,
                # but only down to `max_video_pts`. Beyond that the shot would
                # crawl, so the line runs past its slot instead.
                audio_speed = max_audio_speed
                target_ms = max(slot_ms, int(round(clip_ms / max_audio_speed)))
                target_ms = min(target_ms, int(round(slot_ms * max_video_pts)))

        planned.append(
            AlignedSegment(
                segment_index=index,
                source_start_ms=start_ms,
                source_end_ms=max(end_ms, start_ms + 1),
                clip_duration_ms=clip_ms,
                slot_ms=slot_ms,
                target_ms=target_ms,
                audio_speed=round(audio_speed, 5),
                video_pts=round(target_ms / slot_ms, 5),
            )
        )

    return AlignPlan(
        segments=planned,
        source_duration_ms=video_duration_ms,
        output_duration_ms=sum(s.target_ms for s in planned),
        max_audio_speed=max_audio_speed,
    )


def build_setpts_filter(video_pts: float) -> str:
    """ffmpeg video filter for one planned segment."""
    if video_pts <= 1.001:
        return "setpts=PTS"
    return f"setpts={video_pts + PTS_NUDGE:.5f}*PTS"
