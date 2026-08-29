"""QA self-review — validate a rendered video before marking it "done".

Technique ported from OpenMontage's analysis tools (ffmpeg/ffprobe), stripped of
their BaseTool/ToolResult framework. A render is only trustworthy if it actually
has a video stream, an audio stream, a sane duration, audible audio (not silent),
and non-blank frames. We run cheap deterministic ffmpeg/ffprobe probes and return
a structured report; the caller writes it to status.json and can refuse to ship a
render that fails a hard check.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path


def _ffprobe() -> str | None:
    return shutil.which("ffprobe")


def _ffmpeg() -> str | None:
    return shutil.which("ffmpeg")


def _probe_streams(path: str) -> dict:
    """ffprobe JSON: streams + format. {} on failure."""
    fp = _ffprobe()
    if not fp:
        return {}
    try:
        out = subprocess.run(
            [fp, "-v", "quiet", "-print_format", "json",
             "-show_streams", "-show_format", path],
            capture_output=True, text=True, timeout=60,
        )
        return json.loads(out.stdout or "{}")
    except Exception:
        return {}


def _mean_volume_db(path: str) -> float | None:
    """Single-pass volumedetect mean volume in dB. None if undetectable.
    Near-silent audio reports very low values (e.g. -91 dB)."""
    fm = _ffmpeg()
    if not fm:
        return None
    try:
        out = subprocess.run(
            [fm, "-hide_banner", "-i", path, "-af", "volumedetect",
             "-f", "null", "-"],
            capture_output=True, text=True, timeout=120,
        )
        m = re.search(r"mean_volume:\s*(-?\d+(?:\.\d+)?)\s*dB", out.stderr)
        return float(m.group(1)) if m else None
    except Exception:
        return None


def _frame_brightness(path: str, at_s: float) -> float | None:
    """Average luma (YAVG, 0-255) of one frame via signalstats. None on failure.
    A fully black/blank frame yields ~0."""
    stats = _frame_stats(path, at_s)
    return stats["brightness"] if stats else None


def _frame_stats(path: str, at_s: float) -> dict | None:
    """One frame's luma stats via signalstats: {brightness (YAVG), contrast
    (YHIGH-YLOW, robust 10th..90th percentile spread)}. None on failure.
    Blank/flat frames: brightness ~0 or ~255, contrast ~0."""
    fm = _ffmpeg()
    if not fm:
        return None
    try:
        out = subprocess.run(
            [fm, "-hide_banner", "-ss", f"{at_s:.2f}", "-i", path,
             "-frames:v", "1", "-vf", "signalstats,metadata=print",
             "-f", "null", "-"],
            capture_output=True, text=True, timeout=60,
        )
        vals = {}
        for key in ("YAVG", "YLOW", "YHIGH", "YMAX"):
            m = re.search(rf"lavfi\.signalstats\.{key}=(\d+(?:\.\d+)?)", out.stderr)
            if m:
                vals[key] = float(m.group(1))
        if "YAVG" not in vals:
            return None
        return {
            "brightness": vals["YAVG"],
            "ymax": vals.get("YMAX", 0.0),
            "contrast": max(0.0, vals.get("YHIGH", 0.0) - vals.get("YLOW", 0.0)),
        }
    except Exception:
        return None


def is_blank_frame(stats: dict | None,
                   *, min_brightness: float = 4.0,
                   max_brightness: float = 251.0,
                   min_contrast: float = 2.0) -> bool:
    """Orkas-VideoStudio blank-frame heuristic: near-black, near-white, or flat
    (no luma spread) frames carry no visual content. Pure — unit-testable."""
    if not stats:
        return True
    b = stats.get("brightness", 0.0)
    # A title card is dark with a small area of bright text: the 10th..90th
    # percentile spread ignores it (contrast reads 0) and every static card
    # opening failed hook_frame. Real bright pixels anywhere (YMAX) mean the
    # frame carries content; only near-black with NO bright pixels is blank.
    if stats.get("ymax", 0.0) >= 180.0 and min_brightness <= b <= max_brightness:
        return False
    return (b < min_brightness or b > max_brightness
            or stats.get("contrast", 0.0) < min_contrast)


def freeze_spans_from_stderr(stderr: str) -> list[tuple[float, float]]:
    """Parse ffmpeg freezedetect output into (start_s, duration_s) spans.
    Pure — unit-testable. freezedetect logs freeze_start / freeze_duration
    pairs (freeze_duration may be missing for a freeze running to EOF)."""
    starts = [float(v) for v in re.findall(
        r"freeze_start:\s*(-?\d+(?:\.\d+)?)", stderr)]
    durs = [float(v) for v in re.findall(
        r"freeze_duration:\s*(\d+(?:\.\d+)?)", stderr)]
    spans = []
    for i, st in enumerate(starts):
        spans.append((max(0.0, st), durs[i] if i < len(durs) else -1.0))
    return spans


def _detect_frozen_spans(path: str, min_freeze_s: float) -> list[tuple[float, float]] | None:
    """Run ffmpeg freezedetect over the whole video. Returns spans (start, dur;
    dur=-1 → runs to EOF) at least min_freeze_s long, or None if undetectable.
    Ken-Burns/animated shots always move, so a detected freeze is a real
    stuck/static stretch (bad concat, dead overlay, static card)."""
    fm = _ffmpeg()
    if not fm:
        return None
    try:
        out = subprocess.run(
            [fm, "-hide_banner", "-i", path,
             "-vf", f"freezedetect=n=-50dB:d={min_freeze_s:.1f}",
             "-map", "0:v", "-f", "null", "-"],
            capture_output=True, text=True, timeout=300,
        )
        return freeze_spans_from_stderr(out.stderr)
    except Exception:
        return None


def write_contact_sheet(path: str, out_png: str, *, cols: int = 3,
                        rows: int = 2) -> bool:
    """Evidence contact sheet: cols*rows frames evenly sampled across the video,
    tiled into one PNG (Orkas contact-sheet idea). Best-effort; False on failure."""
    fm = _ffmpeg()
    fp = _ffprobe()
    if not fm or not fp:
        return False
    n = cols * rows
    try:
        pr = subprocess.run(
            [fp, "-v", "quiet", "-show_entries", "format=duration",
             "-of", "csv=p=0", path],
            capture_output=True, text=True, timeout=30,
        )
        dur = float((pr.stdout or "0").strip() or 0)
        if dur <= 0:
            return False
        # fps = n frames over the duration → evenly spread samples.
        out = subprocess.run(
            [fm, "-hide_banner", "-y", "-i", path,
             "-vf", f"fps={n}/{dur:.3f},scale=320:-1,tile={cols}x{rows}",
             "-frames:v", "1", out_png],
            capture_output=True, text=True, timeout=180,
        )
        return out.returncode == 0 and Path(out_png).exists()
    except Exception:
        return False


def assess_motion(motion_sec: float, total_sec: float,
                  min_ratio: float = 0.0) -> dict:
    """Delivery-guard motion check (Orkas promise-preservation): share of
    runtime that is real motion (stock footage / Veo clips) vs static images
    with Ken-Burns ("slide grammar"). Pure — unit-testable.

    min_ratio <= 0 → report-only (pass). Within 0.10 under the floor →
    borderline (still pass=False but flagged borderline for the caller)."""
    ratio = (motion_sec / total_sec) if total_sec > 0 else 0.0
    ok = min_ratio <= 0 or ratio >= min_ratio
    return {
        "motion_ratio": round(ratio, 3),
        "motion_sec": round(motion_sec, 1),
        "total_sec": round(total_sec, 1),
        "min_ratio": min_ratio,
        "pass": ok,
        "borderline": (not ok) and ratio >= min_ratio - 0.10,
    }


def validate_video(
    path: str,
    *,
    expected_duration: float | None = None,
    min_audio_db: float = -50.0,
    min_brightness: float = 6.0,
    duration_tolerance: float = 0.30,
    motion_sec: float | None = None,
    motion_min_ratio: float = 0.0,
    evidence_dir: str | None = None,
) -> dict:
    """Run QA checks on a finished render.

    Returns {ok: bool, checks: {name: {pass, detail}}, summary: str,
    [motion: {...}], [contact_sheet: path]}.
    Hard-fail checks (gate shipping): video_stream, audio_stream, not_silent,
    not_blank, hook_frame. Soft checks (warn only): duration_match,
    frozen_frames, motion_ratio.

    motion_sec: seconds of real motion (stock/Veo clips) on the timeline —
    supplied by the renderer, which knows each scene's visual type. Enables the
    Orkas delivery-guard "is this a slideshow?" metric.
    evidence_dir: when set, a 3x2 contact-sheet PNG is written there.
    """
    p = Path(path)
    checks: dict[str, dict] = {}

    if not p.exists() or p.stat().st_size == 0:
        return {"ok": False, "checks": {
            "file_exists": {"pass": False, "detail": "missing or empty"}},
            "summary": "render file missing/empty"}

    info = _probe_streams(path)
    streams = info.get("streams", [])
    vstreams = [s for s in streams if s.get("codec_type") == "video"]
    astreams = [s for s in streams if s.get("codec_type") == "audio"]
    try:
        duration = float(info.get("format", {}).get("duration", 0.0))
    except (TypeError, ValueError):
        duration = 0.0

    checks["video_stream"] = {
        "pass": bool(vstreams),
        "detail": f"{len(vstreams)} video stream(s)",
    }
    checks["audio_stream"] = {
        "pass": bool(astreams),
        "detail": f"{len(astreams)} audio stream(s)",
    }
    checks["duration_ok"] = {
        "pass": duration > 0.5,
        "detail": f"{duration:.1f}s",
    }

    # Duration match (soft) — only when an expectation is supplied.
    if expected_duration and expected_duration > 0:
        drift = abs(duration - expected_duration) / expected_duration
        checks["duration_match"] = {
            "pass": drift <= duration_tolerance,
            "soft": True,
            "detail": f"got {duration:.1f}s vs expected {expected_duration:.1f}s "
                      f"(drift {drift*100:.0f}%)",
        }

    # Audio not silent.
    mean_db = _mean_volume_db(path) if astreams else None
    checks["not_silent"] = {
        "pass": mean_db is not None and mean_db > min_audio_db,
        "detail": (f"mean {mean_db:.1f} dB (min {min_audio_db})"
                   if mean_db is not None else "no audio measured"),
    }

    # Frames not blank — sample at 3 positions (skip head/tail padding).
    if vstreams and duration > 1:
        samples = [duration * f for f in (0.25, 0.5, 0.75)]
        brights = [b for b in (_frame_brightness(path, t) for t in samples)
                   if b is not None]
        best = max(brights) if brights else None
        checks["not_blank"] = {
            "pass": best is not None and best >= min_brightness,
            "detail": (f"max luma {best:.1f} over {len(brights)} samples"
                       if best is not None else "no frame sampled"),
        }

    # Hook frame not empty (CTR-critical): the opening must show content.
    # Sampled at 3 early points so an intentional fade-from-black still passes;
    # ALL blank = a real dead hook (Orkas EMPTY_HOOK_FRAME). Hard fail.
    if vstreams and duration > 3:
        hook_ts = [0.2, 1.0, 2.0]
        hook_stats = [_frame_stats(path, t) for t in hook_ts]
        measured = [s for s in hook_stats if s is not None]
        all_blank = bool(measured) and all(is_blank_frame(s) for s in measured)
        checks["hook_frame"] = {
            "pass": bool(measured) and not all_blank,
            "detail": (" / ".join(
                f"{t:.1f}s luma {s['brightness']:.0f} contrast {s['contrast']:.0f}"
                for t, s in zip(hook_ts, hook_stats) if s)
                or "no hook frame sampled"),
        }

    # Frozen-frame runs (soft): a long visually-static stretch means a stuck
    # concat / dead overlay — every intended shot animates (Ken-Burns/Veo/stock).
    if vstreams and duration > 20:
        min_freeze = min(8.0, max(4.0, duration * 0.35))
        spans = _detect_frozen_spans(path, min_freeze)
        if spans is not None:
            worst = max((d for _, d in spans), default=0.0)
            checks["frozen_frames"] = {
                "pass": not spans,
                "soft": True,
                "detail": (f"{len(spans)} frozen span(s) ≥{min_freeze:.0f}s, "
                           f"worst {'to-EOF' if worst < 0 else f'{worst:.1f}s'} "
                           f"at {spans[0][0]:.1f}s" if spans
                           else f"no span ≥{min_freeze:.0f}s"),
            }

    result_extra: dict = {}

    # Motion ratio (soft, delivery guard): real footage/Veo vs Ken-Burns stills.
    # Report always; gate only when the channel sets motion_min_ratio > 0.
    if motion_sec is not None and duration > 0:
        motion = assess_motion(motion_sec, duration, motion_min_ratio)
        result_extra["motion"] = motion
        checks["motion_ratio"] = {
            "pass": motion["pass"],
            "soft": True,
            "detail": (f"{motion['motion_ratio']*100:.0f}% motion "
                       f"({motion['motion_sec']:.0f}s/{motion['total_sec']:.0f}s"
                       + (f", floor {motion_min_ratio*100:.0f}%"
                          if motion_min_ratio > 0 else ", report-only") + ")"),
        }

    # Evidence contact sheet (best-effort, never affects pass/fail).
    if evidence_dir:
        try:
            sheet = str(Path(evidence_dir) / "qa_contact_sheet.png")
            if write_contact_sheet(path, sheet):
                result_extra["contact_sheet"] = sheet
        except Exception:
            pass

    hard_fail = [n for n, c in checks.items()
                 if not c.get("soft") and not c["pass"]]
    soft_fail = [n for n, c in checks.items()
                 if c.get("soft") and not c["pass"]]
    ok = not hard_fail
    if ok and soft_fail:
        summary = f"PASS (warnings: {', '.join(soft_fail)})"
    elif ok:
        summary = "PASS - all checks green"
    else:
        summary = f"FAIL: {', '.join(hard_fail)}"
    return {"ok": ok, "checks": checks, "summary": summary, **result_extra}


if __name__ == "__main__":
    import sys
    rep = validate_video(sys.argv[1] if len(sys.argv) > 1 else "")
    print(json.dumps(rep, indent=2, ensure_ascii=False))
