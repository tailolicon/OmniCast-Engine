"""Rich terminal display for Niche Vault."""
from __future__ import annotations

import io
import sys
from datetime import datetime, timezone

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import box
from rich.text import Text
from rich.columns import Columns

from omnicast.vault.models import HealthCheckResult, NicheRecord, NicheStatus

def _utf8_console() -> Console:
    """Return a Console that writes UTF-8 even on Windows CP1252 terminals."""
    try:
        _file = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    except AttributeError:
        _file = sys.stdout
    return Console(width=120, legacy_windows=False, file=_file)

console = _utf8_console()

_STATUS_ICON = {
    NicheStatus.HOT:      "🔴",
    NicheStatus.WATCHING: "🟡",
    NicheStatus.ACTIVE:   "🟢",
    NicheStatus.STALE:    "🔘",
    NicheStatus.ARCHIVED: "⬛",
}
_STATUS_COLOR = {
    NicheStatus.HOT:      "bold red",
    NicheStatus.WATCHING: "yellow",
    NicheStatus.ACTIVE:   "bold green",
    NicheStatus.STALE:    "dim",
    NicheStatus.ARCHIVED: "dim",
}


def _age_str(saved_at: str) -> str:
    try:
        dt = datetime.fromisoformat(saved_at.replace("Z", "+00:00"))
        days = (datetime.now(timezone.utc) - dt).days
        if days == 0: return "today"
        if days == 1: return "1d"
        return f"{days}d"
    except Exception:
        return "?"


def _checked_str(last_checked: str | None) -> str:
    if not last_checked:
        return "[dim]never[/dim]"
    try:
        dt = datetime.fromisoformat(last_checked.replace("Z", "+00:00"))
        diff = datetime.now(timezone.utc) - dt
        hours = int(diff.total_seconds() / 3600)
        if hours == 0: return "just now"
        if hours < 24: return f"{hours}h ago"
        return f"{diff.days}d ago"
    except Exception:
        return "?"


def _trend_str(record: NicheRecord) -> str:
    """Return trend arrow based on score delta from last health log."""
    from omnicast.vault import db as vault_db
    from pathlib import Path
    vault_db_path = Path(__file__).resolve().parents[3] / "output" / "vault.db"
    logs = vault_db.get_logs(record.niche_id, limit=2, path=vault_db_path)
    if len(logs) < 2:
        # Only 1 or 0 logs — compare vs original score
        delta = record.current_health - record.original_score
    else:
        delta = logs[0].health_score - logs[1].health_score

    if delta > 2:
        return f"[bold green]↑ +{delta}[/bold green]"
    if delta < -2:
        return f"[bold red]↓ {delta}[/bold red]"
    return "[dim]━[/dim]"


def print_vault_table(records: list[NicheRecord], market: str | None = None) -> None:
    """Print full vault list as Rich table."""
    if not records:
        console.print("[dim]  Vault is empty. Run: python vault.py --save --all[/dim]")
        return

    hot = sum(1 for r in records if r.status == NicheStatus.HOT)
    watching = sum(1 for r in records if r.status == NicheStatus.WATCHING)
    stale = sum(1 for r in records if r.status == NicheStatus.STALE)
    active = sum(1 for r in records if r.status == NicheStatus.ACTIVE)

    market_str = f"  │  {market} Market" if market else ""
    header = (
        f"  NICHE VAULT{market_str}  │  {len(records)} niches  │  "
        f"[red]{hot} HOT[/red] · [yellow]{watching} watching[/yellow] · "
        f"[green]{active} active[/green] · [dim]{stale} stale[/dim]"
    )
    console.print(Panel(header, box=box.DOUBLE_EDGE, padding=(0, 1)))
    console.print()

    table = Table(
        box=box.SIMPLE,
        show_header=True,
        header_style="bold dim",
        padding=(0, 1),
        expand=False,
    )
    table.add_column("",       width=2,  no_wrap=True)   # icon
    table.add_column("Status", width=8,  no_wrap=True)
    table.add_column("Score",  width=5,  justify="right", no_wrap=True)
    table.add_column("Trend",  width=8,  no_wrap=True)
    table.add_column("Niche",  width=46, no_wrap=True)
    table.add_column("Mkt",    width=4,  no_wrap=True)
    table.add_column("Age",    width=6,  no_wrap=True)
    table.add_column("Checked",width=10, no_wrap=True)

    for r in records:
        icon  = _STATUS_ICON[r.status]
        color = _STATUS_COLOR[r.status]
        label = Text(r.status.value.upper(), style=color)
        score_str = Text(str(r.current_health), style=color)
        trend = _trend_str(r)
        name  = Text(r.niche_name[:46], style=color, no_wrap=True)
        table.add_row(
            icon, label, score_str, trend, name,
            r.market, _age_str(r.saved_at), _checked_str(r.last_checked),
        )

    console.print(table)
    console.print(
        "  [dim][HOT] = Act now · [WATCH] = Monitor · "
        "[ACTIVE] = Channel live · [STALE] = Skip[/dim]"
    )


def print_hot_niches(records: list[NicheRecord]) -> None:
    """Print detailed panels for HOT niches."""
    hot = [r for r in records if r.status == NicheStatus.HOT]
    if not hot:
        console.print("  [yellow]No HOT niches right now. Run health check first:[/yellow]")
        console.print("  python vault.py --health-check --all")
        return

    console.print(Panel(
        f"  🔴 HOT NICHES — ACT NOW  ({len(hot)})",
        box=box.DOUBLE_EDGE,
        style="bold red",
        padding=(0, 1),
    ))
    console.print()

    for i, r in enumerate(hot, 1):
        evidence = r.niche_data.get("evidence", [])
        top_ev = evidence[0] if evidence else {}
        logs = r.niche_data.get("_last_health_notes", [])

        score_trend = f"{r.original_score} → {r.current_health}"
        trend_arrow = "↑↑" if r.current_health > r.original_score else (
            "→" if r.current_health == r.original_score else "↓"
        )

        lines = [
            f"  Market: [bold]{r.market}[/bold]  │  Saved: {_age_str(r.saved_at)} ago  │  "
            f"Category: {r.niche_data.get('category', '?')}  │  "
            f"Est. RPM: [bold]${r.niche_data.get('estimated_rpm', 0):.0f}[/bold]",
            "",
        ]

        if logs:
            lines.append("  [bold]WHY HOT:[/bold]")
            for note in logs:
                lines.append(f"  ✦ {note}")
            lines.append("")

        lines.append(f"  [bold]SIGNAL TREND:[/bold]  {score_trend}  {trend_arrow}")

        if top_ev:
            vid_id = top_ev.get("video_id", "")
            link_str = f"  [dim](youtu.be/{vid_id})[/dim]" if vid_id else ""
            lines += [
                "",
                f"  [bold]TOP BREAKOUT:[/bold]  \"{top_ev.get('title', '')[:70]}\"{link_str}",
                f"  {top_ev.get('views', 0):,} views · "
                f"{top_ev.get('views_per_day', 0):,.0f}/day · "
                f"{top_ev.get('outlier_x', 0)}x median",
            ]

        lines += [
            "",
            f"  [dim]→ python niche_flow.py --create {r.niche_id}[/dim]",
        ]

        console.print(Panel(
            "\n".join(lines),
            title=f"[bold red]#{i}  {r.niche_name}  [{r.current_health}/100][/bold red]",
            border_style="red",
            padding=(0, 0),
        ))
        console.print()


def print_health_results(
    results: list[HealthCheckResult],
    elapsed: float,
) -> None:
    """Print health check progress summary."""
    console.print()

    went_hot   = [r for r in results if r.new_status == NicheStatus.HOT
                  and r.old_status != NicheStatus.HOT]
    went_stale = [r for r in results if r.new_status == NicheStatus.STALE
                  and r.old_status != NicheStatus.STALE]

    # Per-niche result lines (already printed during check; this is summary)
    console.rule(style="dim")
    parts = []
    if went_hot:
        parts.append(
            f"[bold red]{len(went_hot)} niche(s) → HOT[/bold red]  "
            f"→  python vault.py --list --status hot"
        )
    if went_stale:
        names = ", ".join(r.niche_id for r in went_stale)
        parts.append(f"[dim]{len(went_stale)} niche(s) → STALE: {names}[/dim]")

    parts.append(
        f"[dim]Health check: {len(results)} niches · {elapsed:.1f}s[/dim]"
    )
    for p in parts:
        console.print(f"  {p}")
    console.rule(style="dim")


def print_quota_status(rotator) -> None:
    """Print color-coded quota warning before health check run."""
    total = rotator.key_count
    available = rotator.available_count
    used = total - available
    pct_used = used / total if total > 0 else 1.0

    # Each key ≈ 10k units/day, search.list = 100 units
    est_units = available * 10_000
    est_searches = est_units // 100

    if pct_used >= 0.8:
        color = "bold red"
        warn = "⛔ QUOTA CRITICAL — add new API keys before running!"
    elif pct_used >= 0.5:
        color = "yellow"
        warn = "⚠ Quota low — monitor closely"
    else:
        color = "dim green"
        warn = ""

    line = (
        f"  YouTube API: [{color}]{available}/{total} keys available[/{color}]"
        f"  │  est. quota: [{color}]{est_units:,} units · {est_searches} searches[/{color}]"
    )
    if warn:
        line += f"  │  [{color}]{warn}[/{color}]"
    console.print(line)
    console.print()


def print_check_line(result: HealthCheckResult) -> None:
    """Print one-line result for a single niche during health check."""
    delta_str = f"(+{result.score_delta})" if result.score_delta >= 0 \
                else f"({result.score_delta})"
    icon = _STATUS_ICON[result.new_status]
    color = _STATUS_COLOR[result.new_status]
    name = result.niche_id[:45]
    transition = ""
    if result.old_status != result.new_status:
        transition = (
            f"  [bold]{result.old_status.value}→{result.new_status.value}[/bold]"
        )
    console.print(
        f"  Checking [dim]{name:<45}[/dim] "
        f"[{color}]{icon} {result.new_status.value.upper():<8}[/{color}] "
        f"[dim]{delta_str:>5}[/dim]"
        f"{transition}"
    )
