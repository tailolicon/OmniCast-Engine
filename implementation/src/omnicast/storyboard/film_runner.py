"""Film runner: YAML spec → gated stills → FLF clips → assembled film.

This is the pipeline version of the process that was executed by hand for demo
ep1 v4, with the two measured drift sources designed out (see style_lock.py):

  GATE B'  every keyframe still must pass the style gate against ONE fixed
           anchor before any video money is spent (Orkas: verify keyframe
           before animating; StoryGen: fixed anchor, not a rolling chain).
           Failing stills are regenerated with the anchor attached and the
           style-match clause pinned (AIComicBuilder LAST_FRAME_STYLE_MATCHING)
           — bounded rerolls, fail-closed.
  GATE C'  every clip is generated BETWEEN two approved stills
           (provider.convert_flf). No tail-carry: video tails are never fed
           back as inputs, so in-clip neural softening cannot compound.
  GATE D'  every adjacent boundary is measured (tail N vs head N+1) and the
           landing of each clip vs its target still is reported.
  GATE E'  assembly: 2-frame FLF dedup trim → single BGM under native SFX →
           loudnorm to target → true-peak limiter (level=disabled — the
           limiter's auto-makeup DEFEATS loudnorm otherwise, measured) →
           loudness re-verified from the encoded file.

Everything lands in plan.json (pipeline/edl.py VideoPlan) after every step —
readable, diffable, resumable (Orkas plan.json contract; GAP_3 C-9).
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

import structlog
import yaml

from omnicast.pipeline.edl import (
    DeliveryPromise,
    PromiseType,
    Segment,
    SegmentSource,
    Tracks,
    VideoPlan,
    assess_delivery,
    save_plan,
    validate_plan,
)
from omnicast.storyboard.clips import flf_clip_prompt
from omnicast.storyboard.slop import blocking_findings as blocking_slop
from omnicast.storyboard.slop import lint as lint_slop
from omnicast.storyboard.style_lock import (
    BOUNDARY_GATE,
    MAX_KEYFRAME_NCC,
    MAX_STILL_REROLLS,
    STILL_GATE,
    STYLE_MATCH_CLAUSE,
    StyleVerdict,
    check_boundary,
    check_still,
    content_delta,
    film_span_report,
    style_vector,
)

logger = structlog.get_logger()

_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

#: Frames dropped from the head of every clip after the first at assembly:
#: FLF makes tail(N) ≈ head(N+1) (same approved still), so butt-joining keeps
#: the same pose for ~2 frames — a visible micro-freeze at 24 fps.
FLF_DEDUP_FRAMES = 2
_FPS = 24


class FilmError(RuntimeError):
    """Fail-closed: raised when a gate cannot be satisfied within budget."""


@dataclass
class FilmStill:
    key: str                  # "K1"
    path: Path
    prompt: str = ""          # regen prompt (delta from the anchor's world)
    #: extra reference stills to attach on regen besides the anchor
    extra_refs: list[str] = field(default_factory=list)


@dataclass
class FilmShot:
    shot_id: str              # "S1"
    order: int
    seconds: int
    start: str                # still key
    end: str                  # still key
    prompt: str               # motion-only delta; style clause appended


@dataclass
class FilmSpec:
    name: str
    product_dir: Path
    anchor: str               # style-anchor still key (usually "K1")
    style_lock: str           # rendering-language contract, every prompt
    style_match_clause: str   # pinned when regenerating stills
    video_style_clause: str   # appended to every clip prompt
    stills: dict[str, FilmStill]
    shots: list[FilmShot]
    #: Saved Flow project characters attached to every still regen via the
    #: composer's @-picker. This is the conditioning channel that actually
    #: reaches the model; uploaded ingredient chips never did (measured live).
    characters: list[str] = field(default_factory=list)
    #: Project image asset (display name, e.g. "K1.jpg") attached alongside
    #: the characters as the visual style anchor.
    anchor_asset: str = ""
    aspect: str = "9:16"
    resolution: tuple[int, int] = (768, 1376)
    bgm_path: str = ""
    bgm_gain: float = 0.25
    loudness_lufs: float = -14.0
    true_peak_dbtp: float = -1.0
    still_gate: float = STILL_GATE
    boundary_gate: float = BOUNDARY_GATE

    @property
    def clips_dir(self) -> Path:
        return self.product_dir / "clips"

    @property
    def frames_dir(self) -> Path:
        return self.product_dir / "qa_frames"


def _gate_prompt_slop(stills: dict[str, FilmStill],
                      shots: list[FilmShot]) -> None:
    """Lint every hand-written prompt in the spec BEFORE anything is generated.

    `slop.py` has been in this repo the whole time and the film path never
    called it: the only caller was `storyboard/pipeline.py`, which stops at
    approved stills and never renders video. So the one pipeline that spends
    real credits was also the one with no slop gate. It runs here, at load
    time, because that is the last moment where a fix costs nothing — a
    blocking finding caught after `gate_stills` has already paid for four
    images is a refund nobody issues.
    """
    problems: list[str] = []
    for key, still in stills.items():
        if not still.prompt:
            continue
        findings = lint_slop(still.prompt)
        for finding in findings:
            logger.info("film.slop", where=f"still {key}",
                        detail=finding.describe())
        problems += [f"still {key}: {f.describe()}"
                     for f in blocking_slop(findings)]
    for shot in shots:
        findings = lint_slop(shot.prompt, motion=True)
        for finding in findings:
            logger.info("film.slop", where=f"shot {shot.shot_id}",
                        detail=finding.describe())
        problems += [f"shot {shot.shot_id}: {f.describe()}"
                     for f in blocking_slop(findings)]
    if problems:
        raise FilmError(
            "spec prompts contain blocking slop — fix the prompt text before "
            "spending credits:\n  " + "\n  ".join(problems))


def load_film_spec(path: str | Path) -> FilmSpec:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    missing = [k for k in ("name", "product_dir", "anchor", "style_lock",
                           "video_style_clause", "stills", "shots")
               if k not in raw]
    if missing:
        raise FilmError(f"{path}: spec is missing required keys: "
                        f"{', '.join(missing)}")
    product_dir = Path(raw["product_dir"])
    stills = {
        k: FilmStill(key=k, path=product_dir / v["file"],
                     prompt=v.get("prompt", ""),
                     extra_refs=list(v.get("extra_refs", [])))
        for k, v in raw["stills"].items()
    }
    shots = [
        FilmShot(shot_id=s["id"], order=i, seconds=int(s["seconds"]),
                 start=s["start"], end=s["end"], prompt=s["prompt"])
        for i, s in enumerate(raw["shots"])
    ]
    for s in shots:
        for key in (s.start, s.end):
            if key not in stills:
                raise FilmError(f"shot {s.shot_id}: unknown still key {key!r}")
    _gate_prompt_slop(stills, shots)
    return FilmSpec(
        name=raw["name"],
        product_dir=product_dir,
        anchor=raw["anchor"],
        style_lock=raw["style_lock"],
        # Style-agnostic by design ("the attached reference defines the art
        # style"), so it is a safe default for any film that does not override
        # it — unlike `style_lock`, which is the film's own look and must be
        # written per film.
        style_match_clause=raw.get("style_match_clause", STYLE_MATCH_CLAUSE),
        video_style_clause=raw["video_style_clause"],
        stills=stills,
        shots=shots,
        characters=list(raw.get("characters", [])),
        anchor_asset=raw.get("anchor_asset", ""),
        aspect=raw.get("aspect", "9:16"),
        resolution=tuple(raw.get("resolution", (768, 1376))),
        bgm_path=raw.get("bgm", {}).get("path", ""),
        bgm_gain=float(raw.get("bgm", {}).get("gain", 0.25)),
        loudness_lufs=float(raw.get("loudness_lufs", -14.0)),
        true_peak_dbtp=float(raw.get("true_peak_dbtp", -1.0)),
        still_gate=float(raw.get("still_gate", STILL_GATE)),
        boundary_gate=float(raw.get("boundary_gate", BOUNDARY_GATE)),
    )


# ---------------------------------------------------------------------------
# GATE B' — stills
# ---------------------------------------------------------------------------

def _still_regen_prompt(spec: FilmSpec, still: FilmStill) -> str:
    """Content first, style contract last. Two live lessons baked in:
    the word "frame" is BANNED (the model painted a literal empty picture
    frame), and no reference-image roles are described — conditioning comes
    from the project's attached characters, not uploaded chips."""
    if not still.prompt:
        raise FilmError(
            f"still {still.key} failed the style gate but has no regen prompt "
            f"in the spec — cannot regenerate, refusing to continue")
    # NO meta-instructions about the reference images: telling Nano Banana 2
    # to "keep the previous story moment" made it COPY the refs and drop the
    # scene delta (measured live — the hand-run with a bare scene description
    # landed the pose, the ref_line version reproduced K5). The chips carry
    # identity by themselves; the prompt only describes THIS moment.
    return (
        f"{still.prompt}\n\n"
        f"Art style (must match the attached pictures exactly): "
        f"{spec.style_lock}"
    )


async def gate_stills(spec: FilmSpec, provider) -> dict[str, StyleVerdict]:
    """Verify every keyframe against the anchor; regenerate failures (bounded).

    Two checks per still, both cheap and both required:
      style  — lineart distance vs the FIXED anchor (drift kills the film);
      content — NCC vs the previous keyframe must stay below MAX_KEYFRAME_NCC
                (a copy means the story beat did not happen; also catches a
                stale download pretending to be a new generation).
    The anchor itself is exempt (it DEFINES the style) but must exist.
    """
    anchor_still = spec.stills[spec.anchor]
    if not anchor_still.path.exists():
        raise FilmError(f"style anchor {spec.anchor} missing: {anchor_still.path}")
    anchor_vec = style_vector(anchor_still.path)

    verdicts: dict[str, StyleVerdict] = {}
    for key, still in spec.stills.items():
        if key == spec.anchor:
            continue
        prev_path = (spec.product_dir / still.extra_refs[0]
                     if still.extra_refs else None)
        rerolls = 0
        while True:
            failure = ""
            if still.path.exists():
                try:
                    verdict = check_still(still.path, anchor_vec,
                                          spec.still_gate)
                except Exception as exc:
                    # A non-image on disk (the live wrong-mode bug wrote an
                    # mp4 as a .jpg) is a FAILED candidate, not a crash: drop
                    # it and let the bounded reroll handle it.
                    still.path.unlink(missing_ok=True)
                    failure = f"unreadable candidate ({type(exc).__name__})"
                    logger.warning("film.still_unreadable", key=key,
                                   error=str(exc)[:200])
                else:
                    verdicts[key] = verdict
                    if not verdict.passed:
                        failure = f"style distance {verdict.distance:.4f}"
                    else:
                        # Content check against EVERY other keyframe, not
                        # just the previous one: a regen that reproduced K5
                        # while K6 was its prev sailed through the prev-only
                        # check (live run 44).
                        for other_key, other in spec.stills.items():
                            if other_key == key or not other.path.exists():
                                continue
                            ncc = content_delta(still.path, other.path)
                            if ncc > MAX_KEYFRAME_NCC:
                                failure = (
                                    f"content copy of {other_key} "
                                    f"(ncc {ncc:.4f} > {MAX_KEYFRAME_NCC})")
                                logger.info("film.still_content_copy",
                                            key=key, of=other_key, ncc=ncc)
                                break
                    if not failure:
                        break
            if rerolls >= MAX_STILL_REROLLS:
                raise FilmError(
                    f"still {key} failed its gate {rerolls}x "
                    f"(last: {failure or 'missing file'}) — stopping before "
                    f"video spend")
            rerolls += 1
            logger.info("film.still_regen", key=key, attempt=rerolls,
                        reason=failure or "missing")
            if hasattr(provider, "set_prompt_files"):
                # Reference chips through the @-picker. When a saved project
                # CHARACTER carries the anchor (its source image is the K1
                # keyframe), attaching the anchor file again is redundant —
                # and a single character chip is what made Nano Banana 2
                # finally hold the story content (measured live: every
                # multi-file NB2 attempt drifted; character+prompt landed).
                files = [] if spec.characters else [str(anchor_still.path)]
                if prev_path is not None and prev_path.exists():
                    files.append(str(prev_path))
                provider.set_prompt_files(files)
            if spec.characters and hasattr(provider, "set_characters"):
                provider.set_characters(spec.characters)
            if spec.anchor_asset and hasattr(provider, "set_prompt_assets"):
                provider.set_prompt_assets([spec.anchor_asset])
            await provider.generate(
                _still_regen_prompt(spec, still),
                output_path=str(still.path),
                resolution=spec.resolution,
                wait_s=240,
            )
    return verdicts


# ---------------------------------------------------------------------------
# plan.json
# ---------------------------------------------------------------------------

def build_plan(spec: FilmSpec) -> VideoPlan:
    segments = [
        Segment(
            segment_id=shot.shot_id,
            order=shot.order,
            source=SegmentSource.GENERATE,
            target_sec=float(shot.seconds),
            spec={
                "prompt": shot.prompt,
                "start_still": shot.start,
                "end_still": shot.end,
                "seconds": shot.seconds,
                "mode": "flf",
            },
        )
        for shot in spec.shots
    ]
    plan = VideoPlan(
        plan_id=f"film-{spec.name}",
        aspect=spec.aspect,
        total_target_sec=float(sum(s.seconds for s in spec.shots)),
        delivery_promise=DeliveryPromise(type=PromiseType.MOTION_LED),
        segments=segments,
        tracks=Tracks(music={"path": spec.bgm_path, "gain": spec.bgm_gain}),
        billable_generations=len(segments),
    )
    problems = validate_plan(plan)
    if problems:
        raise FilmError(f"plan invalid: {problems}")
    return plan


# ---------------------------------------------------------------------------
# GATE C' — clips (FLF between approved stills only)
# ---------------------------------------------------------------------------

async def gate_clips(spec: FilmSpec, plan: VideoPlan, provider,
                     reuse: bool = True) -> VideoPlan:
    spec.clips_dir.mkdir(parents=True, exist_ok=True)
    for seg in plan.ordered():
        out = spec.clips_dir / f"{seg.segment_id}.mp4"
        if reuse and seg.produced:
            continue
        if reuse and out.exists():
            plan = plan.with_produced(seg.segment_id, str(out))
            save_plan(plan, spec.product_dir)
            continue
        shot = next(s for s in spec.shots if s.shot_id == seg.segment_id)
        # `shot.prompt` from film.yaml is a bare motion line. On its own it
        # never tells the model which attached still is the first frame and
        # which is the target it must land on — the top first/last-frame
        # failure in seedance's guide, and the likely reason clips drifted off
        # their end keyframe before the endpoints were being measured at all.
        prompt = flf_clip_prompt(shot.prompt, spec.video_style_clause)
        logger.info("film.clip_gen", shot=shot.shot_id, seconds=shot.seconds)
        result = await provider.convert_flf(
            str(spec.stills[shot.start].path),
            str(spec.stills[shot.end].path),
            prompt,
            seconds=shot.seconds,
            output_path=str(out),
        )
        plan = plan.with_produced(seg.segment_id, result["path"])
        seg2 = plan.segment(seg.segment_id)
        if seg2 is not None:
            seg2.evidence.update({"workflow": result.get("workflow", ""),
                                  "media_id": result.get("media_id", "")})
        save_plan(plan, spec.product_dir)
    return plan


# ---------------------------------------------------------------------------
# GATE D' — boundaries
# ---------------------------------------------------------------------------

def _run(cmd: list[str]) -> None:
    proc = subprocess.run(cmd, capture_output=True, text=True,
                          creationflags=_NO_WINDOW)
    if proc.returncode != 0:
        raise FilmError(f"ffmpeg failed: {' '.join(cmd)}\n{proc.stderr[-2000:]}")


def _extract_frame(video: Path, out: Path, *, tail: bool) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    if tail:
        _run(["ffmpeg", "-y", "-v", "error", "-sseof", "-0.15", "-i",
              str(video), "-frames:v", "1", "-update", "1", "-q:v", "2", str(out)])
    else:
        _run(["ffmpeg", "-y", "-v", "error", "-i", str(video),
              "-frames:v", "1", "-q:v", "2", str(out)])
    return out


def gate_boundaries(spec: FilmSpec, plan: VideoPlan) -> dict:
    """Measure every cut. Hard-fail on adjacent style break; report landing."""
    ordered = plan.ordered()
    frames = spec.frames_dir
    heads: dict[str, Path] = {}
    tails: dict[str, Path] = {}
    for seg in ordered:
        video = Path(seg.produced_path)
        heads[seg.segment_id] = _extract_frame(
            video, frames / f"head_{seg.segment_id}.jpg", tail=False)
        tails[seg.segment_id] = _extract_frame(
            video, frames / f"tail_{seg.segment_id}.jpg", tail=True)

    boundaries: list[dict] = []
    failures: list[str] = []
    for a, b in zip(ordered, ordered[1:]):
        verdict = check_boundary(tails[a.segment_id], heads[b.segment_id],
                                 spec.boundary_gate)
        boundaries.append({"cut": f"{a.segment_id}|{b.segment_id}",
                           **verdict.as_dict()})
        if not verdict.passed:
            failures.append(
                f"{a.segment_id}|{b.segment_id} distance "
                f"{verdict.distance:.4f} > {spec.boundary_gate}")

    span = film_span_report(
        heads[ordered[0].segment_id],
        [tails[s.segment_id] for s in ordered])

    report = {"boundaries": boundaries, "film_span": span}
    (spec.product_dir / "qa_report.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8")
    if failures:
        raise FilmError("boundary gate failed: " + "; ".join(failures))
    return report


# ---------------------------------------------------------------------------
# GATE E' — assembly
# ---------------------------------------------------------------------------

def _probe_duration(path: Path) -> float:
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, creationflags=_NO_WINDOW)
    return float(proc.stdout.strip())


def _measure_loudness(path: Path) -> tuple[float, float]:
    proc = subprocess.run(
        ["ffmpeg", "-i", str(path), "-af",
         "loudnorm=I=-14:TP=-1.5:print_format=summary", "-f", "null",
         "NUL" if sys.platform == "win32" else "/dev/null"],
        capture_output=True, text=True, creationflags=_NO_WINDOW)
    text = proc.stderr
    lufs = re.search(r"Input Integrated:\s*([-+0-9.]+)\s*LUFS", text)
    tp = re.search(r"Input True Peak:\s*([-+0-9.]+)\s*dBTP", text)
    if not lufs or not tp:
        raise FilmError("could not measure loudness of assembled film")
    return float(lufs.group(1)), float(tp.group(1))


def assemble(spec: FilmSpec, plan: VideoPlan) -> Path:
    ordered = plan.ordered()
    clips = [Path(s.produced_path) for s in ordered]
    trim = FLF_DEDUP_FRAMES / _FPS
    total = sum(_probe_duration(c) for c in clips) - trim * (len(clips) - 1)

    inputs: list[str] = []
    for c in clips:
        inputs += ["-i", str(c)]
    has_bgm = bool(spec.bgm_path) and Path(spec.bgm_path).exists()
    if has_bgm:
        inputs += ["-i", spec.bgm_path]

    parts: list[str] = []
    concat_in = ""
    for i in range(len(clips)):
        if i == 0:
            parts.append(f"[{i}:v]setpts=PTS-STARTPTS[v{i}]")
            parts.append(f"[{i}:a]asetpts=PTS-STARTPTS[a{i}]")
        else:
            parts.append(
                f"[{i}:v]trim=start={trim:.4f},setpts=PTS-STARTPTS[v{i}]")
            parts.append(
                f"[{i}:a]atrim=start={trim:.4f},asetpts=PTS-STARTPTS[a{i}]")
        concat_in += f"[v{i}][a{i}]"
    parts.append(f"{concat_in}concat=n={len(clips)}:v=1:a=1[vc][nat]")

    if has_bgm:
        fade_out = max(total - 2.5, 0.0)
        parts.append(
            f"[{len(clips)}:a]volume={spec.bgm_gain},afade=t=in:d=1.5,"
            f"afade=t=out:st={fade_out:.2f}:d=2.5,atrim=0:{total:.2f},"
            f"asetpts=PTS-STARTPTS[bgm]")
        parts.append("[nat][bgm]amix=inputs=2:duration=first:normalize=0[mx]")
        amain = "[mx]"
    else:
        amain = "[nat]"
    parts.append(
        f"{amain}loudnorm=I={spec.loudness_lufs}:TP=-1.5:LRA=11,"
        f"aresample=48000[aout]")

    staged = spec.product_dir / "_assembled_stage.mp4"
    final = spec.product_dir / "final.mp4"
    _run(["ffmpeg", "-y", "-v", "error", *inputs,
          "-filter_complex", ";".join(parts),
          "-map", "[vc]", "-map", "[aout]",
          "-c:v", "libx264", "-crf", "18", "-preset", "slow",
          "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
          "-ar", "48000", "-movflags", "+faststart", str(staged)])

    # True-peak limiter pass. level=disabled is LOAD-BEARING: alimiter's
    # default auto-leveling adds makeup gain that un-does loudnorm (measured
    # +1.4 LUFS on ep1 v4 before this was caught).
    _run(["ffmpeg", "-y", "-v", "error", "-i", str(staged),
          "-c:v", "copy", "-af",
          "alimiter=limit=0.841:level=disabled:attack=3:release=60",
          "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
          "-movflags", "+faststart", str(final)])
    staged.unlink(missing_ok=True)

    lufs, tp = _measure_loudness(final)
    if abs(lufs - spec.loudness_lufs) > 1.0 or tp > spec.true_peak_dbtp:
        raise FilmError(
            f"assembled loudness out of spec: {lufs} LUFS (target "
            f"{spec.loudness_lufs}±1.0), TP {tp} dBTP (max {spec.true_peak_dbtp})")

    delivery = assess_delivery(plan)
    meta = {
        "final": str(final),
        "duration_s": round(_probe_duration(final), 3),
        "loudness": {"integrated_lufs": lufs, "true_peak_dbtp": tp},
        "delivery": delivery,
        "bgm": {"path": spec.bgm_path, "gain": spec.bgm_gain},
    }
    (spec.product_dir / "assembly.json").write_text(
        json.dumps(meta, indent=2), encoding="utf-8")
    logger.info("film.assembled", **meta)
    return final


# ---------------------------------------------------------------------------
# entry
# ---------------------------------------------------------------------------

async def run_film(spec: FilmSpec, provider, *, reuse_clips: bool = True) -> Path:
    """The whole film, gated. Raises FilmError at the FIRST unpassable gate."""
    still_verdicts = await gate_stills(spec, provider)
    plan = build_plan(spec)
    save_plan(plan, spec.product_dir)
    plan = await gate_clips(spec, plan, provider, reuse=reuse_clips)
    gate_boundaries(spec, plan)
    final = assemble(spec, plan)
    save_plan(plan, spec.product_dir)
    logger.info("film.done", final=str(final),
                stills={k: v.as_dict() for k, v in still_verdicts.items()})
    return final
