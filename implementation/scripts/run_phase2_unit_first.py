"""Phase-2-only driver: unit-first creepy script generation for one manual topic.

Runs the omnicast.script pipeline step exactly as the runner would, with the
narrative unit-first flow and the subscription Claude CLI writer backend.

Usage:
    .venv/Scripts/python.exe scripts/run_phase2_unit_first.py \
        [--channel true_dread_files_us] [--topic "..."]
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
os.environ.setdefault("OMNICAST_SCRIPT_FLOW", "unit_first")
# Script generation bills the operator subscription, never API credits.
os.environ.setdefault("OMNICAST_CLAUDE_BACKEND", "cli")


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stories", type=int, default=0,
                        help="force N stories (0 = title/duration decides)")
    parser.add_argument("--channel", default="true_dread_files_us")
    parser.add_argument(
        "--topic",
        default="3 True Encounters During Apartment Maintenance Calls After Dark",
    )
    args = parser.parse_args()
    # A mangled launcher once split a quoted topic into single words and the
    # pipeline burned 50 minutes generating for the topic "3". Fail fast on
    # anything that cannot be a real compilation topic.
    if len(args.topic.split()) < 3:
        print(f"REJECTED/FAILED after 0.0s: topic too short to be real: {args.topic!r} "
              "(check launcher quoting)")
        return 1

    # The model tier is operational policy, not a per-launch choice. Running
    # this script without it put planner and writer on Opus at max effort and
    # burned a whole quota window on one unfinished compilation.
    from omnicast.config.narrative_roles import apply_standard_roles
    apply_standard_roles(os.environ)
    if getattr(args, "stories", 0):
        os.environ["OMNICAST_NARRATIVE_STORY_COUNT"] = str(args.stories)

    from omnicast.pipeline.steps import StepContext, _step_script

    ctx = StepContext("manual_phase2", "manual_cli", {}, {})
    start = time.perf_counter()
    try:
        out = await _step_script({"channel_id": args.channel, "topic": args.topic}, ctx)
    except Exception as exc:
        print(f"REJECTED/FAILED after {time.perf_counter() - start:.1f}s: {exc}")
        return 1
    print(f"ACCEPTED after {time.perf_counter() - start:.1f}s")
    for key, value in out.items():
        print(f"  {key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
