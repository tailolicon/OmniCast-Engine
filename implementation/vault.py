"""
OmniCast Engine — Niche Vault CLI
==================================
Persistent niche library with health monitoring.

Commands:
    python vault.py --save <niche_id>          Save one niche from latest scan
    python vault.py --save --all               Save all top-10 niches from latest scan
    python vault.py --list                     Show full vault
    python vault.py --list --status hot        Show only HOT niches (act now)
    python vault.py --list --market US         Filter by market
    python vault.py --health-check <niche_id>  Check one niche
    python vault.py --health-check --all       Check all watching niches
    python vault.py --archive <niche_id>       Archive a niche (remove from active list)
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

CACHE_PATH  = Path(__file__).parent / "output" / "niche_cache.json"
VAULT_DB    = Path(__file__).parent / "output" / "vault.db"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _load_cache() -> dict:
    if not CACHE_PATH.exists():
        print("  [ERROR] No niche_cache.json found. Run: python niche_flow.py --scan")
        sys.exit(1)
    with open(CACHE_PATH, encoding="utf-8") as f:
        return json.load(f)


def _build_channel_id_map(cache: dict) -> dict[str, str]:
    """Map channel_name → channel_id from channels_raw."""
    return {
        ch["channel_name"]: ch["channel_id"]
        for ch in cache.get("channels_raw", [])
        if ch.get("channel_id") and ch.get("channel_name")
    }


def _build_channel_query_map(cache: dict) -> dict[str, str]:
    """Map channel_name → seed_query from channels_raw."""
    return {
        ch["channel_name"]: ch.get("seed_query", "")
        for ch in cache.get("channels_raw", [])
        if ch.get("channel_name")
    }


def _niche_to_record(niche: dict, market: str, cache: dict):
    """Convert niche dict from cache → NicheRecord for vault storage."""
    from omnicast.vault.models import NicheRecord, NicheStatus

    ch_id_map = _build_channel_id_map(cache)
    ch_query_map = _build_channel_query_map(cache)

    # Extract evidence channel IDs by matching channel names
    evidence = niche.get("evidence", [])
    channel_names = list(dict.fromkeys(e["channel"] for e in evidence if e.get("channel")))
    channel_ids = [ch_id_map[n] for n in channel_names if n in ch_id_map]

    # Seed queries for competitor search
    seed_queries = list(dict.fromkeys(
        ch_query_map[n] for n in channel_names if n in ch_query_map and ch_query_map[n]
    ))

    now_iso = datetime.now(timezone.utc).isoformat()
    score = niche.get("total_score", niche.get("current_health", 0))

    return NicheRecord(
        niche_id=niche["niche_id"],
        niche_name=niche["niche_name"],
        market=market,
        status=NicheStatus.WATCHING,
        original_score=score,
        current_health=score,
        saved_at=now_iso,
        last_checked=None,
        evidence_channel_ids=channel_ids,
        seed_queries=seed_queries,
        niche_data=niche,
    )


# ── Commands ──────────────────────────────────────────────────────────────────

def cmd_save(niche_id: str | None, save_all: bool, market: str) -> None:
    from omnicast.vault import db
    from omnicast.vault.display import console

    db.init_db(VAULT_DB)
    cache = _load_cache()
    niches = cache.get("niches", [])

    if save_all:
        targets = niches
    elif niche_id:
        targets = [n for n in niches if n["niche_id"] == niche_id]
        if not targets:
            available = [n["niche_id"] for n in niches]
            console.print(f"  [red]Niche '{niche_id}' not in latest scan.[/red]")
            console.print(f"  Available: {', '.join(available)}")
            sys.exit(1)
    else:
        console.print("  [red]Specify --save <niche_id> or --save --all[/red]")
        sys.exit(1)

    saved = 0
    for niche in targets:
        existing = db.get_niche(niche["niche_id"], VAULT_DB)
        if existing:
            console.print(
                f"  [dim]Already in vault:[/dim] {niche['niche_id']} "
                f"(status={existing.status.value}, score={existing.current_health})"
            )
            continue
        record = _niche_to_record(niche, market, cache)
        db.upsert_niche(record, VAULT_DB)
        console.print(
            f"  [green]✓ Saved:[/green] {record.niche_id}  "
            f"[score={record.original_score}, channels={len(record.evidence_channel_ids)}]"
        )
        saved += 1

    console.print(f"\n  {saved} niche(s) saved to vault → output/vault.db")


def cmd_list(status_filter: str | None, market: str | None) -> None:
    from omnicast.vault import db
    from omnicast.vault.display import console, print_hot_niches, print_vault_table
    from omnicast.vault.models import NicheStatus

    db.init_db(VAULT_DB)

    status_enum = None
    if status_filter:
        try:
            status_enum = NicheStatus(status_filter.lower())
        except ValueError:
            valid = [s.value for s in NicheStatus]
            console.print(f"  [red]Unknown status '{status_filter}'. Valid: {valid}[/red]")
            sys.exit(1)

    records = db.list_niches(status=status_enum, market=market, path=VAULT_DB)

    if status_enum == NicheStatus.HOT:
        print_hot_niches(records)
    else:
        print_vault_table(records, market=market)


def cmd_archive(niche_id: str) -> None:
    from omnicast.vault import db
    from omnicast.vault.display import console
    from omnicast.vault.models import NicheStatus

    db.init_db(VAULT_DB)
    record = db.get_niche(niche_id, VAULT_DB)
    if not record:
        console.print(f"  [red]Niche '{niche_id}' not in vault.[/red]")
        sys.exit(1)
    db.update_status(niche_id, NicheStatus.ARCHIVED, record.current_health, VAULT_DB)
    console.print(f"  [dim]Archived: {niche_id}[/dim]")


async def _run_health_check(niche_id: str | None, check_all: bool) -> None:
    from omnicast.vault import db
    from omnicast.vault.display import (
        console, print_check_line, print_health_results, print_quota_status,
    )
    from omnicast.vault.health import check_all as health_check_all
    from omnicast.vault.health import check_niche
    from omnicast.vault.models import NicheStatus
    from omnicast.vault import db as vault_db
    from omnicast.config.settings import get_settings
    from omnicast.discovery.key_rotator import YouTubeKeyRotator

    vault_db.init_db(VAULT_DB)
    settings = get_settings()
    key_pool = settings.youtube_key_pool
    if not key_pool:
        console.print("  [red]YOUTUBE_API_KEY not set in .env[/red]")
        sys.exit(1)

    rotator = YouTubeKeyRotator(key_pool)
    print_quota_status(rotator)

    if check_all:
        # Only check non-archived, non-active niches
        records = [
            r for r in vault_db.list_niches(path=VAULT_DB)
            if r.status not in (NicheStatus.ARCHIVED, NicheStatus.ACTIVE)
        ]
        if not records:
            console.print("  [dim]No niches to check. Vault is empty or all archived.[/dim]")
            return
        console.print(
            f"\n  Running health check for {len(records)} niche(s)...\n"
        )
    elif niche_id:
        record = vault_db.get_niche(niche_id, VAULT_DB)
        if not record:
            console.print(f"  [red]Niche '{niche_id}' not in vault.[/red]")
            sys.exit(1)
        records = [record]
        console.print(f"\n  Checking {niche_id}...\n")
    else:
        console.print("  [red]Specify --health-check <niche_id> or --health-check --all[/red]")
        sys.exit(1)

    t0 = time.perf_counter()
    results = await health_check_all(records, rotator)
    elapsed = time.perf_counter() - t0

    now_iso = datetime.now(timezone.utc).isoformat()

    for result in results:
        print_check_line(result)

        # Update DB
        from omnicast.vault.models import HealthLog
        from omnicast.vault import db as vdb

        # Store health notes in niche_data for HOT panel display
        record = vdb.get_niche(result.niche_id, VAULT_DB)
        if record:
            niche_data = dict(record.niche_data)
            niche_data["_last_health_notes"] = result.notes
            record = record.__class__(
                **{**record.__dict__, "niche_data": niche_data}
            )
            vdb.upsert_niche(record, VAULT_DB)

        vdb.update_status(result.niche_id, result.new_status, result.new_score, VAULT_DB)
        vdb.update_last_checked(result.niche_id, now_iso, VAULT_DB)

        status_change = None
        if result.old_status != result.new_status:
            status_change = f"{result.old_status.value}→{result.new_status.value}"

        vdb.insert_log(HealthLog(
            log_id=None,
            niche_id=result.niche_id,
            scan_date=now_iso,
            new_videos_count=result.new_videos_count,
            avg_new_vpd=result.avg_new_vpd,
            dedicated_competitors=result.dedicated_competitors,
            micro_outlier_found=result.micro_outlier_found,
            health_score=result.new_score,
            status_change=status_change,
            notes="; ".join(result.notes),
        ), VAULT_DB)

    print_health_results(results, elapsed)


def cmd_health_check(niche_id: str | None, check_all: bool) -> None:
    asyncio.run(_run_health_check(niche_id, check_all))


# ── CLI entry point ───────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="OmniCast Niche Vault — persistent niche library + health monitor",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # Save
    parser.add_argument("--save", nargs="?", const="__ALL__", metavar="NICHE_ID",
                        help="Save niche to vault (omit ID + use --all for all top-10)")
    parser.add_argument("--all", action="store_true",
                        help="Apply --save or --health-check to all niches")

    # List
    parser.add_argument("--list", action="store_true",
                        help="List vault contents")
    parser.add_argument("--status", metavar="STATUS",
                        help="Filter by status: hot|watching|active|stale|archived")

    # Health check
    parser.add_argument("--health-check", nargs="?", const="__ALL__",
                        metavar="NICHE_ID",
                        help="Run health check (omit ID + use --all for all niches)")

    # Archive
    parser.add_argument("--archive", metavar="NICHE_ID",
                        help="Archive a niche")

    # Shared
    parser.add_argument("--market", default="US", metavar="MARKET",
                        help="Market code (US|UK|AU|CA). Default: US")

    args = parser.parse_args()

    if args.save is not None:
        save_all = args.save == "__ALL__" or args.all
        niche_id = None if save_all else args.save
        cmd_save(niche_id, save_all, args.market)

    elif args.list:
        market_filter = args.market if args.market != "US" else None
        cmd_list(status_filter=args.status, market=market_filter)

    elif args.health_check is not None:
        check_all = args.health_check == "__ALL__" or args.all
        niche_id = None if check_all else args.health_check
        cmd_health_check(niche_id, check_all)

    elif args.archive:
        cmd_archive(args.archive)

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
