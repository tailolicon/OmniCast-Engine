"""Render a single Remotion composition to an mp4 — the bridge that lets
render_real_video drop animated React scenes (intro / count-up stat / outro)
into the existing ffmpeg concat pipeline. Additive: if Remotion isn't installed
the caller just falls back to the normal ffmpeg scene.

Compositions live in remotion_studio/src/ (IntroCard, StatPop, OutroCTA).
Each takes JSON props incl. durationInFrames so the clip matches narration length.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).parent
STUDIO = ROOT / "remotion_studio"
FPS = 30

# Compositions registered in remotion_studio/src/Root.tsx
KNOWN_COMPS = {"IntroCard", "StatPop", "OutroCTA"}


def available() -> bool:
    """True only when the studio deps are installed (npm install ran)."""
    return (STUDIO / "node_modules" / "remotion").exists() and _npx() is not None


def _npx() -> str | None:
    return shutil.which("npx") or shutil.which("npx.cmd")


def render_scene(comp_id: str, props: dict, out_mp4: Path, dur_s: float = 4.0,
                 w: int = 1920, h: int = 1080, fps: int = FPS,
                 timeout: int = 600) -> bool:
    """Render `comp_id` with `props` to `out_mp4` (silent video, h264).

    durationInFrames is derived from dur_s so the scene matches its narration.
    Returns True on success. Never raises — logs + returns False so the caller
    falls back to the normal ffmpeg scene.
    """
    if not available():
        return False
    if comp_id not in KNOWN_COMPS:
        print(f"[remotion] [warn] unknown composition {comp_id!r}")
        return False

    out_mp4 = Path(out_mp4)
    out_mp4.parent.mkdir(parents=True, exist_ok=True)
    props = dict(props or {})
    props["durationInFrames"] = max(fps, round(float(dur_s) * fps))

    props_file = STUDIO / f"_props_{uuid.uuid4().hex[:10]}.json"
    try:
        props_file.write_text(json.dumps(props), encoding="utf-8")
        cmd = [
            _npx(), "remotion", "render", "src/index.ts", comp_id,
            str(out_mp4.resolve()),
            f"--props={props_file.resolve()}",
            "--codec=h264",
            "--log=error",
            f"--concurrency={max(1, (os.cpu_count() or 4) // 2)}",
        ]
        print(f"[remotion] render {comp_id} -> {out_mp4.name} ({props['durationInFrames']}f)")
        proc = subprocess.run(cmd, cwd=str(STUDIO), capture_output=True, text=True,
                              timeout=timeout)
        if proc.returncode != 0:
            sys.stderr.write((proc.stderr or "")[-1500:])
            print(f"[remotion] [warn] render failed rc={proc.returncode}")
            return False
        return out_mp4.exists() and out_mp4.stat().st_size > 0
    except Exception as exc:
        print(f"[remotion] [warn] {exc}")
        return False
    finally:
        try:
            props_file.unlink()
        except Exception:
            pass


if __name__ == "__main__":
    # Smoke test: render the three templates to output/_remotion_test/.
    out = ROOT / "output" / "_remotion_test"
    print("available:", available())
    if available():
        for comp, props in [
            ("IntroCard", {"title": "THE GLP-1 TRAP", "subtitle": "Why healthy food backfires", "accent": "#38bdf8", "bg": "#0a0f1a"}),
            ("StatPop", {"value": 50, "suffix": "%", "label": "SLOWER GASTRIC EMPTYING", "accent": "#38bdf8"}),
            ("OutroCTA", {"headline": "SUBSCRIBE", "sub": "Weekly health breakdowns", "accent": "#ef4444", "bg": "#0a0f1a"}),
        ]:
            ok = render_scene(comp, props, out / f"{comp}.mp4", dur_s=3.0)
            print(comp, "->", ok)
