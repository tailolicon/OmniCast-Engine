"""Would the trope auditor reject the videos this channel is competing with?

`plan_audit/trope` accounts for 53% of every plan rejection this channel has
ever had — 108 of 203 — and fourteen runs have produced no releasable script.
Reading the objections, some look fair and some look like the auditor mapping
a specific premise onto a generic label ("standard wrong-address stalker") and
rejecting it because the label exists. Almost any premise maps onto some label.

But the person running this wants a script to pass, which is a bad position
from which to judge whether a gate is too strict. So the gate gets judged
against something it cannot be argued with: the real premises of the
competitor videos, several with over a million views, taken from their own
transcripts.

If the auditor rejects those as tropes, it is miscalibrated by an objective
standard rather than by anyone's preference. If it passes them, the gate is
right and our premises really are stock.

Costs plan_audit calls only (DeepSeek in the standard role config), no writer
and no critic.

Usage:
  python scripts/audit_calibration.py --n 6
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("OMNICAST_CLAUDE_BACKEND", "cli")


async def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--channel", default="true_dread_files_us")
    ap.add_argument("--n", type=int, default=6)
    args = ap.parse_args()

    from omnicast.config.narrative_roles import apply_standard_roles
    apply_standard_roles(os.environ)

    from omnicast.agents.narrative_pipeline import (
        CompilationPlan,
        NarrativeStoryPlan,
    )
    from omnicast.config.narrative_quality import SCRIPT_PROFILE_REGISTRY
    from omnicast.pipeline.steps import _build_unit_pipeline_for_audit

    bank = json.loads(
        (ROOT / "output" / "research" / args.channel / "premise_bank.json")
        .read_text(encoding="utf-8"))[: args.n]

    profile = SCRIPT_PROFILE_REGISTRY["true_horror_strict_v1"]
    unit = _build_unit_pipeline_for_audit(args.channel)

    passed = blocked = 0
    for row in bank:
        # The competitor's own opening, cast into the fields the auditor reads.
        # Deliberately thin: the point is whether the PREMISE reads as stock,
        # and a thin plan gives the auditor less to like, not more.
        story = NarrativeStoryPlan(
            story_id="story_1", title=row["title"][:60],
            narrator_profile=row["opening"][:200],
            setting="as described in the account",
            setup_requirement=row["opening"][:200],
            threat=(row["first_turns"] or ["something the narrator noticed"])[0][:200],
            threat_type="human",
            escape_action="leaves for a lit, occupied place",
            ending_shape="nothing is explained afterwards",
            voice_rules="plain spoken account",
            continuity_ledger=[
                "hook_timeline: the night described in the account",
                "people_objects: narrator and one stranger",
                "locations_exits: the place described and the road out",
                "props_threat_position: stranger at the edge of the scene",
                "response_escape: leaves for somewhere occupied",
            ],
            threat_mechanism="blocks_path",
            progression_mechanism="silent_stillness",
            escape_mechanism="flee_to_occupied_place",
            aftermath_mechanism="no_explanation_offered",
            threat_identity="lone_stranger",
            distinguishing_turn=(row["first_turns"] or ["it happened"])[0][:120],
        )
        plan = CompilationPlan(topic=row["title"][:80],
                               cold_open=row["opening"][:120],
                               target_word_count=1500, stories=[story])
        verdict = await unit._audit_plan(plan, profile)
        tropes = [b for b in verdict.blockers if "/trope]" in b]
        mark = "BLOCKED" if verdict.status == "blocked" else "passed "
        if verdict.status == "blocked":
            blocked += 1
        else:
            passed += 1
        print(f"\n[{mark}] {row['views']:>9,}  {row['title'][:52]}")
        if tropes:
            print(f"    TROPE: {' '.join(tropes[0].split())[:220]}")
        elif verdict.blockers:
            print(f"    other: {' '.join(verdict.blockers[0].split())[:180]}")

    print(f"\n{'=' * 68}")
    print(f"real competitor premises: {passed} passed / {blocked} blocked")
    print("A gate that blocks the videos we are competing with is not "
          "protecting quality.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
