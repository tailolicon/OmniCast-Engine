"""Near-Miss Hospital: resume a SAVED needs_edit candidate and try to finish it.

External review 2026-07-20 (both reviewers): candidates rejected at the release
door are serialized with every blocker quoted, then never read again — each new
run regenerates from zero at roughly 3x the cost of finishing the saved one.
This driver reconstructs the judged state from a product folder's
narrative_audit.json and runs the pipeline's hospital_pass (the same repair
machinery and acceptance rules as a live run). It never flips production_ready:
output goes to `hospital_script.txt` + `hospital_report.json` in the product
folder for a HUMAN to review.

Usage:
    .venv/Scripts/python.exe scripts/finish_candidate.py --product <product_dir>
        [--profile true_horror_strict_v1]

Do not run while a live batch is generating (one account, one pipeline).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
os.environ.setdefault("OMNICAST_CLAUDE_BACKEND", "cli")


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--product", required=True, help="product folder with narrative_audit.json")
    parser.add_argument("--profile", default="true_horror_strict_v1")
    args = parser.parse_args()

    product = Path(args.product)
    audit_path = product / "narrative_audit.json"
    if not audit_path.exists():
        print(f"REJECTED: no narrative_audit.json in {product}")
        return 1
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    if not audit.get("plan") or not audit.get("stories"):
        print("REJECTED: audit has no plan/stories to resume (0-prose failure?)")
        return 1

    from omnicast.agents.narrative_pipeline import (
        CompilationPlan,
        NamedChannelStrategy,
        NarrativeUnitPipeline,
        StoryDraft,
    )
    from omnicast.config.narrative_quality import resolve_script_profile
    from omnicast.config.settings import get_settings
    from omnicast.pipeline.steps import _llm_client, _narrative_role_clients

    plan = CompilationPlan.model_validate(audit["plan"])
    stories = [StoryDraft.model_validate(s) for s in audit["stories"]]
    strategy = NamedChannelStrategy.from_quality_profile(
        resolve_script_profile(args.profile)
    )

    # The default (DeepSeek-first) roles ARE the deepseek clients; the live
    # pipeline builds them and passes them in. Without this, critic/compliance/
    # plan_audit resolve to None and _audit_stories fails instantly (0.0s,
    # zero_score). claude_only mode ignores these and uses Claude CLI for all.
    settings = get_settings()
    vault_path = Path(__file__).resolve().parents[1] / "output" / "vault.db"
    deepseek_pro = _llm_client("deepseek", model=settings.deepseek_pro_model, db_path=vault_path)
    deepseek_flash = _llm_client("deepseek", model=settings.deepseek_flash_model, db_path=vault_path)
    roles = _narrative_role_clients(
        settings, vault_path=vault_path,
        deepseek_pro=deepseek_pro, deepseek_flash=deepseek_flash,
    )
    pipe = NarrativeUnitPipeline(
        planner_llm=roles["planner"],
        writer_llm=roles["writer"],
        plan_repair_llm=roles["plan_repair"],
        patch_llm=roles["patch"],
        critic_llm=roles["critic"],
        plan_audit_llm=roles["plan_audit"],
        annotation_llm=roles["annotation"],
        annotation_fallback_llm=roles["annotation_fallback"],
        compliance_llm=roles["compliance"],
        compliance_escalation_llm=roles["compliance_escalation"],
        critic_fallback_llm=roles["critic_fallback"],
        plan_audit_escalation_llm=roles["plan_audit_escalation"],
        release_challenger_llm=roles["challenger"],
        quality_strategy=strategy,
        judge_mode=roles["judge_mode"],
        model_roles=roles["model_roles"],
    )

    start = time.perf_counter()
    result = await pipe.hospital_pass(plan, stories, strategy)
    elapsed = time.perf_counter() - start

    score = result["score"]
    lines = [f"[{s.story_id}] {s.title}\n\n{s.narration}" for s in result["stories"]]
    (product / "hospital_script.txt").write_text(
        "\n\n----\n\n".join(lines), encoding="utf-8"
    )
    report = {
        "content_lockable": result["content_lockable"],
        "total_score": score.total_score,
        "before_total_score": (audit.get("scorecard") or {}).get("total_score"),
        "repair_waves": result["repair_waves"],
        "gate_failures": [f.message for f in result["gate"].failures],
        "remaining_blockers": [
            f"[{i.severity}] {i.story_id}: {i.problem}"
            for i in score.story_issues if i.severity in {"critical", "major"}
        ],
        "call_counts": result["call_counts"],
        "notional_cost_usd": result["notional_cost_usd"],
        "elapsed_s": round(elapsed, 1),
        "note": "hospital output — human review required; production_ready never set here",
    }
    (product / "hospital_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    verdict = "CONTENT_LOCKABLE" if result["content_lockable"] else "STILL_BLOCKED"
    print(f"{verdict} after {elapsed:.1f}s | score {report['before_total_score']} -> "
          f"{score.total_score} | waves {result['repair_waves']} | "
          f"blockers left {len(report['remaining_blockers'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
