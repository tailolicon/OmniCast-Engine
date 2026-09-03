"""Character anchor set — the reference images that hold a mascot's identity.

WS1 (visual consistency): the text DNA block alone cannot stop per-frame face
drift — image models re-interpret text every call. The root fix is REFERENCE
CONDITIONING: generate (once, cached) a small anchor set of the character from
the DNA, then attach those images as Flow "Ingredients" to every scene
generation (FlowProvider.set_reference_images / env FLOW_INGREDIENTS).

Layers, cheapest first:
  1. channel `character_portrait` (operator-supplied) — always anchor #1;
  2. cached anchors from a previous run — free;
  3. fresh anchors generated from the DNA block via the image provider.

Anchors live in output/_characters/anchors/<slug>/anchor_NN.png next to the
DNA cache. Everything is best-effort: no provider / a failed generation just
yields fewer (or zero) anchors and the caller falls back to text-DNA only.
"""

from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path

# implementation/ root (this file: implementation/src/omnicast/media/…)
_ROOT = Path(__file__).resolve().parents[3]
ANCHOR_DIR = _ROOT / "output" / "_characters" / "anchors"

# Poses chosen so the model sees the identity from several angles — a single
# frontal portrait lets profile shots drift.
ANCHOR_POSES = (
    "front-facing head-and-shoulders portrait, neutral expression, plain background",
    "three-quarter view upper-body shot, plain background",
    "full-body standing shot, plain background",
)

MAX_ANCHORS_DEFAULT = 3


def _slug(text: str) -> str:
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in text.strip())[:40]
    h = hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]
    return f"{safe}_{h}" if safe else h


def build_anchor_prompts(dna_block: str, style_prefix: str = "",
                         count: int = MAX_ANCHORS_DEFAULT) -> list[str]:
    """Compose one prompt per anchor pose from the DNA block (+ channel style
    prefix so the anchors match the video's art direction)."""
    if not dna_block:
        return []
    prompts = []
    for pose in ANCHOR_POSES[:max(1, count)]:
        parts = [p for p in (style_prefix.strip(), dna_block.strip()) if p]
        parts.append(f"Character reference sheet shot: {pose}. "
                     "Single character only, no text, no watermark.")
        prompts.append(". ".join(parts))
    return prompts


def cached_anchor_paths(dna_block: str) -> list[Path]:
    """Existing non-empty anchors for this DNA, oldest naming order."""
    d = ANCHOR_DIR / _slug(dna_block)
    if not d.exists():
        return []
    out = [p for p in sorted(d.glob("anchor_*.png"))
           if p.is_file() and p.stat().st_size > 0]
    return out


async def ensure_anchor_images(
    dna_block: str,
    provider=None,
    *,
    style_prefix: str = "",
    count: int = MAX_ANCHORS_DEFAULT,
    anchor_dir: Path | None = None,
) -> list[str]:
    """Return up to `count` anchor image paths for this DNA — cached if
    available, generated via `provider.generate(prompt, output_path=…)`
    otherwise. Partial results are fine; failures never raise."""
    if not dna_block:
        return []
    base = (anchor_dir or ANCHOR_DIR) / _slug(dna_block)
    have = [p for p in sorted(base.glob("anchor_*.png"))
            if p.is_file() and p.stat().st_size > 0]
    if len(have) >= count or provider is None:
        return [str(p) for p in have[:count]]
    base.mkdir(parents=True, exist_ok=True)
    prompts = build_anchor_prompts(dna_block, style_prefix, count)
    out: list[str] = [str(p) for p in have]
    for n, prompt in enumerate(prompts):
        dst = base / f"anchor_{n:02d}.png"
        if dst.exists() and dst.stat().st_size > 0:
            if str(dst) not in out:
                out.append(str(dst))
            continue
        try:
            await provider.generate(prompt, output_path=str(dst))
            if dst.exists() and dst.stat().st_size > 0:
                out.append(str(dst))
        except Exception as exc:  # anchor gen is best-effort
            print(f"      [anchor] generation failed ({str(exc)[:80]}) — "
                  f"continuing with {len(out)} anchor(s)")
    return out[:count]


def resolve_reference_images(
    channel: dict | None,
    dna_block: str = "",
    provider=None,
    *,
    count: int = MAX_ANCHORS_DEFAULT,
) -> list[str]:
    """Full resolution order for a channel's ingredient set (sync wrapper):

      1. explicit `reference_images` list in channels/<id>.json (paths);
      2. `character_portrait` (operator portrait) — always first if present;
      3. cached/generated anchors from the DNA block.

    Returns [] when the channel has no recurring character — callers then skip
    ingredients entirely (behavior identical to pre-WS1).
    """
    channel = channel or {}
    out: list[str] = []
    for p in channel.get("reference_images") or []:
        try:
            if Path(p).exists() and Path(p).stat().st_size > 0:
                out.append(str(Path(p).resolve()))
        except Exception:
            continue
    portrait = channel.get("character_portrait")
    if portrait:
        try:
            pp = Path(portrait)
            if pp.exists() and pp.stat().st_size > 0 and str(pp.resolve()) not in out:
                out.insert(0, str(pp.resolve()))
        except Exception:
            pass
    if len(out) >= count or not dna_block:
        return out[:count]
    try:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop is None:
            anchors = asyncio.run(ensure_anchor_images(
                dna_block, provider, count=count - len(out)))
        else:  # already inside an event loop — cached anchors only (no await)
            anchors = [str(p) for p in cached_anchor_paths(dna_block)]
    except Exception:
        anchors = []
    for a in anchors:
        if a not in out:
            out.append(a)
    return out[:count]
