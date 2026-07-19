# -*- coding: utf-8 -*-
"""Feasibility spike for Chatterbox TTS on CPU — horror-narration params.

Runs in the isolated .venv_chatterbox. Synthesizes the same dread line at a few
param settings, saves wavs, and prints the CPU real-time factor (audio_sec /
wall_sec) so we know if it's viable for batch overnight renders.
"""
import time
from pathlib import Path

import torchaudio
from chatterbox.tts import ChatterboxTTS

OUT = Path(__file__).resolve().parent.parent / "output" / "_tts_spike"
OUT.mkdir(parents=True, exist_ok=True)

# A measured, first-person dread line (the channel's actual register).
TEXT = ("I worked home health, third shift, driving the county roads nobody else "
        "wanted. That night, the thing at mile marker twelve was standing exactly "
        "where it had been the week before. It had not moved. It was still facing "
        "the road. It was still waiting for me.")

print("[spike] loading model on CPU (first run downloads ~1-2GB)…", flush=True)
t0 = time.time()
model = ChatterboxTTS.from_pretrained(device="cpu")
print(f"[spike] model loaded in {time.time()-t0:.1f}s  sr={model.sr}", flush=True)

# (label, exaggeration, cfg_weight, temperature)
TRIALS = [
    ("A_measured", 0.40, 0.30, 0.70),   # controlled dread, slow pacing
    ("B_dramatic", 0.60, 0.45, 0.80),   # more theatrical
    ("C_flat_slow", 0.30, 0.25, 0.60),  # very deliberate, near-monotone menace
]

for label, exg, cfg, temp in TRIALS:
    t = time.time()
    wav = model.generate(TEXT, exaggeration=exg, cfg_weight=cfg, temperature=temp)
    wall = time.time() - t
    dur = wav.shape[-1] / model.sr
    out = OUT / f"spike_{label}.wav"
    torchaudio.save(str(out), wav, model.sr)
    print(f"[spike] {label:12s} exg={exg} cfg={cfg} temp={temp} | "
          f"audio={dur:.1f}s wall={wall:.1f}s  RTF={dur/wall:.2f}x  -> {out.name}",
          flush=True)

print("[spike] done. Listen to output/_tts_spike/*.wav", flush=True)
