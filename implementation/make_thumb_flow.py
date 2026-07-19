"""FLOW-ONLY thumbnail for the Shot Day Dinner product (operator policy).

Mirrors render_real_video's Flow thumb path exactly: clickbait thumb_prompt +
premium photoreal style, headline text baked by Flow (nano-banana), normalized
to 1280x720. No fallback — fails loudly if Flow can't deliver.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PROD = ROOT / "output/products/beat_glp1_nausea/20260709_0234_shot_day_dinner_what_you_eat_tonight_decides_tomor"

import clickbait  # noqa: E402
from omnicast.config.settings import get_settings  # noqa: E402
from omnicast.media.providers.registry import get_image_provider  # noqa: E402

THUMB_STYLE = (
    "photorealistic cinematic photograph, dramatic exaggerated "
    "facial expression, vivid rim lighting, teal and magenta studio "
    "lighting, shallow depth of field, hyper-detailed, high contrast"
)
THUMB_NEG = (
    "flat vector, cartoon, illustration, clipart, 2d, anime, drawing, "
    "low detail, blurry, watermark, logo, "
    "deformed hands, extra fingers, distorted face, "
    "gibberish text, misspelled text, garbled letters"
)


def main() -> None:
    settings = get_settings()
    channel_meta = json.loads((ROOT / "channels/beat_glp1_nausea.json").read_text(encoding="utf-8"))
    script_text = (PROD / "script.txt").read_text(encoding="utf-8")

    cb = clickbait.generate_clickbait(script_text, channel_meta)
    if not cb or not cb.get("thumb_prompt"):
        raise SystemExit("clickbait generation failed — no thumb_prompt")
    ttext = (cb.get("thumb_text") or "").strip().upper()
    print(f"[cb] title: {cb['title']!r}")
    print(f"[cb] thumb_text: {ttext!r}")

    provider = get_image_provider("flow")
    tp = (
        f"{THUMB_STYLE}, {cb['thumb_prompt']}, bold dramatic subject. "
        f"Large bold all-caps YouTube thumbnail headline text reading "
        f"exactly \"{ttext}\" placed in a corner — thick sans-serif, "
        f"heavy black outline, one word in bright yellow, perfectly spelled, "
        f"highly legible, MrBeast-style impactful thumbnail typography"
    )
    bg = PROD / "_assets" / "_thumb_bg.png"
    asyncio.run(provider.generate(
        tp, negative=THUMB_NEG, model=settings.flow_image_model,
        resolution=(1280, 720), output_path=str(bg.resolve())))
    if not bg.exists() or bg.stat().st_size == 0:
        raise SystemExit("Flow produced no image")

    from PIL import Image
    im = Image.open(bg).convert("RGB")
    tw, th = 1280, 720
    sc = max(tw / im.width, th / im.height)
    im = im.resize((int(im.width * sc), int(im.height * sc)))
    x0 = (im.width - tw) // 2
    y0 = (im.height - th) // 2
    out = PROD / "video_thumb.png"
    im.crop((x0, y0, x0 + tw, y0 + th)).save(out)
    (PROD / "video_title.txt").write_text(cb["title"], encoding="utf-8")
    print(f"[done] {out} (Flow, text baked)")


if __name__ == "__main__":
    main()
