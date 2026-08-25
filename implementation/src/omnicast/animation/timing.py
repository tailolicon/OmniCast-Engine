"""Keyframes, easing, anticipation, squash-and-stretch, comic timing (§7.1).

These are the parts of animation that ARE arithmetic. §7.1 lists them beside
rigging and drawing, but unlike those they need no renderer to be correct: an
ease curve is a function, anticipation is a lead-in interval, squash-and-stretch
is a volume-preserving scale, and comic timing is the spacing between beats.

Computing them here means that when a renderer arrives it consumes real curves
instead of inventing motion — which is the specific failure §7.1 names, where
"animation" is a pile of images and a crossfade.

VOLUME PRESERVATION IS NOT DECORATION. Squash-and-stretch that does not preserve
volume is just scaling, and it reads as a bug to any viewer who has seen
animation. It is enforced here rather than left to a prompt.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from omnicast.shared.numbers import num as _num

# Named curves. `linear` is included and is almost always wrong for character
# motion — it is here so a caller can say "no easing" explicitly rather than
# getting it by accident.
EASINGS: tuple[str, ...] = (
    "linear", "ease_in", "ease_out", "ease_in_out", "anticipate", "overshoot",
)

# How far ahead of a move its anticipation starts, as a share of the move.
ANTICIPATION_LEAD = 0.25
# How far back the anticipation pulls, as a share of the move's distance.
ANTICIPATION_DEPTH = 0.12
# Overshoot past the target before settling, as a fraction of the move.
OVERSHOOT_AMOUNT = 0.10
# Converts that fraction into the back-easing coefficient. The classic
# `c1 = 1.70158` overshoots by ~10%, so the scale is that constant over 0.10.
_BACK_OVERSHOOT_SCALE = 17.0158

# Comic timing: a beat that lands too close to the previous one has no room to
# read; too far and the joke dies waiting. Both bounds are conventions, named so
# an operator can argue with them.
MIN_BEAT_GAP_SECONDS = 0.4
MAX_BEAT_GAP_SECONDS = 3.5


@dataclass
class Keyframe:
    time: float
    value: float
    easing: str = "ease_in_out"

    def as_dict(self) -> dict:
        return {"time": round(self.time, 3), "value": round(self.value, 4),
                "easing": self.easing}


def ease(kind: str, t: float) -> float:
    """Eased progress in [0, 1] — except `overshoot`/`anticipate`, by design.

    Those two deliberately leave the unit interval: anticipation goes NEGATIVE
    before the move and overshoot goes past 1 before settling. Clamping them
    would remove the only thing that makes them what they are."""
    value = _num(t)
    if value is None:
        return 0.0
    value = min(max(value, 0.0), 1.0)

    if kind == "linear":
        return value
    if kind == "ease_in":
        return value * value
    if kind == "ease_out":
        return 1.0 - (1.0 - value) ** 2
    if kind == "ease_in_out":
        return (2 * value * value if value < 0.5
                else 1.0 - ((-2 * value + 2) ** 2) / 2)
    if kind == "anticipate":
        # Pull back, then go. Negative early by construction.
        if value < ANTICIPATION_LEAD:
            local = value / ANTICIPATION_LEAD
            return -ANTICIPATION_DEPTH * math.sin(local * math.pi)
        local = (value - ANTICIPATION_LEAD) / (1.0 - ANTICIPATION_LEAD)
        return 1.0 - (1.0 - local) ** 2
    if kind == "overshoot":
        if value >= 1.0:
            return 1.0
        # Standard back-out easing, scaled so the peak really is
        # `1 + OVERSHOOT_AMOUNT`. The first version multiplied a sine bump by
        # `1-(1-v)^2`, which is ~0 exactly where the bump peaks: a named
        # constant of 0.10 delivered 0.001, and an operator tuning it got a
        # hundredth of the effect they asked for. §9's own complaint is that
        # numbers like this are buried and uncalibrated.
        c1 = OVERSHOOT_AMOUNT * _BACK_OVERSHOOT_SCALE
        c3 = c1 + 1.0
        return 1.0 + c3 * (value - 1.0) ** 3 + c1 * (value - 1.0) ** 2
    # Unknown curve: linear, and the caller can see it in the keyframe.
    return value


def interpolate(keyframes: list[Keyframe], time: float) -> float | None:
    """Value at `time`, or None outside the keyframed range."""
    # `_num` filters NaN times AND NaN values: `sorted` leaves NaN wherever it
    # was, every comparison against it is False, and the fallthrough returned
    # the last frame's value for a `time` far outside the keyframed range.
    frames = sorted(
        (k for k in keyframes or []
         if isinstance(k, Keyframe)
         and _num(k.time) is not None and _num(k.value) is not None),
        key=lambda k: k.time)
    moment = _num(time)
    if not frames or moment is None:
        return None
    if moment <= frames[0].time:
        return frames[0].value
    if moment >= frames[-1].time:
        return frames[-1].value
    for first, second in zip(frames, frames[1:]):
        if first.time <= moment <= second.time:
            span = second.time - first.time
            if span <= 0:
                return second.value
            progress = ease(second.easing, (moment - first.time) / span)
            return first.value + (second.value - first.value) * progress
    return frames[-1].value


def squash_and_stretch(scale: float) -> tuple[float, float]:
    """(x_scale, y_scale) preserving area — the whole point of the principle.

    `scale` is the vertical factor: 1.2 stretches, 0.8 squashes. Width is
    derived so x*y == 1, because a squash that does not conserve volume is
    scaling, and it reads as a rendering bug rather than as weight."""
    factor = _num(scale)
    if factor is None or factor <= 0:
        return (1.0, 1.0)
    partner = _num(1.0 / factor) if factor else None
    if partner is None or partner <= 0:
        # A denormal input overflowed the reciprocal to `inf` and produced an
        # `nan` area.
        return (1.0, 1.0)
    # Round ONE axis, then re-derive the other from the rounded value. Rounding
    # both independently broke the invariant this function exists for past
    # ~2e4, and past ~1e5 one axis rounded to a literal 0.0 — a renderer fed
    # (1000000.0, 0.0) collapses the character to a zero-height line.
    y = round(factor, 6)
    if y <= 0:
        return (1.0, 1.0)
    x = _num(1.0 / y)
    if x is None or x <= 0:
        return (1.0, 1.0)
    return (x, y)


def anticipation_beats(move_start: float, move_end: float
                       ) -> list[Keyframe] | None:
    """Keyframes for a move that anticipates before it goes.

    Three frames: rest, pull-back, arrival. A move that starts instantly is the
    single most reliable sign that nobody animated it."""
    start, end = _num(move_start), _num(move_end)
    if start is None or end is None or end <= start:
        return None
    duration = end - start
    return [
        Keyframe(time=start, value=0.0, easing="linear"),
        Keyframe(time=start + duration * ANTICIPATION_LEAD,
                 value=-ANTICIPATION_DEPTH, easing="ease_out"),
        Keyframe(time=end, value=1.0, easing="overshoot"),
    ]


@dataclass
class ComicTimingReport:
    beats: int = 0
    gaps: list[float] = field(default_factory=list)
    too_tight: list[int] = field(default_factory=list)
    too_slack: list[int] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def median_gap(self) -> float | None:
        if not self.gaps:
            return None
        import statistics

        return round(statistics.median(self.gaps), 3)

    @property
    def is_measurable(self) -> bool:
        return len(self.gaps) >= 2

    def as_dict(self) -> dict:
        return {
            "beats": self.beats, "gaps": [round(g, 3) for g in self.gaps],
            "median_gap": self.median_gap,
            "too_tight": list(self.too_tight), "too_slack": list(self.too_slack),
            "is_measurable": self.is_measurable,
            "bounds": {"min": MIN_BEAT_GAP_SECONDS, "max": MAX_BEAT_GAP_SECONDS},
            "note": (
                "Timing bounds are conventions, not laws — they are named so an "
                "operator can argue with them. This measures spacing; whether "
                "the joke lands is not a number."
            ),
            "notes": list(self.notes),
        }


def comic_timing_report(beat_times: list[float]) -> ComicTimingReport:
    """Spacing between comedy beats, and which ones crowd or sag.

    It does NOT say whether anything is funny. §9's "no editorial taste" is on
    the explicitly-not-measurable list for the whole system, and pretending a
    gap distribution settles it would be the same overreach."""
    report = ComicTimingReport()
    times = sorted(t for t in (_num(b) for b in (beat_times or [])) if t is not None)
    report.beats = len(times)
    if len(times) < 2:
        report.notes.append(
            "fewer than two beats — spacing needs at least one interval")
        return report

    report.gaps = [b - a for a, b in zip(times, times[1:])]
    for index, gap in enumerate(report.gaps):
        if gap < MIN_BEAT_GAP_SECONDS:
            report.too_tight.append(index)
        elif gap > MAX_BEAT_GAP_SECONDS:
            report.too_slack.append(index)
    if report.too_tight:
        report.notes.append(
            f"{len(report.too_tight)} beat(s) land under {MIN_BEAT_GAP_SECONDS}s "
            "after the previous one — no room for the previous one to read")
    if report.too_slack:
        report.notes.append(
            f"{len(report.too_slack)} gap(s) exceed {MAX_BEAT_GAP_SECONDS}s")
    return report
