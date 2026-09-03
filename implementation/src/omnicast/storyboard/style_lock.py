"""Style lock: keep every keyframe in ONE art style before money is spent.

WHY THIS EXISTS. Demo ep1 v4 drifted from crisp anime-cel (first frame) to soft
watercolor (last frame). Two compounding causes, both found by measurement:

  1. ENDPOINT STILLS WERE DIRTY. The FLF end-frames for S4-S6 (k5end/k6end/
     k7end) measured 0.06-0.24 lineart-distance from the K1 anchor while the
     approved stills sat at 0.01-0.03. Each clip interpolates TOWARD its end
     frame, so a painterly endpoint drags the whole clip's style with it.
  2. TAIL-CARRY COMPOUNDED SOFTNESS. Using the real video tail of clip N as the
     start image of clip N+1 re-feeds the video model its own neural softening
     (tail(F1) already measures 0.17 from head(F1) inside ONE clip). Chained
     five times this is visible to the naked eye.

WHAT THE REFERENCE REPOS DO (read, not assumed):

  * AIComicBuilder `LAST_FRAME_STYLE_MATCHING` (registry.ts): the last frame is
    a fresh IMAGE-MODEL generation with the shot's FIRST frame attached and the
    instruction "你必须精确匹配首帧图像的画风 … 不可协商" (match the first
    frame's art style exactly — non-negotiable). Video then interpolates
    between two clean stills. Never between a still and a video frame.
  * StoryGen-Atelier: shot 1's image is the visual reference for shots 2..N —
    a FIXED anchor, not a rolling chain, precisely because a rolling chain
    accumulates drift each hop.
  * ArcReel `STYLE_ANALYSIS_PROMPT`: extract style descriptors from the anchor
    once, then inject the same style string into every downstream prompt.
  * Orkas stage-consistency: "verify keyframe BEFORE paying to animate" —
    re-roll the cheap image, never the expensive video.

THE GATE. `lineart_distance` compares contrast-normalized gradient energy, hard-edge
ratio, saturation spread and luminance-normalized colorfulness — the signature
of cel line-art versus watercolor wash — while staying blind to hue and
exposure, because an INTENDED lighting change (the lantern lighting up) must
not trip the gate. Calibrated on the v4 demo data with the normalized metric:

    same-style stills  vs anchor: 0.004-0.022   (K2b, K3, K4)
    drifted  stills    vs anchor: 0.037-0.191   (k5end, k6end, k7end)

`STILL_GATE = 0.030` splits the two populations. Adjacent-boundary video
frames of the ACCEPTED v4 cuts measured 0.013-0.057 on the same metric, so
`BOUNDARY_GATE = 0.07` flags a real world-jump without tripping on codec
noise. Full-film span numbers are reported but NOT gated: intended lighting
arcs and in-clip neural softening dominate that signal (head(F1)->tail(F1) is
already 0.18), so a hard gate there would only produce false alarms.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import structlog
from PIL import Image

logger = structlog.get_logger()

#: Reject a candidate STILL whose lineart distance from the film's style anchor
#: exceeds this. Calibrated: approved stills max 0.022, drifted min 0.037.
STILL_GATE = 0.030
#: Reject an adjacent tail(N)|head(N+1) video-frame pair above this.
BOUNDARY_GATE = 0.07
#: Bounded re-roll: after this many failed regenerations of one still, stop
#: and surface the failure instead of burning generations (Orkas repair-budget
#: spirit — three strikes on the same content signature blocks the step).
MAX_STILL_REROLLS = 3
#: A candidate keyframe whose NCC against the PREVIOUS keyframe exceeds this is
#: a copy, not a new story beat — the mandated delta did not happen. Calibrated:
#: genuine pose-changes in the same locked room measure 0.94-0.973 (background
#: dominates); duplicate downloads and reference-copies measure 1.0000.
MAX_KEYFRAME_NCC = 0.985

_ANALYSIS_SIZE = 256


@dataclass(frozen=True)
class StyleVector:
    """Cheap style signature of one image. All scalars; safe to json-dump."""

    grad: float       # mean gradient magnitude — line art carries dense ink edges
    strong: float     # fraction of hard edges (|dx| > 0.12) — cel vs wash
    sat_std: float    # saturation spread — flat cel fills vs watercolor gradients
    col: float        # Hasler-Süsstrunk colorfulness
    sat_mean: float   # kept for reporting; not used by lineart distance

    def as_dict(self) -> dict:
        return {
            "grad": round(self.grad, 5),
            "strong": round(self.strong, 5),
            "sat_std": round(self.sat_std, 5),
            "col": round(self.col, 5),
            "sat_mean": round(self.sat_mean, 5),
        }


@dataclass(frozen=True)
class StyleVerdict:
    passed: bool
    distance: float
    threshold: float
    parts: dict

    def as_dict(self) -> dict:
        return {
            "passed": self.passed,
            "distance": round(self.distance, 4),
            "threshold": self.threshold,
            "parts": {k: round(v, 4) for k, v in self.parts.items()},
        }


def _load(path: str | Path) -> np.ndarray:
    img = Image.open(path).convert("RGB").resize(
        (_ANALYSIS_SIZE, _ANALYSIS_SIZE), Image.LANCZOS)
    return np.asarray(img, dtype=np.float32) / 255.0


def style_vector(path: str | Path) -> StyleVector:
    """All components are contrast/brightness-normalized: a uniformly dimmer
    frame (the lantern-glow scene) must produce the SAME vector, because an
    intended lighting arc is story, not style. Verified by test + the K-still
    calibration set."""
    arr = _load(path)
    r, g, b = arr[..., 0], arr[..., 1], arr[..., 2]
    mx = arr.max(-1)
    mn = arr.min(-1)
    sat = (mx - mn) / (mx + 1e-8)          # already brightness-invariant
    gray = arr.mean(-1)
    contrast = float(gray.std()) + 1e-6
    sx = np.abs(np.diff(gray, axis=1)) / contrast
    sy = np.abs(np.diff(gray, axis=0)) / contrast
    lum = float(gray.mean()) + 1e-6
    rg = (r - g) / lum
    yb = (0.5 * (r + g) - b) / lum
    col = float(np.sqrt(rg.std() ** 2 + yb.std() ** 2)
                + 0.3 * np.sqrt(rg.mean() ** 2 + yb.mean() ** 2))
    return StyleVector(
        grad=float(sx.mean() + sy.mean()),
        strong=float((sx > 0.55).mean()),  # 0.55 contrast units ≈ hard ink edge
        sat_std=float(sat.std()),
        col=col,
        sat_mean=float(sat.mean()),
    )


def _rel(a: float, b: float) -> float:
    return abs(a - b) / max(a, b, 1e-6)


def lineart_distance(a: StyleVector, b: StyleVector) -> tuple[float, dict]:
    """Lighting-blind style distance. 0 = same rendering language.

    sat_std is REPORTED but not scored: it moves with scene lighting (glow
    scenes compress saturation spread) while contributing little separation —
    on the calibration set the three scored axes alone split good/bad wider
    (0.020 vs 0.043) than the four-axis mix did.
    """
    parts = {
        "grad": _rel(a.grad, b.grad),
        "strong": _rel(a.strong, b.strong),
        "sat_std": _rel(a.sat_std, b.sat_std),
        "col": _rel(a.col, b.col),
    }
    total = (0.40 * parts["grad"] + 0.30 * parts["strong"]
             + 0.30 * parts["col"])
    return total, parts


def check_still(candidate: str | Path, anchor: StyleVector,
                threshold: float = STILL_GATE) -> StyleVerdict:
    """Gate one keyframe still against the film's fixed style anchor."""
    dist, parts = lineart_distance(anchor, style_vector(candidate))
    verdict = StyleVerdict(dist <= threshold, dist, threshold, parts)
    logger.info("style_lock.still", candidate=str(candidate),
                **verdict.as_dict())
    return verdict


def check_boundary(tail_frame: str | Path, head_frame: str | Path,
                   threshold: float = BOUNDARY_GATE) -> StyleVerdict:
    """Gate one cut: last frame of clip N vs first frame of clip N+1."""
    dist, parts = lineart_distance(style_vector(tail_frame),
                                   style_vector(head_frame))
    verdict = StyleVerdict(dist <= threshold, dist, threshold, parts)
    logger.info("style_lock.boundary", tail=str(tail_frame),
                head=str(head_frame), **verdict.as_dict())
    return verdict


def content_delta(a: str | Path, b: str | Path) -> float:
    """Normalized cross-correlation of two frames (1.0 = same picture).

    The style gate cannot see WHAT is in the frame — a pixel-faithful copy of
    the previous keyframe passes it perfectly (that is exactly how the first
    pipeline run failed: a stale-download bug returned the K4-era image for
    three different keyframes and the style gate waved all three through).
    This catches it: consecutive keyframes must differ by at least the story
    beat, so NCC above MAX_KEYFRAME_NCC means "no new content, reject".
    """
    def _norm_gray(path: str | Path) -> np.ndarray:
        img = Image.open(path).convert("L").resize((128, 128), Image.LANCZOS)
        arr = np.asarray(img, dtype=np.float32)
        return (arr - arr.mean()) / (arr.std() + 1e-6)

    return float((_norm_gray(a) * _norm_gray(b)).mean())


def film_span_report(first_head: str | Path,
                     tails: list[str | Path]) -> list[dict]:
    """Soft telemetry: drift of every clip tail vs the film's first frame.

    NOT a gate — intended lighting arcs and in-clip softening dominate this
    number (see module docstring). Written to plan.json so a human (or a later
    vision-LLM pass, the AIComicBuilder route) can see the trend.
    """
    anchor = style_vector(first_head)
    rows = []
    for tail in tails:
        dist, parts = lineart_distance(anchor, style_vector(tail))
        rows.append({"tail": str(tail), "distance": round(dist, 4),
                     "parts": {k: round(v, 4) for k, v in parts.items()}})
    logger.info("style_lock.film_span", rows=rows)
    return rows


# ---------------------------------------------------------------------------
# Prompt-side style lock (ArcReel STYLE_ANALYSIS + AIComicBuilder blocks).
# The pixel gate above REJECTS drift; these strings PREVENT it at gen time.
# ---------------------------------------------------------------------------

#: Fixed rendering-language contract for the Miko film. Injected into every
#: still prompt AND every video prompt. One string, never paraphrased per shot
#: (StoryGen: "Global style string — same appliedStyle every call").
STYLE_LOCK_MIKO = (
    "Hand-drawn Japanese anime cel illustration: crisp dark ink outlines, "
    "flat cel-shading with soft two-tone shadows, storybook warmth, clean "
    "linework everywhere. NOT watercolor, NOT soft painterly wash, NOT "
    "photorealistic; no visible brush texture."
)

#: AIComicBuilder LAST_FRAME_STYLE_MATCHING, translated to our single-image
#: providers: the anchor image rides along and the text pins its authority.
STYLE_MATCH_CLAUSE = (
    "CRITICAL - STYLE MATCH (highest priority): the attached reference image "
    "defines the art style. Match its rendering language exactly - same line "
    "weight, same cel shading, same texture treatment. Do not change or blend "
    "styles. Only pose, expression and lighting may differ as described."
)

#: Video prompts get the light version: the start frame already carries the
#: style; the model just must not walk away from it (seedance i2v rule:
#: "prompt only what the image cannot show").
VIDEO_STYLE_CLAUSE = (
    "Keep the exact hand-drawn anime cel style of the start frame from the "
    "first frame to the last - crisp ink outlines and flat cel colors "
    "throughout; no style change, no watercolor softening."
)
