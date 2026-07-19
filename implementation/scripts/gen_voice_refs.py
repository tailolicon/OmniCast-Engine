# -*- coding: utf-8 -*-
"""Generate deep-male horror-narrator reference clips via Edge-TTS (main env).

These serve two purposes:
  1. A standalone FAST narrator option (Edge is ~realtime, no RTF penalty).
  2. Seed references to CLONE into Chatterbox (Edge timbre + Chatterbox emotion).

Same dread test line as the Chatterbox spike, for apples-to-apples comparison.
"""
import asyncio
from pathlib import Path

import edge_tts

OUT = Path(__file__).resolve().parent.parent / "output" / "_tts_spike"
OUT.mkdir(parents=True, exist_ok=True)

TEXT = ("I worked home health, third shift, driving the county roads nobody else "
        "wanted. That night, the thing at mile marker twelve was standing exactly "
        "where it had been the week before. It had not moved. It was still facing "
        "the road. It was still waiting for me.")

# (label, voice, rate, pitch) — deep/slow/ominous variants
VARIANTS = [
    ("edge_christopher_deep", "en-US-ChristopherNeural", "-8%", "-6Hz"),
    ("edge_eric_calm",        "en-US-EricNeural",        "-6%", "-3Hz"),
    ("edge_guy_flat",         "en-US-GuyNeural",         "-10%", "-4Hz"),
]


async def one(label, voice, rate, pitch):
    mp3 = OUT / f"{label}.mp3"
    c = edge_tts.Communicate(TEXT, voice, rate=rate, pitch=pitch)
    await c.save(str(mp3))
    return label, mp3


async def main():
    for v in VARIANTS:
        label, mp3 = await one(*v)
        print(f"[ref] {label:24s} -> {mp3.name}")


if __name__ == "__main__":
    asyncio.run(main())
