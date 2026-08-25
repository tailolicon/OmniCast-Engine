"""Judge a premise for one planner call instead of a whole run.

Nine live runs produced no releasable compilation, and the last four died on
the QUALITY of the premise rather than on plumbing. Each cost roughly
twenty-five minutes and a large share of a quota window, which is why only
nine premises have been looked at.

Planning is one planner call plus one audit. This runs exactly that, prints
the premise in the form a person can judge, and stops. Thirty premises now fit
where three did.

Nothing here writes prose or scores it — a plan that passes still has to
survive the writer, the critic and the release challenger.

Usage:
  python scripts/plan_only.py --topic "True Encounters From ..."
  python scripts/plan_only.py --topic "..." --repeat 3
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("OMNICAST_SCRIPT_FLOW", "unit_first")
os.environ.setdefault("OMNICAST_CLAUDE_BACKEND", "cli")
os.environ["OMNICAST_NARRATIVE_PLAN_ONLY"] = "1"


def _show(plan) -> None:
    print(f"\nCOLD OPEN: {plan.cold_open}")
    print(f"TOTAL: {plan.target_word_count} words across {len(plan.stories)} "
          f"stories")
    for item in plan.stories:
        budget = getattr(item, "target_words", 0) or 0
        print(f"\n─── {item.story_id}: {item.title}"
              f"{f'  [{budget}w]' if budget else ''}")
        print(f"  narrator : {item.narrator_profile}")
        print(f"  setting  : {item.setting}")
        print(f"  setup    : {item.setup_requirement}")
        print(f"  threat   : {item.threat}  ({item.threat_type})")
        print(f"  escape   : {item.escape_action}")
        print(f"  ending   : {item.ending_shape}")
        print(f"  fresh    : {getattr(item, 'distinguishing_turn', '')}")
        for k in ("no_way_out", "threat_mind", "already_line", "remainder"):
            v = getattr(item, k, "")
            if v:
                print(f"  {k:<9}: {v}")
        print(f"  voice    : {item.voice_rules}")
        seed = (item.voice_seed or "").strip()
        if seed:
            print(f"  seed     : {seed[:200]}")


async def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--stories", type=int, default=0,
                    help="force N stories (0 = title/duration decides)")
    ap.add_argument("--channel", default="true_dread_files_us")
    ap.add_argument("--topic", required=True)
    ap.add_argument("--repeat", type=int, default=1,
                    help="judge N independent premises for the same topic")
    ap.add_argument("--save", default="",
                    help="write accepted plans as JSON here")
    args = ap.parse_args()
    if len(args.topic.split()) < 3:
        print(f"REJECTED: topic too short: {args.topic!r}")
        return 1

    from omnicast.agents.narrative_pipeline import PlanOnlyComplete
    from omnicast.config.narrative_roles import apply_standard_roles
    from omnicast.pipeline.steps import StepContext, _step_script
    apply_standard_roles(os.environ)
    if getattr(args, "stories", 0):
        os.environ["OMNICAST_NARRATIVE_STORY_COUNT"] = str(args.stories)

    accepted = []
    for run in range(1, args.repeat + 1):
        started = time.perf_counter()
        ctx = StepContext("plan_only", "manual_cli", {}, {})
        print(f"\n{'=' * 72}\nPREMISE {run}/{args.repeat}: {args.topic}\n{'=' * 72}")
        try:
            await _step_script({"channel_id": args.channel,
                                "topic": args.topic}, ctx)
            print("unexpected: the pipeline ran past the plan stage")
        except PlanOnlyComplete as ok:
            print(f"ACCEPTED in {time.perf_counter() - started:.0f}s "
                  f"(audit: {ok.audit.status})")
            _show(ok.plan)
            accepted.append({"plan": ok.plan.model_dump(mode="json"),
                             "audit": ok.audit.model_dump(mode="json")})
        except Exception as exc:
            # A rejected premise is the useful case, not an error: it is the
            # whole reason to run this. Print why and keep going.
            print(f"REJECTED in {time.perf_counter() - started:.0f}s")
            print(f"  {str(exc)[:600]}")

    if args.save and accepted:
        Path(args.save).write_text(
            json.dumps(accepted, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\n[written] {len(accepted)} accepted plan(s) -> {args.save}")
    print(f"\n{len(accepted)}/{args.repeat} premises accepted")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
