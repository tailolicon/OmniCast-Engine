"""Audiovisual forensics — measure a video's production grammar from the file.

WHY (strategic review §5, P1 in §15):

The review calls this "khoảng trống lớn nhất" — the largest gap. `video_intel`
now measures everything a TRANSCRIPT can support (hook type, beats, words per
minute, runtime), and the P0 work made it honest about the rest: art style,
colour mood, b-roll ratio and text-overlay frequency come back `unknown` and sit
in `assumed_fields`, because no frame was ever looked at.

This module looks at the frames. It is the difference between "we read what they
said" and "we can see how it was cut".

WHAT IT MEASURES, AND HOW

  shot boundaries   ffmpeg `scdet` — score per boundary, so a hard cut (high
                    score, one frame) is distinguishable from a dissolve
                    (moderate score sustained across several frames)
  shot durations    derived from the boundaries; median, spread, cuts/minute
  motion per shot   frame-to-frame luma difference on a downscaled grayscale
                    sample: static / drift (Ken Burns) / dynamic
  colour mood       mean channel balance and luma spread across sampled frames
  silence & pauses  ffmpeg `silencedetect`
  non-speech audio  audio present where the transcript has no cue: the music
                    and SFX bed, and where it starts and stops
  loudness          EBU R128 integrated loudness

WHAT IT DOES NOT MEASURE, AND SAYS SO

Kinetic typography, callout semantics, character consistency, camera framing,
joke and reaction beats, whether the thumbnail promise is paid off — every one
of these needs a vision model, and every one is on the review's list. They are
returned as `missing` with a reason, in the same vocabulary
`analytics.dossier` uses, rather than being left out where a reader cannot
notice their absence.

TEXT OVERLAY IS A PROXY, NOT A MEASUREMENT. Edge density in the lower band of a
frame correlates with burned-in captions, and also with a busy background. It is
reported as `text_overlay_proxy` and marked `inferred`; it deliberately does NOT
populate the blueprint's `text_overlay_freq`, which stays an assumption until
something actually reads the pixels as text.

EVERY STAGE DEGRADES INDEPENDENTLY. No ffmpeg, no numpy, an unreadable file, a
filter missing from an old build — each one costs its own field and says why.
A forensics report with three of six blocks measured is useful; one that raises
is not, and one that silently substitutes defaults is the bug this whole
module exists to end.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass, field

# Status vocabulary, shared with analytics.dossier so a forensics block can be
# folded into a dossier without translation.
MEASURED = "measured"
INFERRED = "inferred"
MISSING = "missing"

# scdet score for a HARD CUT. Dissolves are NOT found by lowering this: a
# one-second crossfade peaks around 0.8 and animated footage produces a steady
# stream of ~1.0 scores, so any threshold low enough to catch the fade invents
# shot boundaries inside every moving shot. Gradual transitions get their own
# detector below.
SCENE_THRESHOLD = 8.0

# Gradual-transition detection, on the sampled frames rather than on scdet.
# A crossfade has a signature no other content has: over the window the picture
# changes completely, every individual step is an EQUAL share of that change,
# and the middle frame is the average of the two ends — which is what a linear
# blend means. A hard cut puts the whole change in one step; animation changes
# just as much but its middle frame is unrelated to its endpoints.
#
# WINDOWS ARE SWEPT, AND THE TOLERANCES ARE RELATIVE. A single fixed window with
# absolute thresholds is only correct for one fade length and one contrast: with
# `change >= 25` and `max_step <= 15` over four samples, the arithmetic pins
# detection to fades of 0.75-1.5s whose luma change is 25-60 of 255. Everything
# else — including this project's own 0.5s house default and every high-contrast
# dissolve — was invisible while the file was still published as one measured
# shot. Tolerances are now fractions of the change itself, so contrast cancels.
GRADUAL_WINDOWS_SECONDS = (0.4, 0.7, 1.0, 1.5, 2.0, 2.5, 3.0)
GRADUAL_MIN_CHANGE = 20.0      # endpoints must genuinely differ (0-255 luma)
GRADUAL_STEP_TOLERANCE = 2.0   # max step vs the change/steps a blend would give
GRADUAL_BLEND_TOLERANCE = 0.15  # |mid - (start+end)/2| as a share of the change
GRADUAL_MIN_STEPS = 3          # below this a cut and a blend are indistinguishable
# Boundaries closer together than this are one transition, not two cuts — a
# dissolve trips the detector on several consecutive frames.
MIN_SHOT_SECONDS = 0.4
# Sampling for motion and colour. 4 fps at 64x36 is ~9 kB/s of raw luma: enough
# to tell a locked-off shot from a whip pan, cheap enough to run on every render.
# 8 fps, not 4: a 0.3-second crossfade is only three samples at 8 fps and one at
# 4, and one sample cannot show a blend. Motion thresholds are per-sample, so
# they are halved with it — the same real motion produces half the difference
# between frames twice as close together.
SAMPLE_FPS = 8.0
SAMPLE_W, SAMPLE_H = 64, 36

# Mean absolute frame-to-frame luma difference (0-255 scale) per motion class.
MOTION_STATIC_MAX = 0.75
MOTION_DRIFT_MAX = 3.0

# Sentinel distinct from None: a probe that ran out of time is a different fact
# from a probe that could not run, and reporting a readable file as "unreadable"
# because it was long is a lie a 4K reference video will trigger in production.
_TIMED_OUT = object()

SILENCE_NOISE_DB = -35.0
SILENCE_MIN_SECONDS = 0.25

# From the review's §5 list. Named individually so the report says which of the
# review's requirements are still open rather than implying it covered them.
NOT_MEASURABLE_HERE: dict[str, str] = {
    "kinetic_typography": "needs a vision model to read animated text",
    "callout_semantics": "needs a vision model to interpret arrows/highlights",
    "character_consistency": "needs face/character embedding across shots",
    "camera_framing": "needs subject detection (close/medium/wide is about the subject)",
    "talking_head_vs_broll": "needs face detection to tell a presenter from footage",
    "joke_and_reaction_beats": "needs multimodal comprehension, not signal processing",
    "thumbnail_promise_payoff": "needs the thumbnail, the title and comprehension of both",
    "sfx_taxonomy": "onset detection can find a hit; naming it needs a classifier",
}


@dataclass
class Shot:
    index: int
    start: float
    end: float
    boundary_score: float = 0.0
    boundary_kind: str = "cut"      # "start" | "cut" | "dissolve"
    motion: str = "unknown"         # "static" | "drift" | "dynamic" | "unknown"
    motion_score: float = 0.0

    @property
    def duration(self) -> float:
        return max(self.end - self.start, 0.0)

    def as_dict(self) -> dict:
        return {"index": self.index, "start": round(self.start, 2),
                "end": round(self.end, 2), "duration": round(self.duration, 2),
                "boundary_score": round(self.boundary_score, 2),
                "boundary_kind": self.boundary_kind,
                "motion": self.motion, "motion_score": round(self.motion_score, 2)}


@dataclass
class AudioSpan:
    start: float
    end: float
    kind: str  # "silence" | "non_speech_audio"

    @property
    def duration(self) -> float:
        return max(self.end - self.start, 0.0)

    def as_dict(self) -> dict:
        return {"start": round(self.start, 2), "end": round(self.end, 2),
                "duration": round(self.duration, 2), "kind": self.kind}


@dataclass
class AVForensics:
    path: str = ""
    duration_seconds: float = 0.0
    shots: list[Shot] = field(default_factory=list)
    audio_spans: list[AudioSpan] = field(default_factory=list)
    colour_mood: str = "unknown"
    colour_metrics: dict = field(default_factory=dict)
    text_overlay_proxy: float | None = None
    integrated_lufs: float | None = None
    mean_volume_dbfs: float | None = None
    field_status: dict[str, str] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    # ── derived rhythm ───────────────────────────────────────────────────────

    @property
    def shot_count(self) -> int:
        return len(self.shots)

    @property
    def cuts_per_minute(self) -> float | None:
        if not self.shots or self.duration_seconds <= 0:
            return None
        return round((len(self.shots) - 1) / (self.duration_seconds / 60.0), 2)

    @property
    def median_shot_seconds(self) -> float | None:
        if not self.shots:
            return None
        import statistics

        return round(statistics.median(s.duration for s in self.shots), 2)

    @property
    def motion_mix(self) -> dict[str, float]:
        """Share of RUNTIME in each motion class — not share of shots.

        A single two-minute locked-off shot and forty half-second whip pans are
        opposite grammars; counting shots would call them 97% dynamic."""
        total = sum(s.duration for s in self.shots)
        if total <= 0:
            return {}
        mix: dict[str, float] = {}
        for shot in self.shots:
            mix[shot.motion] = mix.get(shot.motion, 0.0) + shot.duration
        return {k: round(v / total, 3) for k, v in sorted(mix.items())}

    @property
    def transition_mix(self) -> dict[str, int]:
        mix: dict[str, int] = {}
        for shot in self.shots[1:]:
            mix[shot.boundary_kind] = mix.get(shot.boundary_kind, 0) + 1
        return mix

    @property
    def silence_ratio(self) -> float | None:
        if self.duration_seconds <= 0 or self.field_status.get("silence") != MEASURED:
            return None
        silent = sum(s.duration for s in self.audio_spans if s.kind == "silence")
        return round(silent / self.duration_seconds, 3)

    def as_dict(self) -> dict:
        return {
            "path": self.path,
            "duration_seconds": round(self.duration_seconds, 2),
            "shot_count": self.shot_count,
            "cuts_per_minute": self.cuts_per_minute,
            "median_shot_seconds": self.median_shot_seconds,
            "motion_mix": self.motion_mix,
            "transition_mix": self.transition_mix,
            "colour_mood": self.colour_mood,
            "colour_metrics": dict(self.colour_metrics),
            "text_overlay_proxy": self.text_overlay_proxy,
            "silence_ratio": self.silence_ratio,
            "integrated_lufs": self.integrated_lufs,
            "mean_volume_dbfs": self.mean_volume_dbfs,
            "shots": [s.as_dict() for s in self.shots],
            "audio_spans": [s.as_dict() for s in self.audio_spans],
            "field_status": dict(self.field_status),
            "not_measured": dict(NOT_MEASURABLE_HERE),
            "notes": list(self.notes),
        }


# ── plumbing ─────────────────────────────────────────────────────────────────

def ffmpeg_available() -> bool:
    return bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


def _run(cmd: list[str], timeout: float = 300.0, *, binary: bool = False):
    """Run a probe. Never raises: a failed probe costs its own field.

    `binary` keeps stdout as bytes — raw video frames are not text, and decoding
    them as one loses data silently."""
    try:
        return subprocess.run(cmd, capture_output=True, text=not binary,
                              timeout=timeout)
    except subprocess.TimeoutExpired:
        return _TIMED_OUT
    except (OSError, subprocess.SubprocessError):
        return None


def has_stream(path: str, kind: str) -> bool | None:
    """Whether the file carries a video ('v') or audio ('a') stream.

    Load-bearing. Without it, two probes report a confident measurement of
    something that is not there: `scdet` on a file with no video exits 0 with no
    hits, which `_shots_from_boundaries` turned into one full-length shot; and
    `silencedetect` on a file with no audio prints nothing, which read as 0%
    silence. Both then flowed into the blueprint as measured pacing."""
    proc = _run(["ffprobe", "-v", "error", "-select_streams", kind,
                 "-show_entries", "stream=codec_type", "-of", "csv=p=0",
                 str(path)], timeout=60)
    # `_TIMED_OUT` is a bare sentinel with no `returncode`; it was the one
    # unguarded consumer, and it turned a slow probe into an AttributeError out
    # of a module whose contract is that a failed probe costs its own field.
    if proc is None or proc is _TIMED_OUT or proc.returncode != 0:
        return None
    return bool((proc.stdout or "").strip())


TIMED_OUT = "timed_out"


def probe_duration(path: str):
    """Duration in seconds, `TIMED_OUT`, or None when the file is unreadable.

    Three outcomes, not two. A large-but-perfectly-readable file that exceeds
    the probe budget was being reported as unreadable, which sends an operator
    to look for a corrupt file that is not corrupt."""
    proc = _run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                 "-of", "json", str(path)], timeout=60)
    if proc is _TIMED_OUT:
        return TIMED_OUT
    if proc is None or proc.returncode != 0:
        return None
    try:
        return float(json.loads(proc.stdout)["format"]["duration"])
    except (ValueError, KeyError, TypeError):
        return None


_SCD = re.compile(r"lavfi\.scd\.score:\s*([0-9.]+),\s*lavfi\.scd\.time:\s*([0-9.]+)")


def detect_boundaries(path: str, threshold: float = SCENE_THRESHOLD
                      ) -> list[tuple[float, float]] | None:
    """[(time, score)] of scene changes, or None if the probe could not run."""
    if has_stream(path, "v") is False:
        return None
    proc = _run(["ffmpeg", "-hide_banner", "-i", str(path),
                 "-vf", f"scdet=threshold={threshold:g}", "-f", "null", "-"])
    if proc is None or proc is _TIMED_OUT:
        return None
    hits = [(float(t), float(s)) for s, t in _SCD.findall(proc.stderr)]
    if not hits and proc.returncode != 0:
        return None
    return sorted(hits)


def _shots_from_boundaries(boundaries: list[tuple[float, float]], duration: float,
                           sample_step: float) -> list[Shot]:
    """Collapse detector hits into shots.

    A dissolve trips the detector on several consecutive frames; those are ONE
    transition. Consecutive hits inside `MIN_SHOT_SECONDS` are therefore merged,
    and the merge itself is the evidence that the transition was gradual."""
    merged: list[tuple[float, float, int]] = []   # (time, peak score, hit count)
    for time, score in boundaries:
        if merged and time - merged[-1][0] < MIN_SHOT_SECONDS:
            prev_t, prev_s, count = merged[-1]
            merged[-1] = (prev_t, max(prev_s, score), count + 1)
            continue
        merged.append((time, score, 1))

    cuts = [m for m in merged if 0.0 < m[0] < duration]
    shots: list[Shot] = []
    starts = [0.0] + [m[0] for m in cuts]
    ends = [m[0] for m in cuts] + [duration]
    for index, (start, end) in enumerate(zip(starts, ends)):
        if index == 0:
            shots.append(Shot(index=0, start=start, end=end, boundary_kind="start"))
            continue
        _time, score, _count = cuts[index - 1]
        kind = "cut"
        shots.append(Shot(index=index, start=start, end=end,
                          boundary_score=score, boundary_kind=kind))
    return shots


def sample_frames(path: str, fps: float = SAMPLE_FPS,
                  width: int = SAMPLE_W, height: int = SAMPLE_H):
    """(rgb_frames, times) as a numpy array, or (None, None).

    RGB rather than grayscale because colour mood needs the channels and motion
    only needs one extra conversion."""
    try:
        import numpy as np
    except ImportError:
        return None, None

    proc = _run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(path),
                 "-vf", f"fps={fps:g},scale={width}:{height}",
                 "-pix_fmt", "rgb24", "-f", "rawvideo", "-"], binary=True)
    if proc is None or proc is _TIMED_OUT or not proc.stdout:
        return None, None
    raw = proc.stdout
    frame_bytes = width * height * 3
    count = len(raw) // frame_bytes
    if count < 2:
        return None, None
    frames = np.frombuffer(raw[:count * frame_bytes], dtype=np.uint8)
    frames = frames.reshape(count, height, width, 3).astype(np.float32)
    times = np.arange(count) / fps
    return frames, times


def _luma(frames):
    return frames[..., 0] * 0.299 + frames[..., 1] * 0.587 + frames[..., 2] * 0.114


def detect_gradual_transitions(frames, times) -> list[tuple[float, float]]:
    """[(centre_time, blend_error)] for crossfades/dissolves.

    Found on the sampled frames, not by lowering the scene-change threshold —
    see SCENE_THRESHOLD. A window is a gradual transition when the picture has
    changed completely across it, no single step is much larger than the equal
    share a linear blend would produce (so no hard cut is hiding inside), and
    the middle frame is the average of the two ends.

    Several window lengths are swept because a fade can be a third of a second
    or three seconds, and the tolerances are RELATIVE to the change, so a fade
    between two similar shots and a fade between black and white are judged the
    same way."""
    import numpy as np

    if frames is None or times is None or len(frames) < 4:
        return []
    luma = _luma(frames)
    steps = np.abs(np.diff(luma, axis=0)).mean(axis=(1, 2))

    hits: list[tuple[float, float]] = []
    for window in GRADUAL_WINDOWS_SECONDS:
        span = int(round(window * SAMPLE_FPS))
        if span < GRADUAL_MIN_STEPS or len(luma) <= span:
            continue
        for i in range(len(luma) - span):
            start, end = luma[i], luma[i + span]
            change = float(np.abs(end - start).mean())
            if change < GRADUAL_MIN_CHANGE:
                continue
            # A linear blend spreads `change` evenly over `span` steps. A hard
            # cut puts all of it in one, so its ratio is `span`, not ~1.
            if float(steps[i:i + span].max()) > (change / span) * GRADUAL_STEP_TOLERANCE:
                continue
            middle = luma[i + span // 2]
            blend_error = float(np.abs(middle - (start + end) / 2.0).mean())
            if blend_error > change * GRADUAL_BLEND_TOLERANCE:
                continue
            hits.append((float(times[i + span // 2]), blend_error))

    hits.sort()
    collapsed: list[tuple[float, float]] = []
    for time, error in hits:
        if collapsed and time - collapsed[-1][0] < max(GRADUAL_WINDOWS_SECONDS[0], 1.0):
            if error < collapsed[-1][1]:
                collapsed[-1] = (time, error)
            continue
        collapsed.append((time, error))
    return collapsed


def merge_gradual(shots: list[Shot], gradual: list[tuple[float, float]],
                  duration: float) -> list[Shot]:
    """Fold detected dissolves into the hard-cut shot list, in time order."""
    if not gradual:
        return shots
    cuts = [(s.start, s.boundary_score, "cut") for s in shots[1:]]
    for time, error in gradual:
        if any(abs(time - t) < 1.0 for t, _s, _k in cuts):
            continue  # already accounted for by a hard cut
        if not (0.0 < time < duration):
            continue
        # Score 0 with a distinct scale note: a dissolve's confidence is a blend
        # ERROR (lower is better) and a cut's is an scdet score (higher is
        # better). Mixing the two in one unitless field was misleading, so a
        # dissolve carries its blend error under its own key instead.
        cuts.append((time, -round(error, 3), "dissolve"))
    cuts.sort()

    merged: list[Shot] = []
    starts = [0.0] + [c[0] for c in cuts]
    ends = [c[0] for c in cuts] + [duration]
    for index, (start, end) in enumerate(zip(starts, ends)):
        if index == 0:
            merged.append(Shot(index=0, start=start, end=end, boundary_kind="start"))
            continue
        _time, score, kind = cuts[index - 1]
        merged.append(Shot(index=index, start=start, end=end,
                           boundary_score=score, boundary_kind=kind))
    return merged


def classify_motion(frames, times, shots: list[Shot]) -> None:
    """Annotate each shot in place with its motion class.

    Frames spanning a shot boundary are excluded at BOTH ends. The cut itself is
    the largest frame difference in the video: leaving it in the outgoing shot
    made a three-second locked-off red card read as `dynamic`, which is the
    opposite of the truth and exactly the kind of confident wrong number this
    module exists to stop producing."""
    import numpy as np

    luma = _luma(frames)
    diffs = np.abs(np.diff(luma, axis=0)).mean(axis=(1, 2))
    diff_times = times[1:]
    guard = 1.0 / SAMPLE_FPS

    for shot in shots:
        inside = ((diff_times > shot.start + guard)
                  & (diff_times < shot.end - guard))
        if not inside.any():
            shot.motion, shot.motion_score = "unknown", 0.0
            continue
        score = float(diffs[inside].mean())
        shot.motion_score = score
        if score <= MOTION_STATIC_MAX:
            shot.motion = "static"
        elif score <= MOTION_DRIFT_MAX:
            shot.motion = "drift"
        else:
            shot.motion = "dynamic"


def colour_mood(frames) -> tuple[str, dict]:
    """Warm / cold / neutral / high_contrast, from the pixels."""
    import numpy as np

    mean_rgb = frames.mean(axis=(0, 1, 2))
    luma = _luma(frames)
    contrast = float(luma.std())
    warmth = float(mean_rgb[0] - mean_rgb[2])
    saturation = float(frames.max(axis=3).mean() - frames.min(axis=3).mean())

    metrics = {"mean_r": round(float(mean_rgb[0]), 1),
               "mean_g": round(float(mean_rgb[1]), 1),
               "mean_b": round(float(mean_rgb[2]), 1),
               "warmth": round(warmth, 1),
               "saturation": round(saturation, 1),
               "luma_std": round(contrast, 1)}

    # Contrast is checked first: a high-contrast look is a deliberate grade and
    # the more informative label when both apply.
    if contrast >= 70.0:
        return "high_contrast", metrics
    if warmth >= 12.0:
        return "warm", metrics
    if warmth <= -12.0:
        return "cold", metrics
    return "neutral", metrics


def text_overlay_proxy(frames) -> float:
    """Share of sampled frames whose lower band has caption-like edge density.

    A PROXY. It cannot tell burned-in captions from a busy shop front, which is
    exactly why it is reported under its own name and never becomes
    `text_overlay_freq`."""
    import numpy as np

    luma = _luma(frames)
    band = luma[:, int(luma.shape[1] * 0.6):, :]
    horizontal = np.abs(np.diff(band, axis=2))
    density = (horizontal > 40).mean(axis=(1, 2))
    return round(float((density > 0.06).mean()), 3)


_SILENCE_START = re.compile(r"silence_start:\s*(-?[0-9.]+)")
_SILENCE_END = re.compile(r"silence_end:\s*(-?[0-9.]+)")


def detect_silence(path: str, noise_db: float = SILENCE_NOISE_DB,
                   min_seconds: float = SILENCE_MIN_SECONDS
                   ) -> list[tuple[float, float]] | None:
    # The stream check replaces a guard that looked for "Stream #" in stderr —
    # ffmpeg prints that for the VIDEO stream too, so a file with no audio at
    # all reported `silence: measured, silence_ratio: 0.0`. A file that is 100%
    # silent was being published as 0% silent.
    if has_stream(path, "a") is False:
        return None
    proc = _run(["ffmpeg", "-hide_banner", "-i", str(path), "-af",
                 f"silencedetect=noise={noise_db:g}dB:d={min_seconds:g}",
                 "-f", "null", "-"])
    if proc is None or proc is _TIMED_OUT:
        return None
    starts = [float(x) for x in _SILENCE_START.findall(proc.stderr)]
    ends = [float(x) for x in _SILENCE_END.findall(proc.stderr)]
    return [(s, e) for s, e in zip(starts, ends)]


_LUFS = re.compile(r"I:\s*(-?[0-9.]+)\s*LUFS")


def integrated_loudness(path: str) -> float | None:
    """EBU R128 integrated loudness, or None when the filter did not run.

    ebur128 is not available in every ffmpeg build, and when it fails it STILL
    prints a full, well-formed summary block in which every figure is 0.0 —
    then exits 0. Parsing that block yields a confident "0.0 LUFS" for a
    measurement that never happened, which is worse than no reading at all:
    0.0 LUFS is a clipping-level signal, so it would flag every video as far too
    loud. Real content is never exactly 0.0, so an exact zero is treated as the
    failure it is. Callers get `mean_volume_dbfs` instead."""
    # NO `framelog=quiet`: that option only exists from ffmpeg 6.1, and on
    # older builds it fails the whole filter — which looked exactly like
    # "ebur128 is unusable here" and produced a note saying so. The filter works
    # fine; the option did not.
    proc = _run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path),
                 "-af", "aresample=48000,ebur128", "-f", "null", "-"])
    if proc is None or proc is _TIMED_OUT:
        return None
    hits = _LUFS.findall(proc.stderr)
    if not hits:
        return None
    try:
        value = float(hits[-1])
    except ValueError:
        return None
    return None if value == 0.0 else value


_MEAN_VOL = re.compile(r"mean_volume:\s*(-?[0-9.]+)\s*dB")


def mean_volume_dbfs(path: str) -> float | None:
    """Mean volume in dBFS — the fallback when ebur128 is unusable.

    A DIFFERENT MEASUREMENT, under a different name. Mean sample volume is not
    perceptual loudness; reporting it in a field called `lufs` would let a
    caller compare it against LUFS targets and be wrong by several dB."""
    proc = _run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path),
                 "-af", "volumedetect", "-f", "null", "-"])
    if proc is None or proc is _TIMED_OUT:
        return None
    hits = _MEAN_VOL.findall(proc.stderr)
    try:
        return float(hits[-1]) if hits else None
    except ValueError:
        return None


def _non_speech_spans(duration: float, silences: list[tuple[float, float]],
                      cue_spans: list[tuple[float, float]]) -> list[AudioSpan]:
    """Audible stretches with no speech cue over them — the music/SFX bed."""
    spans: list[AudioSpan] = []
    cursor = 0.0
    blocked = sorted(list(silences) + list(cue_spans))
    for start, end in blocked:
        if start > cursor + 0.5:
            spans.append(AudioSpan(cursor, start, "non_speech_audio"))
        cursor = max(cursor, end)
    if duration - cursor > 0.5:
        spans.append(AudioSpan(cursor, duration, "non_speech_audio"))
    return spans


# ── the analysis ─────────────────────────────────────────────────────────────

def analyse_video(path, *, transcript=None, scene_threshold: float = SCENE_THRESHOLD
                  ) -> AVForensics:
    """Measure the production grammar of one video file.

    `transcript` is optional and only used to separate speech from the music/SFX
    bed — with `analytics.transcript.Transcript`'s cue timings, "audio present
    and nobody is talking" becomes measurable."""
    report = AVForensics(path=str(path))

    if not ffmpeg_available():
        for name in ("duration", "shots", "motion", "colour", "silence", "loudness"):
            report.field_status[name] = MISSING
        report.notes.append("ffmpeg/ffprobe not on PATH — nothing could be measured")
        return report

    duration = probe_duration(str(path))
    if duration is TIMED_OUT:
        for name in ("duration", "shots", "motion", "colour", "silence", "loudness"):
            report.field_status[name] = MISSING
        report.notes.append(
            "the duration probe timed out — the file is LONG or slow to read, "
            "not unreadable; nothing here says anything is wrong with it")
        return report
    if not duration or duration <= 0:
        for name in ("duration", "shots", "motion", "colour", "silence", "loudness"):
            report.field_status[name] = MISSING
        report.notes.append(
            "ffprobe could not read a duration — the file is unreadable, not silent")
        return report
    report.duration_seconds = duration
    report.field_status["duration"] = MEASURED

    has_video = has_stream(str(path), "v")
    has_audio = has_stream(str(path), "a")

    if has_video is False:
        # `scdet` on a file with no video exits 0 with no hits, which used to be
        # indistinguishable from "a single unbroken shot" — so an audio-only
        # file reported one measured shot, and the blueprint published a pacing
        # figure "measured from 1 detected shot" for a file with no pictures.
        for name in ("shots", "motion", "colour", "text_overlay_proxy"):
            report.field_status[name] = MISSING
        report.notes.append(
            "no video stream — nothing to detect shots, motion or colour in")
        boundaries = None
        frames, times = None, None
    else:
        boundaries = detect_boundaries(str(path), scene_threshold)
        if boundaries is None:
            report.field_status["shots"] = MISSING
            report.notes.append(
                "scene detection failed (scdet unavailable or stream unreadable)")
        else:
            report.shots = _shots_from_boundaries(boundaries, duration, 1.0 / SAMPLE_FPS)
            report.field_status["shots"] = MEASURED
        frames, times = sample_frames(str(path))
    if frames is None:
        if has_video is not False:
            report.field_status["motion"] = MISSING
            report.field_status["colour"] = MISSING
            report.field_status["text_overlay_proxy"] = MISSING
            report.notes.append(
                "frame sampling unavailable (numpy missing or no decodable video "
                "stream) — motion, colour and the overlay proxy were not attempted")
    else:
        report.shots = merge_gradual(
            report.shots, detect_gradual_transitions(frames, times), duration)
        if report.shots:
            classify_motion(frames, times, report.shots)
            report.field_status["motion"] = MEASURED
        else:
            report.field_status["motion"] = MISSING
        report.colour_mood, report.colour_metrics = colour_mood(frames)
        report.field_status["colour"] = MEASURED
        report.text_overlay_proxy = text_overlay_proxy(frames)
        # INFERRED, never MEASURED: edge density is not text.
        report.field_status["text_overlay_proxy"] = INFERRED

    silences = None if has_audio is False else detect_silence(str(path))
    if silences is None:
        report.field_status["silence"] = MISSING
        report.field_status["non_speech_audio"] = MISSING
        report.notes.append(
            "no audio stream — a file with no audio is not a file that is 0% "
            "silent" if has_audio is False else
            "silence detection failed")
    else:
        report.field_status["silence"] = MEASURED
        report.audio_spans = [AudioSpan(s, e, "silence") for s, e in silences]
        cue_spans = _cue_spans(transcript)
        if cue_spans:
            report.audio_spans += _non_speech_spans(duration, silences, cue_spans)
            report.field_status["non_speech_audio"] = MEASURED
        else:
            report.field_status["non_speech_audio"] = MISSING
            report.notes.append(
                "no transcript cue timings supplied, so audible-but-not-speech "
                "stretches (the music/SFX bed) could not be separated from speech")

    if has_audio is not False:
        report.integrated_lufs = integrated_loudness(str(path))
        if report.integrated_lufs is None:
            report.mean_volume_dbfs = mean_volume_dbfs(str(path))
            if report.mean_volume_dbfs is not None:
                report.notes.append(
                    "ebur128 produced no usable reading — loudness is mean volume "
                    "in dBFS, NOT LUFS; do not compare it against a LUFS target")
    report.field_status["loudness"] = (
        MEASURED if (report.integrated_lufs is not None
                     or report.mean_volume_dbfs is not None) else MISSING)

    for name in NOT_MEASURABLE_HERE:
        report.field_status[name] = MISSING
    return report


def _cue_spans(transcript) -> list[tuple[float, float]]:
    """Speech spans from a transcript. A junk timing costs its own cue.

    `float("n/a")` raised out of `analyse_video` — in a module whose contract is
    that every stage degrades independently."""
    from omnicast.shared.numbers import num

    segments = tuple(getattr(transcript, "segments", ()) or ())
    spans: list[tuple[float, float]] = []
    for segment in segments:
        start = num(getattr(segment, "start", None))
        duration = num(getattr(segment, "duration", None))
        if start is None or duration is None or duration <= 0:
            continue
        spans.append((start, start + duration))
    return sorted(spans)
