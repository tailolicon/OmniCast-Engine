"""CLI for the competitor-craft learning chain.

    python scripts/run_craft_learning.py --channel senior_wealth_us [--dry-run]

Idempotent: re-running after new captions land redoes the labelling, the
statistics and the publication decision from what is on disk.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from omnicast.analytics.craft_pipeline import run_craft_learning  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--channel", default="senior_wealth_us")
    ap.add_argument("--dry-run", action="store_true",
                    help="build artifacts + report, never touch the vault")
    args = ap.parse_args()

    rep = run_craft_learning(args.channel, ROOT, publish=not args.dry_run)
    print(json.dumps(asdict(rep), ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
