# -*- coding: utf-8 -*-
"""Persistent Chatterbox TTS worker — runs inside .venv_chatterbox.

Why a persistent worker: Chatterbox's model load costs ~10-30s on CPU. The
renderer synthesizes one scene at a time (~40 calls/video), so spawning a fresh
process per scene would reload the model 40x. Instead this loads ONCE, prints a
READY marker, then serves requests over a line protocol until stdin closes.

Protocol (one JSON object per line):
  stdin  request : {"text": str, "out": str, "exaggeration": f, "cfg_weight": f,
                    "temperature": f, "ref": str|null}
  stdout response: <MARKER>{"ok": true, "dur": f}   or  <MARKER>{"error": str}

All library/model noise goes to STDERR so stdout carries only marker lines.
"""
import json
import sys
import time
from pathlib import Path

MARKER = "\x01OMNI\x01"  # unambiguous response prefix; provider scans for this


def _log(msg: str) -> None:
    print(f"[cbx-worker] {msg}", file=sys.stderr, flush=True)


def _respond(obj: dict) -> None:
    sys.stdout.write(MARKER + json.dumps(obj) + "\n")
    sys.stdout.flush()


def main() -> int:
    # GPU when present (RTX 3050 4GB holds the ~1.5GB model comfortably and
    # synthesizes ~10x faster than CPU); CBX_DEVICE=cpu forces the fallback.
    import os as _os
    device = _os.environ.get("CBX_DEVICE", "").strip().lower()
    if not device:
        try:
            import torch as _t
            device = "cuda" if _t.cuda.is_available() else "cpu"
        except Exception:
            device = "cpu"
    _log(f"loading model on {device.upper()} (first run downloads ~1-2GB)…")
    t0 = time.time()
    # Redirect any load-time stdout prints to stderr so the protocol stays clean.
    real_stdout = sys.stdout
    sys.stdout = sys.stderr
    try:
        import torch
        torch.set_num_threads(max(1, (torch.get_num_threads() or 4)))
        from chatterbox.tts import ChatterboxTTS
        model = ChatterboxTTS.from_pretrained(device=device)
        import torchaudio
    finally:
        sys.stdout = real_stdout
    _log(f"model ready in {time.time()-t0:.1f}s sr={model.sr}")
    _respond({"ready": True, "sr": int(model.sr)})

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except Exception as exc:
            _respond({"error": f"bad request json: {exc}"})
            continue
        text = (req.get("text") or "").strip()
        out = req.get("out")
        if not text or not out:
            _respond({"error": "missing text/out"})
            continue
        exg = float(req.get("exaggeration", 0.4))
        cfg = float(req.get("cfg_weight", 0.3))
        temp = float(req.get("temperature", 0.7))
        ref = req.get("ref") or None
        try:
            t = time.time()
            # Route synth-time noise to stderr too.
            sys.stdout = sys.stderr
            try:
                wav = model.generate(text, audio_prompt_path=ref, exaggeration=exg,
                                     cfg_weight=cfg, temperature=temp)
            finally:
                sys.stdout = real_stdout
            Path(out).parent.mkdir(parents=True, exist_ok=True)
            torchaudio.save(out, wav, model.sr)
            dur = wav.shape[-1] / model.sr
            _log(f"synth {dur:.1f}s audio in {time.time()-t:.1f}s -> {Path(out).name}")
            _respond({"ok": True, "dur": float(dur)})
        except Exception as exc:
            import traceback
            _log("synth failed:\n" + traceback.format_exc())
            _respond({"error": str(exc)})
    _log("stdin closed — exiting")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
