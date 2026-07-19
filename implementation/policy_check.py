"""YouTube Policy Checker CLI — run weekly or on-demand.

Usage:
    python policy_check.py             # fetch + diff all sources
    python policy_check.py --approve 42    # approve pending rule #42
    python policy_check.py --reject 42     # reject pending rule #42
    python policy_check.py --list          # show pending + active rules
    python policy_check.py --list-active   # show active rules only

Schedule: Run every Monday 9AM via cron or task scheduler.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

import structlog
structlog.configure(processors=[structlog.dev.ConsoleRenderer(colors=True)])


def banner(t: str) -> None:
    print("\n" + "=" * 60)
    print(f"  {t}")
    print("=" * 60)


async def cmd_check() -> None:
    from omnicast.config.settings import get_settings
    from omnicast.llm.client import LLMClient
    from omnicast.compliance.policy_fetcher import run_policy_check
    from omnicast.vault.db import get_pending_rules

    settings = get_settings()
    # Use Sonnet for policy analysis — legal text needs accuracy, not speed
    llm = LLMClient(provider="anthropic", model="claude-sonnet-4-6")

    banner("YouTube Policy Check")
    print("  Fetching policy sources (RSS + Playwright)...")
    print("  This may take 30-60s for SPA pages.\n")

    n = await run_policy_check(llm)

    if n == 0:
        print("  [OK] No policy changes detected.")
        return

    print(f"\n  [WARN] {n} new rule(s) pending approval:\n")
    pending = get_pending_rules()
    for r in pending:
        print(f"  Rule #{r['rule_id']}: {r['rule_text'][:80]}")
        if r['diff_context']:
            print(f"    Context: {r['diff_context'][:100]}")
        print(f"    Source : {r['source_url']}")
        print()

    print("  To approve: python policy_check.py --approve <id>")
    print("  To reject : python policy_check.py --reject <id>")
    print("  To list   : python policy_check.py --list")


def cmd_list(active_only: bool = False) -> None:
    from omnicast.vault.db import get_active_rules, get_pending_rules, init_db
    init_db()

    if not active_only:
        pending = get_pending_rules()
        if pending:
            banner(f"Pending Approval ({len(pending)})")
            for r in pending:
                print(f"  #{r['rule_id']} | {r['rule_text'][:90]}")
                print(f"       Source: {r['source_url']}")
                print(f"       Context: {r['diff_context'][:80]}")
                print()
        else:
            print("  [OK] No pending rules.")

    active = get_active_rules()
    banner(f"Active Rules ({len(active)})")
    if active:
        for r in active:
            print(f"  #{r['rule_id']} | {r['rule_text'][:90]}")
            print(f"       Source: {r['source_url']}")
            approved = r.get('approved_at', '')[:10]
            print(f"       Approved: {approved} by {r.get('approved_by', '?')}")
            print()
    else:
        print("  (no active rules — using hardcoded defaults)")


def cmd_approve(rule_id: int) -> None:
    from datetime import datetime, UTC
    from omnicast.vault.db import approve_rule, get_pending_rules, init_db
    init_db()

    pending_ids = [r["rule_id"] for r in get_pending_rules()]
    if rule_id not in pending_ids:
        print(f"  [ERROR] Rule #{rule_id} not found in pending_approval.")
        sys.exit(1)

    now = datetime.now(UTC).isoformat()
    approve_rule(rule_id, approved_by="operator", approved_at=now)
    print(f"  [OK] Rule #{rule_id} approved and now ACTIVE.")
    print("  ComplianceChecker will use this rule on next run.")


def cmd_reject(rule_id: int) -> None:
    from omnicast.vault.db import reject_rule, get_pending_rules, init_db
    init_db()

    pending_ids = [r["rule_id"] for r in get_pending_rules()]
    if rule_id not in pending_ids:
        print(f"  [ERROR] Rule #{rule_id} not found in pending_approval.")
        sys.exit(1)

    reject_rule(rule_id)
    print(f"  [OK] Rule #{rule_id} rejected.")


def main() -> None:
    parser = argparse.ArgumentParser(description="YouTube Policy Checker")
    parser.add_argument("--approve", type=int, metavar="RULE_ID")
    parser.add_argument("--reject", type=int, metavar="RULE_ID")
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--list-active", action="store_true")
    args = parser.parse_args()

    if args.approve:
        cmd_approve(args.approve)
    elif args.reject:
        cmd_reject(args.reject)
    elif args.list:
        cmd_list(active_only=False)
    elif args.list_active:
        cmd_list(active_only=True)
    else:
        asyncio.run(cmd_check())


if __name__ == "__main__":
    main()
