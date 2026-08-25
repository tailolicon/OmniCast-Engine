"""Storyboard → animatic video.

WHAT THIS IS AND IS NOT. An animatic is the storyboard timed and moving: each
frame held for its shot's duration, with the camera move the shot DECLARED
applied as a real motion path, cut together with the transitions the board
specifies. It is what a director watches to find out whether the edit works
before anyone pays to animate it. It is NOT generated video — no frame here
contains motion the image did not already have.

THE MOVE COMES FROM THE RECORD, NOT FROM TASTE. `Shot.movement` is already a
closed vocabulary the whole package agrees on, so a DOLLY_IN shot pushes in and
a PAN shot pans. That matters beyond looking nice: if the animatic moves
differently from the shot record, then the thing the director approved is not
the thing the video pipeline will later be told to make.

STATIC STILL DRIFTS. A held frame with zero movement reads as a slideshow, and
a slideshow reads as "nobody made this". Static shots get a very slow push
(3%) — under the threshold where a viewer reads it as a camera move, over the
threshold where the image looks dead.

Requires ffmpeg on PATH. Everything is best-effort and reports what it did:
a missing frame yields a shorter film and a note, never a crash.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import structlog

from omnicast.storyboard.models import FrameType, Movement, Shot, Storyboard

logger = structlog.get_logger()

#: Windows spawns a console window per ffmpeg call without this — the same
#: flag `media/output_audit.py` and `api/render_routes.py` already use.
_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

DEFAULT_FPS = 30
#: A held storyboard frame stops reading as a beat past roughly six seconds and
#: stops registering below about two.
DEFAULT_SHOT_SECONDS = 4.0
MIN_SHOT_SECONDS = 2.0
MAX_SHOT_SECONDS = 8.0
#: Cross-dissolve length. Long enough to read as a transition, short enough not
#: to eat the shot on either side.
XFADE_SECONDS = 0.5

#: Zoom/pan endpoints per declared camera move, as (zoom_start, zoom_end,
#: x_drift, y_drift) where drift is a fraction of the overscan.
_MOTION: dict[Movement, tuple[float, float, float, float]] = {
    Movement.STATIC:      (1.00, 1.03,  0.0,  0.0),
    Movement.DOLLY_IN:    (1.00, 1.18,  0.0,  0.0),
    Movement.ZOOM_IN:     (1.00, 1.18,  0.0,  0.0),
    Movement.DOLLY_OUT:   (1.18, 1.00,  0.0,  0.0),
    Movement.ZOOM_OUT:    (1.18, 1.00,  0.0,  0.0),
    Movement.PAN:         (1.10, 1.10,  1.0,  0.0),
    Movement.TRACK:       (1.08, 1.12,  0.8,  0.0),
    Movement.TILT:        (1.10, 1.10,  0.0,  1.0),
    Movement.CRANE:       (1.06, 1.14,  0.3,  0.8),
    Movement.STEADICAM:   (1.04, 1.10,  0.3,  0.0),
    Movement.HANDHELD:    (1.06, 1.10,  0.2,  0.15),
}

#: Transitions the board may name, mapped to an ffmpeg xfade mode. Anything
#: unrecognised becomes a hard cut, which is the safe default: an invented
#: transition is a change nobody asked for.
_XFADE = {"fade": "fade", "dissolve": "dissolve", "whip-pan": "wiperight",
          "wipe": "wiperight", "cut": ""}


@dataclass
class AnimaticResult:
    path: str = ""
    seconds: float = 0.0
    shots_used: int = 0
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"path": self.path, "seconds": round(self.seconds, 2),
                "shots_used": self.shots_used, "notes": list(self.notes)}


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


#: Above this a held frame has outstayed its welcome and the shot should have
#: been SPLIT. It is a reporting threshold, never a cut: an earlier version
#: clamped to it and silently truncated three lines of the demo, losing ~24
#: seconds of narration mid-sentence. A frame held too long is a pacing note;
#: a line cut off mid-word is a broken video.
LONG_HOLD_SECONDS = 20.0
#: Breath after a line before the cut. Without it every shot ends on a clipped
#: syllable and the edit feels rushed.
NARRATION_TAIL = 0.7


def audio_seconds(path: str | Path) -> float:
    """Duration of an audio file via ffprobe, or 0.0 if it cannot be read."""
    try:
        proc = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            capture_output=True, text=True, creationflags=_NO_WINDOW)
        return max(0.0, float((proc.stdout or "0").strip()))
    except (OSError, ValueError):
        return 0.0


def shot_seconds(shot: Shot, narration: dict[str, str] | None = None) -> float:
    """How long this frame is held.

    Narration wins when there is any: the picture must stay up until its line
    is finished, and a board duration that disagrees is a board duration that
    would cut the voice off mid-word.
    """
    if narration:
        clip = narration.get(shot.shot_id)
        if clip:
            spoken = audio_seconds(clip)
            if spoken > 0:
                # No upper clamp: the frame stays up until the line is done.
                return max(MIN_SHOT_SECONDS, spoken + NARRATION_TAIL)
    raw = float(shot.duration_s or 0.0) or DEFAULT_SHOT_SECONDS
    return max(MIN_SHOT_SECONDS, min(raw, MAX_SHOT_SECONDS))


def _run(cmd: list[str]) -> tuple[bool, str]:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              creationflags=_NO_WINDOW)
    except OSError as exc:
        return False, str(exc)
    if proc.returncode != 0:
        tail = (proc.stderr or "").strip().splitlines()
        return False, " / ".join(tail[-3:])[:300]
    return True, ""


def _zoompan_filter(shot: Shot, seconds: float, width: int, height: int,
                    fps: int) -> str:
    """The motion path for one held frame.

    The source is upscaled before `zoompan` because zoompan steps its zoom in
    whole source pixels; on a 1:1 image that quantisation is visible as a
    judder every few frames.
    """
    z0, z1, dx, dy = _MOTION.get(shot.movement, _MOTION[Movement.STATIC])
    frames = max(1, int(round(seconds * fps)))
    # `on` is the output frame index; linear interpolation between endpoints.
    zoom = f"{z0}+({z1}-{z0})*on/{frames}"
    # Pan across the overscan the zoom creates, centred when drift is zero.
    x = f"iw/2-(iw/zoom/2)+({dx}*(iw/zoom/8)*(on/{frames}-0.5))"
    y = f"ih/2-(ih/zoom/2)+({dy}*(ih/zoom/8)*(on/{frames}-0.5))"
    return (f"scale={width * 2}:{height * 2}:force_original_aspect_ratio=increase,"
            f"crop={width * 2}:{height * 2},"
            f"zoompan=z='{zoom}':x='{x}':y='{y}':d={frames}:s={width}x{height}:fps={fps},"
            f"format=yuv420p")


def _render_clip_segment(clip: Path, shot: Shot, dst: Path, *, width: int,
                         height: int, fps: int, seconds: float
                         ) -> tuple[bool, str]:
    """Use generated video for this shot, fitted to the shot's duration.

    A Veo clip is a fixed few seconds; the shot may need to be held longer
    because its narration is longer. Rather than loop it — which reads as a
    glitch the moment the viewer notices the same gesture twice — the clip
    plays once and its final frame holds for the remainder, which is what an
    editor does with a short take.
    """
    ok, err = _run([
        "ffmpeg", "-y", "-loglevel", "error", "-i", str(clip),
        "-vf", (f"scale={width}:{height}:force_original_aspect_ratio=increase,"
                f"crop={width}:{height},"
                f"tpad=stop_mode=clone:stop_duration={max(0.0, seconds):.3f},"
                f"format=yuv420p"),
        "-t", f"{seconds:.3f}", "-an",
        "-r", str(fps), "-c:v", "libx264", "-preset", "medium", "-crf", "18",
        "-pix_fmt", "yuv420p", str(dst)])
    return ok, err


def _render_segment(image: Path, shot: Shot, dst: Path, *, width: int,
                    height: int, fps: int,
                    narration: dict[str, str] | None = None) -> tuple[bool, str]:
    seconds = shot_seconds(shot, narration)
    ok, err = _run([
        "ffmpeg", "-y", "-loglevel", "error",
        "-loop", "1", "-i", str(image),
        "-t", f"{seconds:.3f}",
        "-vf", _zoompan_filter(shot, seconds, width, height, fps),
        "-r", str(fps), "-c:v", "libx264", "-preset", "medium", "-crf", "18",
        "-pix_fmt", "yuv420p", str(dst),
    ])
    return ok, err


def _concat(segments: list[tuple[Path, Shot]], dst: Path, *, fps: int,
            work: Path, narrated: bool = False) -> tuple[bool, str]:
    """Join the segments, cross-fading where the board asked for it.

    A plain concat is used when every transition is a cut — it is exact and
    cheap, and re-encoding nine clips to apply zero dissolves would only cost
    a generation of quality.
    """
    wants_xfade = (not narrated) and any(
        _XFADE.get((s.transition or "cut").lower(), "")
        for _p, s in segments[1:])
    if not wants_xfade or len(segments) == 1:
        listing = work / "concat.txt"
        listing.write_text(
            "".join(f"file '{p.as_posix()}'\n" for p, _s in segments),
            encoding="utf-8")
        return _run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat",
                     "-safe", "0", "-i", str(listing), "-c", "copy", str(dst)])

    inputs: list[str] = []
    for path, _shot in segments:
        inputs += ["-i", str(path)]

    filters: list[str] = []
    label = "0:v"
    offset = shot_seconds(segments[0][1])
    for i in range(1, len(segments)):
        shot = segments[i][1]
        mode = _XFADE.get((shot.transition or "cut").lower(), "")
        out = f"v{i}"
        if not mode:
            # A cut inside an xfade chain is a zero-length dissolve; ffmpeg
            # needs a positive duration, so use one frame.
            mode, dur = "fade", 1.0 / fps
        else:
            dur = XFADE_SECONDS
        start = max(0.0, offset - dur)
        filters.append(f"[{label}][{i}:v]xfade=transition={mode}:"
                       f"duration={dur:.3f}:offset={start:.3f}[{out}]")
        label = out
        offset = start + dur + shot_seconds(shot)

    return _run(["ffmpeg", "-y", "-loglevel", "error", *inputs,
                 "-filter_complex", ";".join(filters), "-map", f"[{label}]",
                 "-r", str(fps), "-c:v", "libx264", "-preset", "medium",
                 "-crf", "18", "-pix_fmt", "yuv420p", str(dst)])


def _build_audio_track(segments: list[tuple[Path, Shot]],
                       narration: dict[str, str], music: str | Path | None,
                       work: Path, notes: list[str]) -> Path | None:
    """One audio track aligned exactly to the cut.

    Each narration clip is padded to its shot's EXACT duration before the
    concat, so audio and picture cannot drift apart over nine shots — the
    alternative, concatenating clips and hoping the totals match, accumulates
    error and lands the last line over the wrong frame.
    """
    parts: list[Path] = []
    for index, (_seg, shot) in enumerate(segments):
        dur = shot_seconds(shot, narration)
        dst = work / f"aud_{index:03d}.wav"
        clip = narration.get(shot.shot_id)
        if clip and Path(clip).exists():
            ok, err = _run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(clip),
                            "-af", f"apad=whole_dur={dur:.3f}",
                            "-t", f"{dur:.3f}", "-ar", "48000", "-ac", "2",
                            str(dst)])
        else:
            ok, err = _run(["ffmpeg", "-y", "-loglevel", "error",
                            "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
                            "-t", f"{dur:.3f}", str(dst)])
        if not ok:
            notes.append(f"shot {shot.index}: narration segment failed ({err})")
            return None
        parts.append(dst)

    listing = work / "audio.txt"
    listing.write_text("".join(f"file '{p.as_posix()}'\n" for p in parts),
                       encoding="utf-8")
    voice = work / "voice.wav"
    ok, err = _run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat",
                    "-safe", "0", "-i", str(listing), "-c", "copy", str(voice)])
    if not ok:
        notes.append(f"narration concat failed ({err})")
        return None

    if not music or not Path(music).exists():
        return voice

    total = sum(shot_seconds(s, narration) for _p, s in segments)
    mixed = work / "mixed.m4a"
    # Music sits well under the voice; a bed that competes with narration is
    # a bed the viewer notices, which is the one thing it must never be.
    ok, err = _run([
        "ffmpeg", "-y", "-loglevel", "error",
        "-i", str(voice), "-stream_loop", "-1", "-i", str(music),
        "-filter_complex",
        f"[1:a]volume=0.09,atrim=0:{total:.3f},afade=t=out:st={max(0.0, total - 3):.3f}:d=3[bed];"
        f"[0:a][bed]amix=inputs=2:duration=first:dropout_transition=0[a]",
        "-map", "[a]", "-c:a", "aac", "-b:a", "192k", str(mixed)])
    if not ok:
        notes.append(f"music mix failed ({err}) — kept voice only")
        return voice
    return mixed


def build_animatic(
    board: Storyboard,
    output_path: str | Path,
    *,
    fps: int = DEFAULT_FPS,
    width: int = 1920,
    height: int = 1080,
    audio_path: str | Path | None = None,
    narration: dict[str, str] | None = None,
    music_path: str | Path | None = None,
    clips: dict[str, str] | None = None,
) -> AnimaticResult:
    """Cut the board's rendered frames into a timed, moving film.

    With `narration` ({shot_id: audio file}) each shot is held for its line and
    the audio track is assembled to match the cut exactly. `music_path` lays a
    bed under it.
    """
    result = AnimaticResult()
    if not ffmpeg_available():
        result.notes.append("ffmpeg is not on PATH — no animatic produced")
        return result

    shots = sorted(board.shots, key=lambda s: s.index)
    chosen: list[tuple[Path, Shot]] = []
    for shot in shots:
        frames = board.frames_for(shot.shot_id)
        # Prefer the frame a viewer should linger on; a FIRST frame without its
        # LAST is still the truest single image of the shot's opening.
        order = (FrameType.KEY, FrameType.FIRST, FrameType.LAST)
        frame = next((f for kind in order for f in frames
                      if f.frame_type is kind and f.image_path
                      and Path(f.image_path).exists()), None)
        if frame is None:
            result.notes.append(f"shot {shot.index}: no rendered frame — omitted")
            continue
        chosen.append((Path(frame.image_path), shot))

    if not chosen:
        result.notes.append("no rendered frames on this board")
        return result

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="animatic_"))
    try:
        for _img, shot in chosen:
            held = shot_seconds(shot, narration)
            if held > LONG_HOLD_SECONDS:
                result.notes.append(
                    f"shot {shot.index} is held {held:.1f}s so its narration is "
                    f"not cut off, but that is a long time on one frame — the "
                    f"shot is carrying more than one beat and should be split")

        segments: list[tuple[Path, Shot]] = []
        for position, (image, shot) in enumerate(chosen):
            dst = work / f"seg_{position:03d}.mp4"
            clip = (clips or {}).get(shot.shot_id)
            if clip and Path(clip).exists():
                ok, err = _render_clip_segment(
                    Path(clip), shot, dst, width=width, height=height, fps=fps,
                    seconds=shot_seconds(shot, narration))
                if ok:
                    result.notes.append(
                        f"shot {shot.index}: generated video clip used instead "
                        f"of a held frame")
                else:
                    result.notes.append(
                        f"shot {shot.index}: clip failed ({err}) — fell back to "
                        f"the still")
                    ok, err = _render_segment(image, shot, dst, width=width,
                                              height=height, fps=fps,
                                              narration=narration)
            else:
                ok, err = _render_segment(image, shot, dst, width=width,
                                          height=height, fps=fps,
                                          narration=narration)
            if not ok:
                result.notes.append(f"shot {shot.index}: segment failed ({err})")
                continue
            segments.append((dst, shot))

        if not segments:
            result.notes.append("every segment failed — no animatic produced")
            return result

        silent = work / "silent.mp4"
        ok, err = _concat(segments, silent, fps=fps, work=work,
                          narrated=bool(narration))
        if not ok:
            result.notes.append(f"concat failed ({err})")
            return result

        track: Path | str | None = audio_path
        if narration:
            built = _build_audio_track(segments, narration, music_path, work,
                                       result.notes)
            track = built or audio_path
        elif music_path and Path(music_path).exists():
            track = music_path

        if track and Path(track).exists():
            ok, err = _run([
                "ffmpeg", "-y", "-loglevel", "error", "-i", str(silent),
                "-i", str(track), "-c:v", "copy", "-c:a", "aac",
                "-shortest", str(out)])
            if not ok:
                result.notes.append(f"audio mux failed ({err}) — kept silent cut")
                shutil.copy2(silent, out)
        else:
            shutil.copy2(silent, out)

        result.path = str(out)
        result.shots_used = len(segments)
        result.seconds = sum(shot_seconds(s, narration) for _p, s in segments)
        logger.info("animatic built", board=board.board_id, shots=len(segments),
                    seconds=round(result.seconds, 2), path=str(out))
        return result
    finally:
        shutil.rmtree(work, ignore_errors=True)
