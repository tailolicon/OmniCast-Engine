"""Run a real discovery pass for a channel and report the calibration state.

Production caller for DiscoveryOrchestrator outside the API server: loads the
channel profile, runs every configured scanner against live sources, persists
the shadow-scoring corpus (see discovery/shadow_log.py), then summarizes the
accumulated corpus with scoring_calibration.summarize so the v2 promotion
decision is always grounded in the latest evidence.

Usage:
    .venv/Scripts/python.exe scripts/run_discovery.py [--channel senior_wealth_us]

Artifacts:
    output/shadow_scoring.jsonl                     (append — corpus)
    output/research/<channel>/discovery_run_<id>.json (topics + briefs + calibration)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--channel", default="senior_wealth_us")
    args = parser.parse_args()

    from omnicast.config.channel import ChannelProfile
    from omnicast.discovery import shadow_log
    from omnicast.discovery.orchestrator import DiscoveryOrchestrator
    from omnicast.discovery.scoring_calibration import summarize

    raw = json.loads(
        (ROOT / "channels" / f"{args.channel}.json").read_text(encoding="utf-8")
    )
    channel = ChannelProfile(**raw)
    orchestrator = DiscoveryOrchestrator.for_channel(channel)
    print(f"Scanners: {[type(s).__name__ for s in orchestrator.scanners]}")

    result = await orchestrator.run()

    print(f"\nRUN {orchestrator.run_id}: raw={result.total_raw} "
          f"approved={result.approved_count} review={result.review_count} "
          f"failed_sources={result.failed_sources} "
          f"duration={result.duration_seconds:.1f}s")

    # Calibration state over the WHOLE accumulated corpus, this channel only —
    # cross-channel rows would mix niches the scorer weighs differently.
    corpus = [r for r in shadow_log.read_rows()
              if r.get("channel_id") == args.channel]
    report = summarize(corpus)

    out_dir = ROOT / "output" / "research" / args.channel
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "run_id": orchestrator.run_id,
        "ran_at": datetime.now(timezone.utc).isoformat(),
        "channel_id": args.channel,
        "sources": [
            {"source": r.source, "success": r.success, "count": r.count}
            for r in result.source_results
        ],
        "topics": [
            {
                "title": s.raw.title,
                "source": str(s.raw.source),
                "action": s.action,
                "total_v1": getattr(s, "total_score_v1", None),
                "total_v2": getattr(s, "total_score_v2", None),
                "outlier_ratio": (getattr(s.raw, "raw_metrics", {}) or {}).get(
                    "outlier_ratio"
                ),
            }
            for s in result.scored_topics
        ],
        "briefs": [b.model_dump(mode="json") for b in result.briefs],
        "calibration": report.as_dict(),
    }
    dest = out_dir / f"discovery_run_{orchestrator.run_id}.json"
    dest.write_text(json.dumps(payload, ensure_ascii=False, indent=1),
                    encoding="utf-8")

    print(f"\nCALIBRATION (corpus for {args.channel}): rows={report.rows} "
          f"usable={report.usable_rows} youtube={report.youtube_rows} "
          f"ready_to_promote={report.ready_to_promote}")
    for note in report.notes:
        print(f"  NOTE {note}")
    print(f"\nSaved {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
