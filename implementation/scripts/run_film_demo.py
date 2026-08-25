"""Run a film spec end-to-end through the pipeline (no manual UI steps).

    python scripts/run_film_demo.py <film.yaml> [--fresh-clips] [--project URL]

Gates (film_runner): still style gate → FLF clips → boundary gate → assembly
with loudness verification. Fails closed at the first unpassable gate.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from omnicast.media.providers.flow_browser import FlowProvider  # noqa: E402
from omnicast.storyboard.film_runner import load_film_spec, run_film  # noqa: E402


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("spec", help="film.yaml path")
    ap.add_argument("--fresh-clips", action="store_true",
                    help="ignore clips already on disk (full regen)")
    ap.add_argument("--project", default="",
                    help="Flow project URL (default: settings/env)")
    args = ap.parse_args()

    spec = load_film_spec(args.spec)
    provider = FlowProvider(project_url=args.project or None)
    credits = await provider.credits()
    print(f"[film] flow credits: {credits}", flush=True)
    try:
        final = await run_film(spec, provider,
                               reuse_clips=not args.fresh_clips)
    finally:
        provider.close()
    print(f"[film] FINAL: {final}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
