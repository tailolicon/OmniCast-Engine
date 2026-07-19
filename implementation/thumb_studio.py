"""Thumb Studio — thumbnail generation DECOUPLED from the render pipeline.

Operator policy (2026-07-09): thumbnails are FLOW-ONLY and human-curated.
This module generates N candidates per product using DIFFERENT clickbait
angles, lets the operator pick the official one, and supports regeneration
with a free-text OPERATOR NOTE that is injected into the Flow prompt.

Layout inside a product folder:
    thumbs/cand_YYYYmmdd_HHMMSS_<angle>.png   — candidates (1280x720)
    thumbs/meta.json                          — text/title/angle/note per cand
    video_thumb.png                           — the SELECTED official thumb

CLI (host):
    python thumb_studio.py generate <product_dir> [--count 3] [--note "..."]
    python thumb_studio.py select   <product_dir> <candidate_filename>
"""
from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# Premium photoreal base — deliberately MORE aggressive than the old render
# prompt (operator feedback: "chưa đủ clickbait").
THUMB_STYLE = (
    "photorealistic cinematic photograph, EXTREME exaggerated facial expression, "
    "vivid rim lighting, teal and magenta studio lighting, shallow depth of field, "
    "hyper-detailed, ultra high contrast, punchy saturated colors, bright key light "
    "on subject"
)
THUMB_NEG = (
    "flat vector, cartoon, illustration, clipart, 2d, anime, drawing, "
    "low detail, blurry, watermark, logo, dim, dark, muddy, "
    "deformed hands, extra fingers, distorted face, "
    "gibberish text, misspelled text, garbled letters"
)

# Distinct clickbait ANGLES — each candidate gets one, so the operator chooses
# between genuinely different framings instead of three near-identical images.
ANGLES: list[tuple[str, str]] = [
    ("shock_face",
     "EXTREME CLOSE-UP of the subject's face filling half the frame, jaw dropped "
     "or hand clasped over mouth, wide horrified eyes looking at the culprit "
     "object in the foreground corner, skin slightly pale, maximum emotional drama"),
    ("culprit_redmark",
     "dramatic macro shot of the CULPRIT object (the food/drink/mistake of the "
     "video) center frame under an ominous spotlight, a BOLD hand-drawn RED X "
     "or red circle-and-slash over it, dark vignette background, danger mood"),
    ("consequence_split",
     "split composition: LEFT half the subject happily engaging with the culprit "
     "object in warm light, RIGHT half the SAME subject in agony (clutching "
     "stomach, grimacing) in cold blue night light, a bold red arrow sweeping "
     "left-to-right connecting cause to consequence"),
    ("pointing_panic",
     "subject leaning INTO the camera pointing directly at the viewer with an "
     "urgent warning expression, the culprit object glowing red in the "
     "foreground, lens slightly wide for aggressive perspective distortion"),
]


def _flow_provider():
    from omnicast.media.providers.registry import get_image_provider
    return get_image_provider("flow")


def _settings():
    from omnicast.config.settings import get_settings
    return get_settings()


def _load_channel_meta(product_dir: Path) -> dict:
    # products/<channel>/<slug> → channels/<channel>.json
    channel_id = product_dir.parent.name
    p = ROOT / "channels" / f"{channel_id}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def _normalize(src: Path, dst: Path) -> None:
    from PIL import Image
    im = Image.open(src).convert("RGB")
    tw, th = 1280, 720
    sc = max(tw / im.width, th / im.height)
    im = im.resize((int(im.width * sc), int(im.height * sc)))
    x0 = (im.width - tw) // 2
    y0 = (im.height - th) // 2
    im.crop((x0, y0, x0 + tw, y0 + th)).save(dst)


def generate_candidates(product_dir: str | Path, note: str = "",
                        count: int = 4, per_angle: int = 2) -> list[dict]:
    """Generate a BATCH of Flow thumb candidates: `count` angles × `per_angle`
    variations each (Flow's temperature makes every variation distinct).

    `note` = operator direction, injected verbatim into every prompt with
    MUST-FOLLOW priority. FLOW-ONLY. Uses the provider's wave-based
    generate_batch with per-image retry — partial shortfalls keep whatever
    landed (operator picks among survivors); ZERO images raises.
    """
    import clickbait

    product_dir = Path(product_dir)
    script_text = (product_dir / "script.txt").read_text(encoding="utf-8")
    channel_meta = _load_channel_meta(product_dir)

    cb = clickbait.generate_clickbait(script_text, channel_meta)
    if not cb or not cb.get("thumb_prompt"):
        raise RuntimeError("clickbait generation failed — no thumb_prompt")
    ttext = (cb.get("thumb_text") or "").strip().upper()

    tdir = product_dir / "thumbs"
    tdir.mkdir(exist_ok=True)
    meta_path = tdir / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {"candidates": []}

    provider = _flow_provider()
    note_block = (f" OPERATOR DIRECTION (MUST FOLLOW EXACTLY, overrides "
                  f"everything else): {note.strip()}." if note.strip() else "")

    stamp = time.strftime("%Y%m%d_%H%M%S")
    per_angle = max(1, min(int(per_angle), 4))
    prompts: list[str] = []
    raw_paths: list[str] = []
    slots: list[tuple[str, int, Path]] = []
    for angle_id, angle_prompt in ANGLES[:max(1, count)]:
        tp = (
            f"{THUMB_STYLE}, {cb['thumb_prompt']}. FRAMING: {angle_prompt}."
            f"{note_block} "
            f"Large bold all-caps YouTube thumbnail headline text reading "
            f"exactly \"{ttext}\" placed where it does NOT cover the face — "
            f"thick sans-serif, heavy black outline, one word in bright yellow, "
            f"perfectly spelled, highly legible, MrBeast-style impactful "
            f"thumbnail typography"
        )
        for v in range(per_angle):
            raw = tdir / f"_raw_{stamp}_{angle_id}_v{v + 1}.png"
            prompts.append(tp)
            raw_paths.append(str(raw.resolve()))
            slots.append((angle_id, v + 1, raw))

    print(f"[batch] {len(prompts)} images ({count} angles x {per_angle} variations)...")
    if per_angle > 1 and hasattr(provider, "generate_multi"):
        # Flow's NATIVE x2/x3/x4 output tabs: ONE submission per angle yields
        # all variations (0 credits, 4x fewer submits → gentler on anti-abuse).
        async def _run_all() -> None:
            for k in range(0, len(prompts), per_angle):
                await provider.generate_multi(
                    prompts[k], raw_paths[k:k + per_angle],
                    resolution=(1280, 720))
        asyncio.run(_run_all())
    else:
        asyncio.run(provider.generate_batch(
            prompts, raw_paths, resolution=(1280, 720)))

    made: list[dict] = []
    for angle_id, v, raw in slots:
        if not raw.exists() or raw.stat().st_size == 0:
            print(f"[miss] {angle_id} v{v} — Flow shortfall (kept the rest)")
            continue
        cand = tdir / f"cand_{stamp}_{angle_id}_v{v}.png"
        _normalize(raw, cand)
        raw.unlink(missing_ok=True)
        entry = {"file": cand.name, "angle": angle_id, "variation": v,
                 "text": ttext, "title": cb.get("title", ""),
                 "note": note.strip(), "ts": stamp}
        meta["candidates"].append(entry)
        made.append(entry)
        print(f"[cand] {cand.name}")
    if not made:
        raise RuntimeError("Flow produced ZERO thumbnail candidates — "
                           "FLOW-ONLY policy, no fallback")

    meta["title"] = cb.get("title", "")
    meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False),
                         encoding="utf-8")
    return made


def select(product_dir: str | Path, candidate: str) -> Path:
    """Promote one candidate to the official video_thumb.png (+title file)."""
    import shutil
    product_dir = Path(product_dir)
    src = product_dir / "thumbs" / candidate
    if not src.exists():
        raise FileNotFoundError(f"candidate not found: {candidate}")
    dst = product_dir / "video_thumb.png"
    shutil.copyfile(src, dst)
    meta_path = product_dir / "thumbs" / "meta.json"
    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        meta["selected"] = candidate
        for c in meta.get("candidates", []):
            if c.get("file") == candidate and c.get("title"):
                (product_dir / "video_title.txt").write_text(
                    c["title"], encoding="utf-8")
        meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False),
                             encoding="utf-8")
    print(f"[selected] {candidate} -> video_thumb.png")
    return dst


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("generate")
    g.add_argument("product_dir")
    g.add_argument("--count", type=int, default=4)
    g.add_argument("--per-angle", type=int, default=2, dest="per_angle")
    g.add_argument("--note", default="")
    s = sub.add_parser("select")
    s.add_argument("product_dir")
    s.add_argument("candidate")
    a = ap.parse_args()
    if a.cmd == "generate":
        generate_candidates(a.product_dir, note=a.note, count=a.count,
                            per_angle=a.per_angle)
    else:
        select(a.product_dir, a.candidate)
