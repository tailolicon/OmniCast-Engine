"""Withdraw a product that a later gate says should never have passed.

Gates get tightened. When they do, work that already carries `approved` and
`production_ready` does not re-run itself — it sits in output/products/ with a
green flag, and the topic it claimed stays `used`, so the corrected pipeline
cannot even replace it.

That is how a build the operator rejected on sight ends up being the newest
approved script on disk. This retracts one: it demotes the product's meta,
records WHY on the product itself, and frees the topic so a corrected run can
take it. Nothing is deleted — the draft, its variants and its critic feedback
stay exactly where they are, because they are the evidence that the old gate
was wrong.

Usage:
  python scripts/retract_product.py <product_dir> --reason "..."
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("product_dir")
    ap.add_argument("--reason", required=True)
    ap.add_argument("--free-topic", action="store_true",
                    help="also set the topic back to queued so a corrected "
                         "run may claim it")
    args = ap.parse_args()

    pdir = Path(args.product_dir)
    meta_path = pdir / "meta.json"
    if not meta_path.exists():
        print(f"REJECTED: no meta.json at {pdir}")
        return 1
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    if not (meta.get("approved") or meta.get("production_ready")):
        print(f"already retracted or never approved: {pdir.name}")
        return 0

    was = {k: meta.get(k) for k in
           ("approved", "script_approved", "production_ready", "content_locked",
            "score", "stage")}
    meta.update({
        "approved": False, "script_approved": False,
        "production_ready": False, "content_locked": False,
        "stage": "retracted",
        "retracted_at": datetime.now(timezone.utc).isoformat(),
        "retracted_reason": args.reason,
        "retracted_from": was,
    })
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2),
                         encoding="utf-8")
    print(f"retracted {pdir.name}: {was} -> stage=retracted")

    if args.free_topic:
        sys.path.insert(0, str(ROOT / "src"))
        from omnicast.vault import db as vdb

        vault = ROOT / "output" / "vault.db"
        topic_id = vdb.make_topic_id(meta["channel"], meta["topic"])
        con = sqlite3.connect(vault)
        try:
            cur = con.execute(
                "UPDATE topics SET status='queued' WHERE topic_id=? "
                "AND status='used'", (topic_id,))
            con.commit()
        finally:
            con.close()
        print(f"topic {topic_id} freed: {cur.rowcount} row(s) back to queued")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
