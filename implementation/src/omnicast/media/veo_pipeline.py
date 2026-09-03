"""Scene -> Veo clip pipeline: Flow (browser, free credits) first, Gemini Veo 3
API fallback, with tail-frame carry-forward where the active provider accepts
an image input.

Ported patterns (see docs in _refs, research 2026-08-01):
  * StoryGen-Atelier / LocalMiniDrama — tail-frame chaining: the last frame of
    clip N seeds clip N+1 so adjacent clips visually interlock
    (`tailFrameLinkService.js`: ffmpeg -sseof -1 ... -frames:v 1).
  * ArcReel `lib/video_backends/gemini.py` — declarative capability table
    validated BEFORE any paid call (durations, refs=>8s, resolution=>8s).
  * ArcReel prompt research — the motion prompt must not re-describe what the
    seed image already shows; negative prompt is appended as a text tail, not
    a parameter, so behaviour is identical across backends.
  * Orkas stage-generate — sticky provider demotion: when a provider fails in
    a way that will repeat (blocked profile, exhausted credits), stop offering
    it clips instead of paying the timeout per clip.

FlowProvider.convert() currently ignores image_path (text-to-video only), so
carry-forward is automatically skipped while Flow is the active provider and
resumes if the run demotes to the Gemini API. When Flow grows image->video
support this module needs no changes: set FLOW_ACCEPTS_IMAGE = True.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import structlog

logger = structlog.get_logger()

# ── Capability table (ArcReel pattern: declare, validate pre-flight) ──────────
VEO_DURATIONS = (4, 6, 8)          # veo-3.x supported clip lengths (seconds)
REFERENCE_IMAGE_DURATION = 8       # reference images force 8s on veo-3.1
HIGH_RES_DURATION = 8              # 1080p/4k force 8s
FLOW_ACCEPTS_IMAGE = False         # flip when FlowProvider wires image->video

# Veo renders text/watermark-ish artifacts unless told not to; a text tail is
# provider-neutral (parameter channels differ between Flow and the API).
NEGATIVE_TAIL = "No on-screen text, no subtitles, no watermark, no logos."


def clamp_duration(seconds: float) -> int:
    """Nearest supported Veo duration, preferring the first >= request.

    A narration slot of 5.2s gets a 6s clip (loop-free coverage); anything
    above 8s gets 8 and the composer loops it (veo_motion_scene already
    handles in_offset de-looping)."""
    for d in VEO_DURATIONS:
        if seconds <= d:
            return d
    return VEO_DURATIONS[-1]


def preflight_duration(duration: int, *, has_image: bool, resolution: str = "720p") -> int:
    """Validate/repair a requested duration against Veo constraints.

    Mirrors ArcReel `_validate_duration_constraints`, but repairs instead of
    raising: this pipeline is called with narration-derived durations, and the
    nearest legal value is always the right answer for a b-roll clip."""
    if duration not in VEO_DURATIONS:
        duration = clamp_duration(duration)
    if has_image and duration != REFERENCE_IMAGE_DURATION:
        duration = REFERENCE_IMAGE_DURATION
    if resolution in ("1080p", "4k") and duration != HIGH_RES_DURATION:
        duration = HIGH_RES_DURATION
    return duration


def build_motion_prompt(motion: str, *, seeded: bool) -> str:
    """Final prompt text for one clip.

    `motion` should describe MOTION ONLY (action chain, camera move, ambiance).
    When a seed image is attached, any subject/style prose would fight the
    pixels ("where the words disagree with the pixels, the prose becomes a
    drift instruction" — seedance prompt-compiler), so the caller is trusted
    to pass motion-only text and we only add the neutral negative tail."""
    text = motion.strip()
    if seeded and not text:
        text = "Subtle natural motion continuing the scene, slow cinematic push in."
    return f"{text} {NEGATIVE_TAIL}".strip()


def extract_last_frame(clip: Path, out_jpg: Path) -> Path | None:
    """Last frame of a clip as JPEG (LocalMiniDrama tail-frame pattern).

    Returns None instead of raising: carry-forward is an enhancement, and a
    frame-extraction failure must never kill a paid render run."""
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-sseof", "-1", "-i", str(clip),
             "-update", "1", "-q:v", "2", "-frames:v", "1", str(out_jpg)],
            check=True, capture_output=True, timeout=60,
        )
        return out_jpg if out_jpg.exists() and out_jpg.stat().st_size > 0 else None
    except Exception as exc:  # noqa: BLE001 — any ffmpeg failure is non-fatal here
        logger.warning("tail-frame extraction failed", clip=str(clip), error=str(exc)[:120])
        return None


@dataclass
class VeoClipSpec:
    """One scene's request: motion prompt + narration slot."""

    index: int
    motion_prompt: str
    narration_seconds: float = 8.0
    seed_image: str = ""          # optional explicit first-frame image


@dataclass
class VeoClipResult:
    index: int
    path: Path | None
    provider: str = ""            # "flow" | "gemini" | ""
    error: str = ""
    carried_frame: str = ""       # tail frame extracted from this clip


@dataclass
class VeoPipelineReport:
    clips: list[VeoClipResult] = field(default_factory=list)
    demoted_from: str = ""        # provider that was dropped mid-run
    demotion_reason: str = ""

    @property
    def ok_count(self) -> int:
        return sum(1 for c in self.clips if c.path is not None)

    def by_provider(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for c in self.clips:
            if c.path is not None:
                out[c.provider] = out.get(c.provider, 0) + 1
        return out


class VeoScenePipeline:
    """Serial clip generator with sticky fallback and carry-forward.

    Serial on purpose: the Flow browser session is single-tab, each Veo clip
    takes minutes, and the Gemini API path bills real money — one in-flight
    clip keeps failure blast radius to a single clip."""

    def __init__(
        self,
        *,
        provider_order: tuple[str, ...] = ("flow", "gemini"),
        carry_forward: bool = True,
        work_dir: str | Path = ".",
        wait_s: int = 600,
    ) -> None:
        self.provider_order = provider_order
        self.carry_forward = carry_forward
        self.work_dir = Path(work_dir)
        self.wait_s = wait_s
        self._providers: dict[str, object] = {}
        self._dead: dict[str, str] = {}   # provider_id -> reason (sticky)

    # -- provider access ------------------------------------------------------
    def _get(self, provider_id: str):
        if provider_id not in self._providers:
            from omnicast.media.providers.registry import get_video_provider
            self._providers[provider_id] = get_video_provider(provider_id)
        return self._providers[provider_id]

    def _alive_order(self) -> list[str]:
        return [p for p in self.provider_order if p not in self._dead]

    def demote(self, provider_id: str, reason: str) -> None:
        """Sticky removal — a blocked Flow profile or exhausted credit balance
        will fail every subsequent clip too; don't pay the timeout N times."""
        if provider_id not in self._dead:
            self._dead[provider_id] = reason
            logger.warning("veo provider demoted", provider=provider_id, reason=reason[:160])

    def _provider_takes_image(self, provider_id: str) -> bool:
        return provider_id != "flow" or FLOW_ACCEPTS_IMAGE

    # -- generation -----------------------------------------------------------
    async def _one_clip(self, provider_id: str, spec: VeoClipSpec,
                        seed_image: str, out_path: Path) -> Path:
        provider = self._get(provider_id)
        takes_image = self._provider_takes_image(provider_id)
        image_path = seed_image if takes_image else ""
        duration = preflight_duration(
            clamp_duration(spec.narration_seconds), has_image=bool(image_path))
        prompt = build_motion_prompt(spec.motion_prompt, seeded=bool(image_path))
        kwargs: dict = dict(duration=duration, output_path=str(out_path))
        if provider_id == "flow":
            kwargs["wait_s"] = self.wait_s
        result = await provider.convert(image_path, prompt, **kwargs)
        return Path(result)

    async def generate(self, specs: list[VeoClipSpec],
                       on_clip=None) -> VeoPipelineReport:
        """`on_clip(result)` fires after each clip (success or failure) so a
        caller can stream progress to a status UI without threading state in."""
        report = VeoPipelineReport()
        carried = ""   # tail frame path carried across clips
        for spec in specs:
            out_path = self.work_dir / f"scene_{spec.index:02d}_veo.mp4"
            seed = spec.seed_image or (carried if self.carry_forward else "")
            result = VeoClipResult(index=spec.index, path=None)
            for provider_id in self._alive_order():
                try:
                    clip = await self._one_clip(provider_id, spec, seed, out_path)
                    result.path, result.provider = clip, provider_id
                    break
                except Exception as exc:  # noqa: BLE001 — provider boundary
                    msg = f"{type(exc).__name__}: {str(exc)[:200]}"
                    result.error = msg
                    logger.warning("veo clip failed", scene=spec.index,
                                   provider=provider_id, error=msg)
                    # Session-level failures repeat on every clip -> demote.
                    lowered = msg.lower()
                    if any(tok in lowered for tok in (
                            "flowblocked", "credit", "quota", "login",
                            "api_key", "google_api_key", "permission")):
                        self.demote(provider_id, msg)
                        if not report.demoted_from:
                            report.demoted_from = provider_id
                            report.demotion_reason = msg
                    # else: transient — next provider gets this clip, the
                    # failed provider stays in rotation for the next one.
            if result.path is not None and self.carry_forward:
                frame = extract_last_frame(
                    result.path, self.work_dir / f"scene_{spec.index:02d}_tail.jpg")
                if frame is not None:
                    result.carried_frame = str(frame)
                    carried = str(frame)
                else:
                    carried = ""   # broken chain must not reuse a stale frame
            report.clips.append(result)
            if on_clip is not None:
                try:
                    on_clip(result)
                except Exception:  # noqa: BLE001 — progress UI must not kill the run
                    pass
            if not self._alive_order():
                logger.error("all veo providers demoted; stopping",
                             done=report.ok_count, total=len(specs))
                break
        return report

    def close(self) -> None:
        for provider in self._providers.values():
            close = getattr(provider, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:  # noqa: BLE001 — teardown must not raise
                    pass


async def generate_veo_clips(
    prompts: list[str],
    narration_seconds: list[float] | None = None,
    *,
    work_dir: str | Path,
    provider_order: tuple[str, ...] = ("flow", "gemini"),
    carry_forward: bool = True,
    wait_s: int = 600,
    on_clip=None,
) -> VeoPipelineReport:
    """Convenience wrapper used by render_real_video's veo mode."""
    durations = narration_seconds or [8.0] * len(prompts)
    specs = [
        VeoClipSpec(index=i, motion_prompt=p, narration_seconds=durations[i])
        for i, p in enumerate(prompts)
    ]
    pipeline = VeoScenePipeline(
        provider_order=provider_order, carry_forward=carry_forward,
        work_dir=work_dir, wait_s=wait_s)
    try:
        return await pipeline.generate(specs, on_clip=on_clip)
    finally:
        pipeline.close()
