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
    parser.add_argument("--brief-file", default="",
                        help="path to a steering file (wins over --brief; the "
                             "iteration loop accumulates directives there — a "
                             "fresh gen has no memory of prior rounds)")
    parser.add_argument(
        "--editorial-feedback-file",
        default="",
        help=(
            "plain-text operator/reviewer rejection applied to the resumed "
            "draft before routing; forces a Writer revision without weakening "
            "the normal duplicate-topic gate"),
    )
    parser.add_argument("--angle-file", default="",
                        help="JSON EditorialAngle (thesis/against/stake/turn/"
                             "walk_away/evidence_ids). Validated BEFORE "
                             "generation — see omnicast.agents.editorial_angle")
    parser.add_argument("--angle-ledger", default="",
                        help="fact_ledger.json the angle's evidence_ids must "
                             "resolve against (a prior build's ledger for the "
                             "same topic). Without it the ids are unchecked.")
    parser.add_argument(
        "--evidence-file", default="",
        help="operator evidence pack (JSON with entries[]) to verify and merge "
             "into the machine-checked evidence — survives the official-SSA "
             "fast path that discards news evidence; every entry is refetched "
             "and quote-verified before joining")
    parser.add_argument(
        "--duration-min", type=int, default=0,
        help="per-run target duration override (minutes); a news-frame video "
             "wants 8, not the channel's evergreen 14. The 8-minute mid-roll "
             "platform floor still applies underneath.")
    parser.add_argument(
        "--resume-from",
        default="",
        help=(
            "existing needs_edit product directory for the same channel/topic; "
            "the pipeline reparses its raw variant with current code and resumes "
            "gates/repair instead of paying for a fresh first draft"),
    )
    parser.add_argument(
        "--resume-variant",
        default="",
        help=(
            "optional variant id inside --resume-from, for example "
            "claude_revised; fails if that exact artifact is absent"),
    )
    args = parser.parse_args()
    if args.brief_file:
        args.brief = Path(args.brief_file).read_text(encoding="utf-8")
    editorial_feedback = ""
    if args.editorial_feedback_file:
        editorial_feedback = Path(
            args.editorial_feedback_file).read_text(encoding="utf-8")
    if len(args.topic.split()) < 3:
        print(f"REJECTED/FAILED after 0.0s: topic too short: {args.topic!r}")
        return 1

    # THE ARGUMENT IS DECIDED BEFORE THE WRITING, AND IT IS CHECKED HERE.
    # `--angle` is a free-text hint the writer may ignore; every script this
    # channel produced was accurate and argued nothing. A validated angle fails
    # in a second, before a 30-minute generation spends itself on a topic
    # restated with a verb in it.
    angle_obj = None
    if args.angle_file:
        import json as _json

        from omnicast.agents.editorial_angle import EditorialAngle, check_angle
        raw = _json.loads(Path(args.angle_file).read_text(encoding="utf-8"))
        angle_obj = EditorialAngle(
            thesis=raw.get("thesis", ""), against=raw.get("against", ""),
            stake=raw.get("stake", ""), turn=raw.get("turn", ""),
            walk_away=raw.get("walk_away", ""),
            evidence_ids=tuple(raw.get("evidence_ids", ())))
        problems = check_angle(angle_obj)
        if args.angle_ledger:
            from omnicast.agents.editorial_angle import verify_evidence
            problems += verify_evidence(
                angle_obj,
                _json.loads(Path(args.angle_ledger).read_text(encoding="utf-8")))
        else:
            # Say it out loud. An unchecked evidence list looks exactly like a
            # checked one in the log, and that is how decoration survives.
            print("angle: evidence_ids NOT resolved (--angle-ledger not given)")
        if problems:
            print("REJECTED/FAILED after 0.0s: the angle is not an argument yet")
            for p in problems:
                print(f"  - {p}")
            return 1
        print(f"angle OK: {angle_obj.thesis}")

    from omnicast.pipeline.steps import StepContext, _step_script

    brief_text = args.brief
    content_angle = args.angle
    if angle_obj is not None:
        # The block leads, because a constraint appended after 2,000 words of
        # accumulated steering is a suggestion.
        brief_text = (angle_obj.as_prompt_block() + "\n" + brief_text).strip()
        content_angle = content_angle or angle_obj.thesis

    inputs = {"channel_id": args.channel, "topic": args.topic}
    if args.duration_min:
        inputs["target_duration_min"] = args.duration_min
    if args.evidence_file:
        inputs["evidence_file"] = args.evidence_file
    if angle_obj is not None:
        # Hand the VALIDATED angle to the pipeline as an object so the writer
        # is bound to it and the planner is skipped — prose-only steering let
        # the planner override it (see steps.py claude_first branch).
        inputs["editorial_angle"] = angle_obj.as_dict()
    if args.resume_from:
        inputs["resume_from"] = args.resume_from
    if args.resume_variant:
        inputs["resume_variant"] = args.resume_variant
    if editorial_feedback.strip():
        inputs["editorial_feedback"] = editorial_feedback
    for key, val in (("content_angle", content_angle), ("pain_point", args.pain),
                     ("audience", args.audience), ("operator_desc", brief_text)):
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

    # DID IT ACTUALLY ARGUE THE THING? Committing to an angle up front changes
    # nothing if the draft drifts back into explaining the topic — which is the
    # default a language model returns to over 2,000 words. Reported, not
    # enforced: this is a shape check, and a shape check should not be able to
    # veto a script the rubric and the ledger both passed.
    if angle_obj is not None:
        from omnicast.agents.editorial_angle import angle_is_delivered
        path = out.get("script_path") or out.get("script_file") or ""
        try:
            text = Path(path).read_text(encoding="utf-8") if path else ""
        except OSError:
            text = ""
        if text:
            gaps = angle_is_delivered(angle_obj, text)
            if gaps:
                print("ANGLE DELIVERY — the draft drifts off its own claim:")
                for g in gaps:
                    print(f"  - {g}")
            else:
                print("ANGLE DELIVERY: the claim is stated early, defended, "
                      "and landed at the end")
        else:
            print(f"ANGLE DELIVERY: not checked (no readable script at {path!r})")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
