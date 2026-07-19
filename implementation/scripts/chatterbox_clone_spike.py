# -*- coding: utf-8 -*-
"""Clone Edge deep-male refs into Chatterbox — timbre from Edge, emotion from
Chatterbox's exaggeration dial. Runs in .venv_chatterbox."""
import time
from pathlib import Path

import torchaudio
from chatterbox.tts import ChatterboxTTS

OUT = Path(__file__).resolve().parent.parent / "output" / "_tts_spike"
TEXT = ("I worked home health, third shift, driving the county roads nobody else "
        "wanted. That night, the thing at mile marker twelve was standing exactly "
        "where it had been the week before. It had not moved. It was still facing "
        "the road. It was still waiting for me.")

REFS = [
    ("cbx_clone_christopher", OUT / "edge_christopher_deep.wav", 0.45, 0.30, 0.70),
    ("cbx_clone_eric",        OUT / "edge_eric_calm.wav",        0.45, 0.30, 0.70),
]

print("[clone] loading model…", flush=True)
model = ChatterboxTTS.from_pretrained(device="cpu")
print(f"[clone] ready sr={model.sr}", flush=True)

for label, ref, exg, cfg, temp in REFS:
    if not ref.exists():
        print(f"[clone] SKIP {label}: ref missing {ref}", flush=True)
        continue
    t = time.time()
    wav = model.generate(TEXT, audio_prompt_path=str(ref), exaggeration=exg,
                         cfg_weight=cfg, temperature=temp)
    dur = wav.shape[-1] / model.sr
    out = OUT / f"{label}.wav"
    torchaudio.save(str(out), wav, model.sr)
    print(f"[clone] {label:22s} audio={dur:.1f}s wall={time.time()-t:.1f}s "
          f"RTF={dur/(time.time()-t):.2f}x -> {out.name}", flush=True)

print("[clone] done", flush=True)
