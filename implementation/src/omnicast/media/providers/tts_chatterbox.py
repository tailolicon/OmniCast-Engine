"""Chatterbox TTS provider (Resemble AI) — expressive local neural TTS.

Chatterbox is MIT-licensed (commercial-safe, unlike F5-TTS's CC-BY-NC) and the
first open model with an ``exaggeration`` emotion dial — ideal for the measured
dread the horror channel needs, which Kokoro's flat delivery cannot produce.

Isolation: Chatterbox pins its own torch/transformers stack that would clash
with the main env, and the project forbids ad-hoc dependency bumps. So it lives
in a dedicated venv (``.venv_chatterbox``) and is driven as a PERSISTENT
subprocess worker (``scripts/chatterbox_worker.py``): the model loads once and
serves per-scene requests over a stdin/stdout line protocol. The provider is a
registry singleton, so every scene in a render reuses the one warm worker.

Params (dread-tuned defaults, overridable via env):
  exaggeration 0.40  — controlled, not theatrical
  cfg_weight   0.30  — slower, deliberate pacing (lower = slower)
  temperature  0.70  — steady delivery
Voice cloning: pass a reference wav as the voice spec (``chatterbox:/path/ref.wav``)
or via ``voice_clone_path`` — else the built-in voice is used.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import threading
from pathlib import Path

from omnicast.media.providers.interfaces import ModelOption

_IMPL_ROOT = Path(__file__).resolve().parents[4]
_VENV_PY = (_IMPL_ROOT / ".venv_chatterbox" / "bin" / "python") if os.name != "nt" else (_IMPL_ROOT / ".venv_chatterbox" / "Scripts" / "python.exe")
_WORKER = _IMPL_ROOT / "scripts" / "chatterbox_worker.py"
_MARKER = "\x01OMNI\x01"

# Dread-tuned defaults (env-overridable so the operator can retune without code).
_DEF_EXG = float(os.getenv("OMNICAST_CBX_EXAGGERATION", "0.40"))
_DEF_CFG = float(os.getenv("OMNICAST_CBX_CFG_WEIGHT", "0.30"))
_DEF_TEMP = float(os.getenv("OMNICAST_CBX_TEMPERATURE", "0.70"))
_READY_TIMEOUT = float(os.getenv("OMNICAST_CBX_READY_TIMEOUT", "180"))
_SYNTH_TIMEOUT = float(os.getenv("OMNICAST_CBX_SYNTH_TIMEOUT", "300"))


class ChatterboxTTSProvider:
    """Expressive local TTS via a persistent isolated-venv worker."""

    id = "chatterbox"
    name = "Chatterbox (Resemble AI, Local)"
    models = [
        ModelOption(id="default", name="Chatterbox default voice",
                    description="Built-in expressive voice (exaggeration dial)"),
    ]

    def __init__(self) -> None:
        self._proc: subprocess.Popen | None = None
        self._lock = threading.Lock()  # one worker, serialize scene requests
        self._sr = 24000

    # ── worker lifecycle ────────────────────────────────────────────────────
    def _ensure_worker(self) -> subprocess.Popen:
        if self._proc is not None and self._proc.poll() is None:
            return self._proc
        if not _VENV_PY.exists():
            raise RuntimeError(
                f"Chatterbox venv missing at {_VENV_PY}. Create it: "
                f"python -m venv .venv_chatterbox && "
                f".venv_chatterbox/Scripts/python -m pip install chatterbox-tts soundfile")
        creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        env = dict(os.environ)
        env["PYTHONIOENCODING"] = "utf-8"
        proc = subprocess.Popen(
            [str(_VENV_PY), "-X", "utf8", str(_WORKER)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=None,
            text=True, encoding="utf-8", bufsize=1, env=env,
            creationflags=creationflags)
        # Wait for the READY marker (covers first-run model download).
        import time as _t
        t0 = _t.time()
        while _t.time() - t0 < _READY_TIMEOUT:
            if proc.poll() is not None:
                raise RuntimeError("Chatterbox worker died during startup (see stderr)")
            resp = self._read_marker(proc)
            if resp is not None:
                if resp.get("ready"):
                    self._sr = int(resp.get("sr", self._sr))
                    self._proc = proc
                    return proc
                raise RuntimeError(f"Chatterbox worker startup error: {resp}")
        proc.kill()
        raise RuntimeError(f"Chatterbox worker not ready within {_READY_TIMEOUT}s")

    def _read_marker(self, proc: subprocess.Popen) -> dict | None:
        """Read stdout lines until one carries the response marker. Non-marker
        lines (stray prints) are ignored. Returns None on EOF."""
        assert proc.stdout is not None
        while True:
            line = proc.stdout.readline()
            if line == "":
                return None
            idx = line.find(_MARKER)
            if idx >= 0:
                try:
                    return json.loads(line[idx + len(_MARKER):].strip())
                except Exception:
                    continue

    # ── synthesis ───────────────────────────────────────────────────────────
    async def generate(
        self,
        text: str,
        *,
        model: str | None = None,
        voice_clone_path: str | None = None,
        output_path: str,
        speed: float = 1.0,  # honored by the caller's atempo post-pass, not here
    ) -> str:
        # A model spec that points at an audio file = a clone reference.
        ref = voice_clone_path
        if not ref and model and model not in ("default", "chatterbox"):
            cand = Path(model)
            if cand.suffix.lower() in (".wav", ".mp3", ".flac") and cand.exists():
                ref = str(cand)
        req = {
            "text": text, "out": str(output_path),
            "exaggeration": _DEF_EXG, "cfg_weight": _DEF_CFG,
            "temperature": _DEF_TEMP, "ref": ref,
        }
        return await asyncio.to_thread(self._synth_blocking, req, output_path)

    def _synth_blocking(self, req: dict, output_path: str) -> str:
        with self._lock:
            proc = self._ensure_worker()
            assert proc.stdin is not None
            try:
                proc.stdin.write(json.dumps(req) + "\n")
                proc.stdin.flush()
            except (BrokenPipeError, OSError) as exc:
                self._proc = None
                raise RuntimeError(f"Chatterbox worker pipe broke: {exc}") from exc
            resp = self._read_marker(proc)
            if resp is None:
                self._proc = None
                raise RuntimeError("Chatterbox worker closed mid-request")
            if resp.get("error"):
                raise RuntimeError(f"Chatterbox synth failed: {resp['error']}")
        if not Path(output_path).exists() or Path(output_path).stat().st_size == 0:
            raise RuntimeError("Chatterbox produced no audio")
        return output_path

    def close(self) -> None:
        proc, self._proc = self._proc, None
        if proc and proc.poll() is None:
            try:
                if proc.stdin:
                    proc.stdin.close()
                proc.wait(timeout=5)
            except Exception:
                proc.kill()
