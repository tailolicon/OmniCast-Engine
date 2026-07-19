"""One bounded phase-2 (script) end-to-end attempt for task 2.1 validation.

Scratch driver — invokes the omnicast.script pipeline step directly with a manual
topic, exactly like a pipeline run would. Delete after validation.
"""

from __future__ import annotations

import asyncio
import os
import sys
import time

os.environ["OMNICAST_SCRIPT_FLOW"] = "unit_first"
os.environ["OMNICAST_CLAUDE_BACKEND"] = "cli"

TOPIC = "3 True Encounters During Apartment Maintenance Calls After Dark"
CHANNEL = "true_dread_files_us"


async def main() -> int:
    from omnicast.pipeline.steps import StepContext, _step_script

    ctx = StepContext(
        execution_id=f"manual-e2e-{int(time.time())}",
        pipeline_id="manual-cli-phase2",
        inputs={},
        step_outputs={},
    )
    t0 = time.perf_counter()
    try:
        out = await _step_script({"channel_id": CHANNEL, "topic": TOPIC}, ctx)
    except Exception as exc:
        print(f"\nE2E_RESULT: REJECTED after {time.perf_counter() - t0:.1f}s")
        print(f"E2E_ERROR: {exc}")
        return 1
    print(f"\nE2E_RESULT: ACCEPTED after {time.perf_counter() - t0:.1f}s")
    print(f"E2E_OUTPUT: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
