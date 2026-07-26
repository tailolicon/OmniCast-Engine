"""Phase-2 driver: claude_first finance-explainer script for one manual topic.

Runs the omnicast.script pipeline step for the flagship senior-finance channel:
Writer (Claude, subscription CLI backend) → Critic (finance_explainer_v1 rubric
+ deterministic YMYL caps) → revise → fact-citation ledger (fail-closed).

Usage:
    .venv/Scripts/python.exe scripts/run_phase2_finance.py \
        [--channel senior_wealth_us] [--topic "..."] \
        [--angle "..."] [--pain "..."] [--audience "..."] [--brief "..."]
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
# claude_first is the default flow for an explainer channel — set explicitly so
# an inherited OMNICAST_SCRIPT_FLOW from a horror shell can't reroute us.
os.environ["OMNICAST_SCRIPT_FLOW"] = "claude_first"
# Script generation bills the operator subscription, never API credits.
os.environ.setdefault("OMNICAST_CLAUDE_BACKEND", "cli")


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--channel", default="senior_wealth_us")
    parser.add_argument("--topic", required=True)
    parser.add_argument("--angle", default="")
    parser.add_argument("--pain", default="")
    parser.add_argument("--audience", default="")
    parser.add_argument("--brief", default="", help="operator_desc steering text")
    args = parser.parse_args()
    if len(args.topic.split()) < 3:
        print(f"REJECTED/FAILED after 0.0s: topic too short: {args.topic!r}")
        return 1

    from omnicast.pipeline.steps import StepContext, _step_script

    inputs = {"channel_id": args.channel, "topic": args.topic}
    for key, val in (("content_angle", args.angle), ("pain_point", args.pain),
                     ("audience", args.audience), ("operator_desc", args.brief)):
        if val:
            inputs[key] = val

    ctx = StepContext("manual_phase2", "manual_cli", {}, {})
    start = time.perf_counter()
    try:
        out = await _step_script(inputs, ctx)
    except Exception as exc:
        print(f"REJECTED/FAILED after {time.perf_counter() - start:.1f}s: {exc}")
        return 1
    print(f"ACCEPTED after {time.perf_counter() - start:.1f}s")
    for key, value in out.items():
        print(f"  {key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
