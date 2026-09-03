"""Build and live-verify a pre-writing YMYL evidence pack.

This is the same stage the script pipeline runs automatically, exposed as a
small diagnostic so source failures can be audited without buying a full
script generation.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--topic", required=True)
    parser.add_argument("--output", default="")
    args = parser.parse_args()

    from omnicast.agents.evidence_research import EvidenceResearchAgent
    from omnicast.pipeline.steps import _llm_client

    llm = _llm_client("anthropic", db_path=ROOT / "output" / "vault.db")
    pack = await EvidenceResearchAgent(llm=llm).execute(args.topic)
    payload = pack.model_dump_json(indent=2)
    if args.output:
        path = Path(args.output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(payload, encoding="utf-8")
        print(path.resolve())
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
