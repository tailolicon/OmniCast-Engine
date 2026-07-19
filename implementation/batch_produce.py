# -*- coding: utf-8 -*-
"""Pipelined multi-video producer — fastest + most resource-efficient path.

The naive way (fully sequential per video) wastes the machine: while one video
renders on CPU, nothing else happens. This orchestrates by RESOURCE CLASS so
independent work overlaps:

  1. SCRIPTS (LLM/subprocess-bound, tiny local footprint) — generate ALL of them
     concurrently up front.
  2. RENDERS (mixed) — launch several at once, capped by RAM. They self-pipeline:
     the Flow image phase is a single shared browser, guarded by a cross-process
     lock (flow_browser._acquire_flow_xlock), so only ONE render drives Flow at a
     time; every other stage (TTS, ffmpeg compose, encode) runs in parallel. Net
     effect: while render A does CPU compose, render B does network image gen.

Usage:
  python batch_produce.py --channel true_dread_files_us \
      --topics "3 True Night Shift Stories" "3 True Rural Road Encounters" ...
  # optional: --max-renders 2  (concurrent renders; default = RAM/6GB, min 1)

Each topic → one product (script.txt + video.mp4). Scripts that fail QA are
still rendered (the pipeline reports scores); use --min-score to skip low ones.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


def _ram_gb() -> float:
    try:
        if sys.platform == "win32":
            import ctypes

            class _MS(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong),
                            ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong),
                            ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong),
                            ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong),
                            ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
            ms = _MS(); ms.dwLength = ctypes.sizeof(_MS)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(ms))
            return ms.ullAvailPhys / 1e9
    except Exception:
        pass
    return 8.0


def _product_dir(channel: str, topic: str) -> Path | None:
    """Newest product dir for a channel whose slug matches the topic words."""
    base = ROOT / "output" / "products" / channel
    if not base.exists():
        return None
    key = "".join(c for c in topic.lower() if c.isalnum() or c == " ").split()[:4]
    best = None
    for d in base.iterdir():
        s = d.name.lower()
        if all(k in s for k in key):
            if best is None or d.stat().st_mtime > best.stat().st_mtime:
                best = d
    return best


async def _gen_script(channel: str, topic: str, sem: asyncio.Semaphore) -> tuple[str, bool, str]:
    """Run content_flow phase-2 for one topic. Concurrency-limited (LLM-bound)."""
    async with sem:
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-X", "utf8", "content_flow.py",
            "--channel", channel, "--topic", topic, "--phase", "2",
            cwd=str(ROOT), stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT, creationflags=_NO_WINDOW)
        out, _ = await proc.communicate()
        ok = proc.returncode == 0 and _product_dir(channel, topic) is not None
        tail = (out or b"").decode("utf-8", "ignore")
        score = ""
        for line in tail.splitlines():
            if "pipeline.script: done" in line and "score=" in line:
                score = "score " + line.split("score=")[1].split()[0]
        return topic, ok, score or "(no score)"


async def _render(channel: str, product: Path, sem: asyncio.Semaphore,
                  image_model: str) -> tuple[str, bool]:
    """Render one product. RAM-capped concurrency; Flow phase self-serializes via
    the cross-process xlock inside flow_browser."""
    async with sem:
        env = dict(os.environ)
        if image_model:
            env["FLOW_IMAGE_MODEL"] = image_model
        # stale Singleton lock is auto-cleaned inside the provider now
        log = ROOT / "output" / f"_batch_{product.name[:20]}.log"
        with open(log, "w", encoding="utf-8") as lf:
            proc = await asyncio.create_subprocess_exec(
                sys.executable, "-X", "utf8", "render_real_video.py",
                "--script", str(product / "script.txt"),
                "--channel", channel, "--subtitles",
                "--out", str(product / "video.mp4"),
                cwd=str(ROOT), stdout=lf, stderr=asyncio.subprocess.STDOUT,
                env=env, creationflags=_NO_WINDOW)
            await proc.communicate()
        ok = proc.returncode == 0 and (product / "video.mp4").exists()
        return product.name, ok


async def main_async(a) -> int:
    t0 = time.time()
    max_scripts = a.max_scripts or min(len(a.topics), 4)
    avail = _ram_gb()
    max_renders = a.max_renders or max(1, min(len(a.topics), int(avail // 6)))
    print(f"[batch] {len(a.topics)} videos | RAM avail {avail:.1f}GB | "
          f"scripts x{max_scripts} concurrent, renders x{max_renders} concurrent")

    # ── PHASE 1: all scripts concurrently ────────────────────────────────────
    print("[batch] phase 1 — generating scripts (parallel)…")
    ssem = asyncio.Semaphore(max_scripts)
    results = await asyncio.gather(*[_gen_script(a.channel, t, ssem) for t in a.topics])
    ready: list[Path] = []
    for topic, ok, score in results:
        pd = _product_dir(a.channel, topic) if ok else None
        print(f"  {'✓' if ok else '✗'} {score:14s} {topic[:50]}")
        if pd:
            ready.append(pd)
    if not ready:
        print("[batch] no scripts produced — abort")
        return 1

    # ── PHASE 2: pipelined renders (Flow serialized, CPU overlapped) ─────────
    print(f"[batch] phase 2 — rendering {len(ready)} videos (pipelined)…")
    rsem = asyncio.Semaphore(max_renders)
    rr = await asyncio.gather(*[
        _render(a.channel, pd, rsem, a.image_model) for pd in ready])
    done = sum(1 for _, ok in rr if ok)
    for name, ok in rr:
        print(f"  {'✓' if ok else '✗'} {name}")
    print(f"[batch] {done}/{len(ready)} videos rendered in {(time.time()-t0)/60:.1f} min")
    return 0 if done == len(ready) else 2


def main() -> int:
    ap = argparse.ArgumentParser(description="Pipelined multi-video producer")
    ap.add_argument("--channel", required=True)
    ap.add_argument("--topics", nargs="+", required=True, help="one per video")
    ap.add_argument("--max-scripts", type=int, default=0, help="concurrent script gens (default: min(N,4))")
    ap.add_argument("--max-renders", type=int, default=0, help="concurrent renders (default: RAM//6GB)")
    ap.add_argument("--image-model", default="nano-banana-pro")
    return asyncio.run(main_async(ap.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
