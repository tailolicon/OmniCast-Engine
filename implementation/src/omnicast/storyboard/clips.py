"""Shot → a CHAIN of generated clips. The part the first attempt got wrong.

WHAT WENT WRONG BEFORE. The first pass generated one 6-second clip per shot and
held its last frame for the rest of the shot — so a 35-second shot was 6
seconds of motion and 29 seconds of a freeze-frame. Across a 161-second cut
that produced 18 seconds of movement total. It looked exactly like what it was.

WHAT THE REFERENCE REPOS ACTUALLY DO (checked, not assumed):

  * seedance-2.0 `sequence-project-state.md` — a SCENE is the re-anchor unit,
    not the clip unit. "Scenes group beats and own clips"; clips inside a scene
    chain from each other's accepted footage. `extension_depth` counts
    consecutive output-sourced generations and "may not exceed the scene's
    max_chain_depth (default 2, hard ceiling 3)": past that the next clip must
    open from CANONICAL references again. So thirty seconds of screen time is
    five chained clips with a re-anchor partway, never one still held.
  * Jellyfish `services/film/generated_video.py` — submits
    `first_frame_base64` AND `last_frame_base64` plus `seconds` per shot: video
    generated BETWEEN two known frames.
  * ArcReel `routers/custom_providers.py` — gates a `last_frame` capability
    override on `end_image_capable`, refusing to report the override as active
    when the execution layer would silently ignore it.

THE PROMPT WAS ALSO WRONG. seedance `i2v-guide.md` opens with the rule the
first attempt broke: "Prompt only what the image cannot show. A still image
already contains subject identity, product form, wardrobe, palette,
composition, and background. Re-describing those static details often causes
drift." The old prompt pasted the shot's whole static description in. What
belongs in an i2v prompt is motion, camera, timing, lighting change, audio and
preservation constraints — and nothing else.

DRIFT IS BOUNDED BY CONSTRUCTION. Chaining output into input compounds error,
which is why `max_chain_depth` exists. Every re-anchor returns to the frame
that was itself generated with the cast's reference sheet attached, so the
chain is pulled back to the canonical face instead of wandering from it.
"""

from __future__ import annotations

import math
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

import structlog

from omnicast.storyboard.models import ANGLE_GLOSS, MOVEMENT_GLOSS, Movement, Shot

logger = structlog.get_logger()

_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

#: Seconds per generation. seedance's multishot budget is 4-6s per beat and
#: Veo's own sweet spot is the same; longer asks get compressed or skipped.
CLIP_SECONDS = 6
#: seedance default. After this many output-sourced generations in a row, the
#: next clip re-opens from the canonical still.
MAX_CHAIN_DEPTH = 2


@dataclass
class ClipPlan:
    shot_id: str
    shot_index: int
    ordinal: int              # position within the shot
    seconds: int
    start_frame: str          # canonical still, or a predecessor's last frame
    reanchored: bool          # True when this clip re-opened from canonical
    prompt: str
    beat: str = ""
    path: str = ""
    #: Canonical LAST still of the shot. Set only on the chain's final clip:
    #: that clip is generated BETWEEN two known frames (first/last-frame mode),
    #: which pulls whatever drift the chain accumulated back onto the approved
    #: still before the cut. Empty means plain i2v.
    end_frame: str = ""

    def as_dict(self) -> dict:
        return {"shot_id": self.shot_id, "shot_index": self.shot_index,
                "ordinal": self.ordinal, "seconds": self.seconds,
                "start_frame": self.start_frame, "reanchored": self.reanchored,
                "beat": self.beat, "path": self.path, "prompt": self.prompt,
                "end_frame": self.end_frame}


@dataclass
class ChainResult:
    clips: list[ClipPlan] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def rendered(self) -> list[ClipPlan]:
        return [c for c in self.clips if c.path and Path(c.path).exists()]

    @property
    def motion_seconds(self) -> float:
        return sum(c.seconds for c in self.rendered)


def extract_last_frame(video: str | Path, dst: str | Path) -> str:
    """Pull the final frame of a take, for the next clip to open from.

    `-sseof -0.2` rather than the very last frame: encoders often leave the
    final frame duplicated or slightly degraded, and a fifth of a second back
    is visually identical while being a clean reference.
    """
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-sseof", "-0.2",
         "-i", str(video), "-frames:v", "1", "-q:v", "2", str(dst)],
        capture_output=True, text=True, creationflags=_NO_WINDOW)
    if proc.returncode != 0 or not dst.exists() or dst.stat().st_size == 0:
        return ""
    return str(dst.resolve())


# --------------------------------------------------------------------------
# Prompting
# --------------------------------------------------------------------------

#: Micro-actions for a HOLD clip — the image IS the moment and the shot must
#: breathe without anything happening. seedance: "distribute three or four
#: natural micro-actions across the clip".
_HOLD_BEATS = (
    "he blinks once and his gaze settles",
    "a slow breath; the shoulders drop very slightly",
    "the eyes shift a few degrees and hold",
    "a small swallow, then stillness",
)


def _camera_clause(shot: Shot, ordinal: int) -> str:
    """ONE camera move with a start and an endpoint.

    seedance's failure list is explicit: "If camera jumps: use one camera move
    with start and endpoint." Only the first clip of a shot performs the shot's
    declared move; continuing clips hold, because repeating a dolly-in every
    six seconds would zoom the scene into the subject's face.
    """
    if ordinal == 0 and shot.movement is not Movement.STATIC:
        return (f"one {MOVEMENT_GLOSS.get(shot.movement, 'slow move')}, "
                f"{ANGLE_GLOSS.get(shot.angle, 'eye level')}, "
                f"beginning at the framing of the reference and ending tighter")
    return "locked frame, no camera move"


#: Which attached image is which, and what stays fixed between them. Stated as
#: constants because two pipelines need the identical wording: `build_clip_prompt`
#: here (storyboard path) and `film_runner.gate_clips` (the v5 film path, whose
#: shot prompts are hand-written in `film.yaml` and carry no frame roles at all).
#: seedance's `first-last-frame-guide.md` calls the omission the top FLF failure:
#: without the roles the model treats the second image as a style reference and
#: never lands on it.
FLF_FRAME_ROLES = (
    "The first attached image is the first frame. The second attached image is "
    "the last frame — the exact visual target this clip ends on. Preserve the "
    "subject, wardrobe, room layout and lighting of both frames exactly."
)

FLF_MOTION_ONLY = (
    "Generate one continuous take from the first frame to the last frame."
)

#: What must not happen inside a single clip, whichever pipeline built it.
FLF_CONSTRAINTS = (
    "Constraint: no new characters, no scene change, no cut, no text on screen."
)


def flf_clip_prompt(motion: str, style_clause: str = "") -> str:
    """Wrap a hand-written motion description in the FLF frame contract.

    The film path's `film.yaml` gives a bare motion line ("she lifts the lantern
    and turns"). That line alone leaves the endpoints, the identity lock and the
    scene constraints unsaid — exactly the three things the two attached stills
    are there to pin down.
    """
    lines = [FLF_FRAME_ROLES]
    motion = motion.strip()
    if motion:
        lines.append(f"{FLF_MOTION_ONLY} Along the way: {motion.rstrip('.')}.")
    else:
        lines.append(FLF_MOTION_ONLY)
    style_clause = style_clause.strip()
    # Channel style clauses often end with their own scene-change ban. Saying it
    # twice spends prompt budget on a rule the model already has.
    if "no scene change" not in style_clause.lower():
        lines.append(FLF_CONSTRAINTS)
    if style_clause:
        lines.append(style_clause)
    return "\n".join(lines)


def _scope_clauses(shot: Shot) -> list[str]:
    """The event-density firewall, said to the MODEL and not only to the gate.

    `Shot.beats_completed` / `beats_reserved` existed and were checked by the
    continuity gate — and never reached a video prompt, so the model was free
    to replay a finished beat ("Action restarts") or perform a later one early
    ("Future event appears early"). seedance's compiler ships both as
    exclusions on every clip; these are that, capped so a long list cannot eat
    the token budget the motion text needs.
    """
    out: list[str] = []
    done = [b.strip().rstrip(".") for b in shot.beats_completed if str(b).strip()]
    if done:
        out.append("Already happened before this clip: "
                   + "; ".join(done[:3]) + ". Do not replay it.")
    held = [b.strip().rstrip(".") for b in shot.beats_reserved if str(b).strip()]
    if held:
        out.append("Do not yet show: " + "; ".join(held[:3])
                   + ". That belongs to a later shot.")
    return out


def build_clip_prompt(shot: Shot, ordinal: int, total: int,
                      beat: str = "", *, to_last_frame: bool = False) -> str:
    """An i2v prompt that says only what the still cannot.

    Deliberately does NOT restate the subject, the wardrobe, the room or the
    palette: the start frame already carries all of it, and restating it is
    what makes the model redraw — and therefore drift — the very things that
    were supposed to stay fixed.

    `to_last_frame=True` is first/last-frame mode (StoryGen's interpolation
    chain, Jellyfish's first+last pair): both stills are attached, and the
    prompt's job shrinks to the PATH between them — never to the endpoints,
    which the images already state better than words can.
    """
    react = bool(beat)
    if react:
        # React mode: one beat, given room to land. "Rushed emotions read as
        # glitches; give the key beat at least two seconds."
        action = (f"Only this happens: {beat.rstrip('.')}. "
                  f"It lands over two to three seconds and completes before the "
                  f"clip ends.")
    else:
        action = (f"Only this happens: {_HOLD_BEATS[ordinal % len(_HOLD_BEATS)]}. "
                  f"Nobody stands, turns, or leaves frame.")

    if to_last_frame:
        lines = [
            FLF_FRAME_ROLES,
            FLF_MOTION_ONLY
            + (f" Along the way: {beat.rstrip('.')}." if beat else ""),
            f"Camera: {_camera_clause(shot, ordinal)}.",
        ]
    else:
        lines = [
            "The attached image is the first frame. Preserve face identity, "
            "hairstyle, wardrobe, room layout and lighting exactly.",
            action,
            f"Camera: {_camera_clause(shot, ordinal)}.",
        ]
    lines.extend(_scope_clauses(shot))
    if shot.light_key or shot.time_of_day:
        lines.append(f"Lighting stays as it is: "
                     f"{shot.time_of_day or 'unchanged'}"
                     f"{', ' + shot.light_key if shot.light_key else ''}.")
    lines.append("Sound: quiet room tone only.")
    lines.append(FLF_CONSTRAINTS)
    if not to_last_frame and ordinal + 1 < total:
        # The next clip opens from this one's final frame, so it must end
        # somewhere a successor can continue from.
        lines.append("End on a settled, continuable pose rather than mid-gesture.")
    return "\n".join(lines)


# --------------------------------------------------------------------------
# Planning
# --------------------------------------------------------------------------

def plan_shot_chain(shot: Shot, seconds_needed: float, anchor: str, *,
                    end_anchor: str = "",
                    clip_seconds: int = CLIP_SECONDS,
                    max_chain_depth: int = MAX_CHAIN_DEPTH) -> list[ClipPlan]:
    """How many clips this shot needs, and what each one opens from.

    `start_frame` is left blank for clips that open from a predecessor: the
    chain runner fills it after each take, because it can only come from
    footage that actually exists.

    `end_anchor` is the shot's canonical LAST still. When given, the FINAL
    clip is planned as first/last-frame interpolation into it — so however far
    ordinals 0..n-1 drifted, the shot lands back on the approved frame, and
    the next shot's opening (checked against this one by the continuity gate)
    stays true. Intermediate clips never take it: interpolating every clip
    into the same end frame would play the ending n times.
    """
    count = max(1, math.ceil(seconds_needed / clip_seconds))
    beats = [b for b in (shot.action_beats or []) if str(b).strip()]
    plans: list[ClipPlan] = []
    depth = 0
    for i in range(count):
        reanchor = i == 0 or depth >= max_chain_depth
        depth = 0 if reanchor else depth + 1
        beat = beats[i] if i < len(beats) else ""
        final = i == count - 1
        to_last = bool(end_anchor) and final
        plans.append(ClipPlan(
            shot_id=shot.shot_id, shot_index=shot.index, ordinal=i,
            seconds=clip_seconds,
            start_frame=anchor if reanchor else "",
            reanchored=reanchor,
            beat=beat,
            end_frame=end_anchor if to_last else "",
            prompt=build_clip_prompt(shot, i, count, beat,
                                     to_last_frame=to_last)))
    return plans


async def render_shot_chain(shot: Shot, seconds_needed: float, anchor: str,
                            provider, out_dir: str | Path, *,
                            end_anchor: str = "",
                            model: str | None = None,
                            clip_seconds: int = CLIP_SECONDS,
                            max_chain_depth: int = MAX_CHAIN_DEPTH,
                            resolution: tuple[int, int] | None = (1920, 1080),
                            ) -> ChainResult:
    """Generate the whole chain for one shot, threading each take into the next."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    result = ChainResult()
    supports_flf = bool(getattr(provider, "supports_last_frame", False))
    if end_anchor and not supports_flf:
        # The provider cannot take a last frame, so the final clip must not be
        # PROMPTED as if two images were attached — the model would hunt for a
        # "second image" that is not there. Plan plain i2v instead, and say so:
        # "we had a last frame" and "the last frame was used" are different
        # claims.
        result.notes.append(
            f"shot {shot.index}: provider "
            f"'{getattr(provider, 'id', '?')}' takes no last frame — final "
            f"clip falls back to plain i2v instead of first/last interpolation")
        end_anchor = ""
    plans = plan_shot_chain(shot, seconds_needed, anchor,
                            end_anchor=end_anchor,
                            clip_seconds=clip_seconds,
                            max_chain_depth=max_chain_depth)
    previous_tail = ""

    for plan in plans:
        start = plan.start_frame or previous_tail or anchor
        if not plan.start_frame and not previous_tail:
            # The predecessor failed, so this clip cannot continue from it.
            # Re-anchoring is the honest fallback and it is recorded as one.
            plan.reanchored = True
            result.notes.append(
                f"shot {shot.index} clip {plan.ordinal}: predecessor produced no "
                f"frame, re-anchored to the canonical still")
        plan.start_frame = start
        dst = out / f"{shot.index:03d}_{plan.ordinal:02d}.mp4"

        kwargs: dict = {"duration": plan.seconds, "model": model,
                        "output_path": str(dst), "resolution": resolution}
        if plan.end_frame:
            kwargs["last_image_path"] = plan.end_frame
        try:
            await provider.convert(start, plan.prompt, **kwargs)
        except Exception as exc:  # noqa: BLE001 — a failed clip is data
            result.notes.append(f"shot {shot.index} clip {plan.ordinal} failed: "
                                f"{str(exc)[:160]}")
            result.clips.append(plan)
            previous_tail = ""
            continue

        if not dst.exists() or dst.stat().st_size == 0:
            result.notes.append(f"shot {shot.index} clip {plan.ordinal}: provider "
                                f"wrote no file")
            result.clips.append(plan)
            previous_tail = ""
            continue

        plan.path = str(dst.resolve())
        result.clips.append(plan)
        previous_tail = extract_last_frame(
            dst, out / f"{shot.index:03d}_{plan.ordinal:02d}_tail.jpg")
        if not previous_tail:
            result.notes.append(
                f"shot {shot.index} clip {plan.ordinal}: could not extract a tail "
                f"frame, so the next clip re-anchors")

    logger.info("shot chain rendered", shot=shot.index,
                clips=len(result.rendered), planned=len(plans),
                seconds=result.motion_seconds)
    return result
