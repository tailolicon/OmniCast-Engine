"""
OmniCast Engine — Flow A: Niche Discovery + Channel Creation
=============================================================
CLI for finding underserved YouTube niches and auto-generating channel configs.

Usage:
    python niche_flow.py --scan                      # Scan YouTube -> display ranked niches
    python niche_flow.py --scan --verbose            # Show raw channel data + signal quality
    python niche_flow.py --list                      # Show last scan results
    python niche_flow.py --create <niche_id>         # Auto-create channel from niche
    python niche_flow.py --create <niche_id> --market UK

Workflow:
    1. --scan  -> scans 40 seed queries, samples ~120 channels, finds viral outliers
    2. Review niche list - check evidence (real channels + real video titles)
    3. --create <niche_id>  -> ChannelBuilderAgent generates channel JSON
    4. Verify channels/{id}.json, then: python content_flow.py --channel <id>
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

import structlog

structlog.configure(processors=[structlog.dev.ConsoleRenderer(colors=True)])

ROOT = Path(__file__).parent
CHANNELS_DIR = ROOT / "channels"
OUTPUT_DIR = ROOT / "output"
NICHE_CACHE = OUTPUT_DIR / "niche_cache.json"
VAULT_DB = OUTPUT_DIR / "vault.db"

CATEGORY_TO_NICHE: dict[str, str] = {
    "finance": "finance",
    "retirement": "finance",
    "crypto": "finance",
    "investing": "finance",
    "real_estate": "finance",
    "health": "health",
    "nutrition": "health",
    "fitness": "health",
    "wellness": "health",
    "mental_health": "psychology",
    "psychology": "psychology",
    "productivity": "psychology",
    "self_help": "psychology",
    "technology": "tech",
    "tech": "tech",
    "ai": "tech",
    "software": "tech",
    "science": "tech",
    "history": "mythology",
    "mythology": "mythology",
    "ancient": "mythology",
    "culture": "mythology",
    "lifestyle": "health",
    "education": "tech",
}


def _safe_print(text: str) -> None:
    try:
        print(text)
    except UnicodeEncodeError:
        print(text.encode("ascii", errors="replace").decode("ascii"))


def banner(title: str) -> None:
    print("\n" + "=" * 65)
    print(f"  {title}")
    print("=" * 65)


def step(name: str, value: str) -> None:
    print(f"  [OK] {name}: {value}")


def _map_niche(category: str) -> str:
    """Map a discovered niche's category to a channel niche bucket.

    A blue-ocean category not in the map is KEPT AS-IS (auto-tagged) rather than
    silently forced to "finance" — the old default made every unmapped niche inherit
    finance's high-RPM brand assumptions, biasing downstream toward the wrong voice/
    monetization profile (Gemini gap #3). Falls back to a neutral bucket only when the
    category is missing entirely."""
    key = (category or "").lower().strip()
    if key in CATEGORY_TO_NICHE:
        return CATEGORY_TO_NICHE[key]
    return key or "lifestyle"


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def _load_cache() -> dict:
    if not NICHE_CACHE.exists():
        return {}
    try:
        return json.loads(NICHE_CACHE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_cache(data: dict) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    NICHE_CACHE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


# ─── Scan command ────────────────────────────────────────────────────────────

async def cmd_scan(verbose: bool = False, market: str = "US", dynamic_seeds: bool = True) -> None:
    from omnicast.config.settings import get_settings
    from omnicast.llm.client import LLMClient
    from omnicast.discovery.niche_scanner import NicheScanner
    from omnicast.discovery.seed_generator import SeedQueryGenerator, MARKETS, FALLBACK_SEEDS
    from omnicast.discovery.key_rotator import YouTubeKeyRotator, QuotaExhaustedError
    from omnicast.agents.niche_discoverer import NicheDiscovererAgent

    settings = get_settings()
    key_pool = settings.youtube_key_pool
    if not key_pool:
        print("  [ERROR] YOUTUBE_API_KEY not set in .env")
        sys.exit(1)

    rotator = YouTubeKeyRotator(key_pool)
    print(f"  YouTube API keys loaded: {rotator.key_count} key(s)")

    cfg = MARKETS.get(market, MARKETS["US"])
    banner(f"OmniCast Niche Discovery — Market: {market} ({cfg.region_code})")
    print("  Videos: published last 90 days only")
    print("  Channels: 1k-5M subs, 30 long-form videos each")
    print("  Shorts (<61s) filtered. views_per_day velocity computed.")
    print("  Supernova: subs<10k + outlier>10x = untapped niche signal\n")

    # ── Step 0: Generate seeds (T0-T4) + Supernova Radar (T5) in parallel ───
    seed_queries = None
    t5_channel_ids: list[str] = []

    if dynamic_seeds:
        print("  [Step 0] Generating dynamic seed queries + Supernova Radar (T5)...")
        _ds_chat = settings.deepseek_chat_model  # non-reasoning, no <think> token waste
        llm_seed = LLMClient(provider="deepseek", model=_ds_chat)
        seed_gen = SeedQueryGenerator(
            llm_client=llm_seed,
            rotator=rotator,
        )
        t_seed = time.perf_counter()
        try:
            # Run T0-T4 seed generation + T5 category sweep concurrently
            seed_task = asyncio.create_task(
                seed_gen.generate(market=market, target_count=40)
            )
            t5_task = asyncio.create_task(
                seed_gen.sweep_categories(market=market, days_back=7, videos_per_category=100)
            )
            seed_results, t5_results = await asyncio.gather(
                seed_task, t5_task, return_exceptions=True
            )
            seed_queries = seed_results if isinstance(seed_results, list) else None
            t5_channel_ids = t5_results if isinstance(t5_results, list) else []
        except QuotaExhaustedError as exc:
            print(f"  [WARN] {exc}")
            seed_queries = None
        seed_elapsed = time.perf_counter() - t_seed

        if seed_queries:
            step("Dynamic seeds generated", f"{len(seed_queries)} queries in {seed_elapsed:.1f}s")
            if verbose:
                print("  Seeds:")
                for i, s in enumerate(seed_queries[:10], 1):
                    print(f"    {i:2}. {s}")
                if len(seed_queries) > 10:
                    print(f"    ... +{len(seed_queries)-10} more")
        else:
            print("  [WARN] Dynamic seed generation failed — using static fallback")
            seed_queries = None

        if t5_channel_ids:
            step("T5 Supernova Radar", f"{len(t5_channel_ids)} channels (cat 19/22/26/27/28, last 7d)")
        else:
            print("  [WARN] T5 category sweep returned no channels")
    else:
        print("  [Step 0] Using static seed queries (--no-dynamic-seeds)")
    print()

    scanner = NicheScanner(market=market, rotator=rotator)
    t0 = time.perf_counter()
    channels = await scanner.scan(
        seed_queries=seed_queries,
        pre_channel_ids=t5_channel_ids or None,
    )
    scan_time = time.perf_counter() - t0

    supernova = sum(1 for c in channels if c.is_supernova)
    viral = sum(1 for c in channels if c.has_viral_proof)
    emerging = sum(1 for c in channels if c.is_emerging)

    step("Channels sampled", str(len(channels)))
    step("Supernova (<10k subs, outlier>10x)", str(supernova))
    step("Viral proof (outlier >= 5x)", str(viral))
    step("Emerging channels (<300k subs)", str(emerging))
    step("Scan time", f"{scan_time:.1f}s")

    if not channels:
        print("  [ERROR] No channels found. Check YouTube API key / quota.")
        sys.exit(1)

    # Show raw signal quality if verbose
    if verbose:
        banner("Raw Channel Signal (sorted: supernova > viral > outlier)")
        print(f"  {'Channel':<32} {'Subs':>7} {'Med':>8} {'Outlier':>8} {'v/day':>8} {'Flags':>12}")
        print("  " + "-" * 82)
        sorted_ch = sorted(
            channels,
            key=lambda c: (c.is_supernova, c.has_viral_proof, c.top_outlier_ratio),
            reverse=True,
        )
        for ch in sorted_ch[:25]:
            flags = ""
            if ch.is_supernova:
                flags += "[NOVA]"
            elif ch.has_viral_proof:
                flags += "[V]"
            if ch.is_emerging:
                flags += "[E]"
            subs_str = f"{ch.subscribers // 1000}k" if ch.subscribers >= 1000 else str(ch.subscribers)
            med_str = f"{int(ch.median_views):,}"
            # top vpd
            vpd = ch.top_videos[0].get("views_per_day", 0) if ch.top_videos else 0
            vpd_str = f"{vpd:,.0f}"
            _safe_print(
                f"  {ch.channel_name:<32} {subs_str:>7} {med_str:>8} "
                f"{ch.top_outlier_ratio:>7.1f}x {vpd_str:>8} {flags:>12}"
            )
        print()
        print("  Top signal videos (verified API data):")
        for ch in sorted_ch[:12]:
            if (ch.is_supernova or ch.has_viral_proof) and ch.top_videos:
                v = ch.top_videos[0]
                nova = "[NOVA] " if ch.is_supernova else ""
                _safe_print(f"    {nova}[{ch.channel_name}] {v['title'][:65]}")
                _safe_print(f"      {v['views']:,} views | {v.get('views_per_day',0):,.0f}/day | {v['outlier_x']}x median")
        print()

    if len(channels) < 10:
        print("  [WARN] Low channel count may reduce niche quality.")

    # LLM clustering
    print(f"\n  [AI] Clustering {len(channels)} channels into niches...")
    _ds_chat  = settings.deepseek_chat_model  # non-reasoning, no <think> token waste
    _ds_flash = settings.deepseek_flash_model
    llm       = LLMClient(provider="deepseek", model=_ds_chat)
    flash_llm = LLMClient(provider="deepseek", model=_ds_flash)
    agent = NicheDiscovererAgent(llm=llm, flash_llm=flash_llm)

    t1 = time.perf_counter()
    niches = await agent.discover(channels, top_n=15)
    llm_time = time.perf_counter() - t1

    step("LLM time", f"{llm_time:.1f}s")
    step("Niches found", str(len(niches)))

    if not niches:
        print("  [ERROR] Niche discovery returned no results.")
        print("  Try: python niche_flow.py --scan --verbose to inspect raw signal")
        sys.exit(1)

    # Cache results
    niche_dicts = []
    for n in niches:
        niche_dicts.append({
            "niche_id": n.niche_id,
            "niche_name": n.niche_name,
            "category": n.category,
            "audience_description": n.audience_description,
            "pain_points": n.pain_points,
            "content_triggers": n.content_triggers,
            "demand_score": n.demand_score,
            "gap_score": n.gap_score,
            "rpm_score": n.rpm_score,
            "specificity_score": n.specificity_score,
            "total_score": n.total_score,
            "estimated_rpm": n.estimated_rpm,
            "example_channels": n.example_channels,
            "breakout_titles": n.breakout_titles,
            "why_opportunity": n.why_opportunity,
            "evidence": n.evidence,
        })

    # ── Semantic dedup against existing vault niches ──────────────────────────
    niche_dicts = await _dedup_against_vault(niche_dicts, settings)

    # Serialize raw channel signal for filter quality review
    channels_raw = [
        {
            "channel_id": c.channel_id,
            "channel_name": c.channel_name,
            "subscribers": c.subscribers,
            "median_views": c.median_views,
            "top_outlier_ratio": c.top_outlier_ratio,
            "avg_engagement_rate": c.avg_engagement_rate,
            "comment_view_ratio": c.comment_view_ratio,
            "video_count_sampled": c.video_count_sampled,
            "seed_query": c.seed_query,
            "is_supernova": c.is_supernova,
            "is_emerging": c.is_emerging,
            "has_viral_proof": c.has_viral_proof,
            "top_videos": c.top_videos,   # [{title, views, views_per_day, outlier_x}]
        }
        for c in channels
    ]

    _save_cache({
        "niches": niche_dicts,
        "channels_analyzed": len(channels),
        "viral_proof_count": viral,
        "scanned_at": _now(),
        "channels_raw": channels_raw,
    })

    # Velocity cross-scan (Claude gap #2): so với lần quét trước — niche lặp lại
    # với điểm tăng = đang tăng tốc (ưu tiên); lặp lại điểm giảm = nguội dần.
    # Snapshot trước đọc từ chính niche_results.json trước khi bị ghi đè.
    try:
        import json as _json, re as _re
        _prev_path = Path("output/niche_results.json")
        _prev = {}
        if _prev_path.exists():
            _old = _json.loads(_prev_path.read_text(encoding="utf-8"))
            for _n in (_old.get("niches") or []):
                _nm = str(_n.get("niche_name") or _n.get("name") or "").lower()
                _toks = frozenset(_re.findall(r"[a-z0-9]+", _nm))
                if _toks:
                    _prev[_toks] = float(_n.get("score") or _n.get("total_score") or 0)
        for _n in niche_dicts:
            _nm = str(_n.get("niche_name") or _n.get("name") or "").lower()
            _toks = set(_re.findall(r"[a-z0-9]+", _nm))
            _match = None
            for _pt, _ps in _prev.items():
                _ov = len(_toks & _pt) / max(1, len(_toks | _pt))
                if _ov >= 0.5:
                    _match = _ps; break
            _cur = float(_n.get("score") or _n.get("total_score") or 0)
            if _match is None:
                _n["momentum"] = "new"
            else:
                _d = round(_cur - _match, 1)
                _n["momentum"] = ("rising" if _d > 0 else "cooling" if _d < 0 else "flat")
                _n["momentum_delta"] = _d
    except Exception as _exc:  # không bao giờ làm gãy scan vì tính năng phụ
        logger.warning("momentum annotate failed", error=str(_exc)) if 'logger' in dir() else None

    # Also sync to niche_results.json for dashboard API
    _sync_to_api(niche_dicts, len(channels))

    # Display results
    banner(f"Top {len(niches)} Underserved Niches")
    for i, niche in enumerate(niches, 1):
        _safe_print(niche.display(i))
        print()

    print("=" * 65)
    print(f"  Scan: {scan_time:.1f}s + LLM: {llm_time:.1f}s = {scan_time + llm_time:.1f}s total")
    print(f"  Cached: output/niche_cache.json")
    print(f"\n  Next steps:")
    print(f"    python niche_flow.py --list              # review again")
    if niches:
        print(f"    python niche_flow.py --create {niches[0].niche_id}")


# ─── List command ─────────────────────────────────────────────────────────────

async def cmd_list() -> None:
    cache = _load_cache()
    niches = cache.get("niches", [])
    if not niches:
        print("  No cached results. Run: python -X utf8 niche_flow.py --scan")
        return

    scanned_at = cache.get("scanned_at", "unknown")
    channels_analyzed = cache.get("channels_analyzed", 0)
    viral_count = cache.get("viral_proof_count", 0)

    banner(f"Cached Niches — {len(niches)} found")
    print(f"  Scanned: {scanned_at[:19]}")
    print(f"  Channels: {channels_analyzed} sampled, {viral_count} with viral proof")
    print()

    for i, n in enumerate(niches, 1):
        score = n.get("total_score", 0)
        nid = n.get("niche_id", "")
        name = n.get("niche_name", "")
        audience = n.get("audience_description", "")
        rpm = n.get("estimated_rpm", 0)
        why = n.get("why_opportunity", "")[:80]
        demand = n.get("demand_score", 0)
        gap = n.get("gap_score", 0)
        rpm_s = n.get("rpm_score", 0)
        spec = n.get("specificity_score", 0)

        print(f"  #{i} [{score}/100] {name}")
        print(f"       ID      : {nid}")
        print(f"       Audience: {audience}")
        print(f"       Scores  : demand={demand} gap={gap} rpm={rpm_s} spec={spec}")
        print(f"       Est.RPM : ${rpm:.0f}")
        print(f"       Gap     : {why}")

        evidence = n.get("evidence", [])
        if evidence:
            print("       Evidence:")
            for ev in evidence[:2]:
                ch = ev.get("channel", "")
                title = ev.get("title", "")[:55]
                views = ev.get("views", 0)
                ox = ev.get("outlier_x", 0)
                print(f"         [{ch}] {title}")
                print(f"           {views:,} views ({ox}x median)")

        breakouts = n.get("breakout_titles", [])
        if breakouts:
            print("       Breakouts:")
            for t in breakouts[:2]:
                print(f"         * {t[:70]}")
        print()

    print(f"  Create channel: python -X utf8 niche_flow.py --create <niche_id>")


# ─── Channels command ────────────────────────────────────────────────────────

async def cmd_channels(min_outlier: float = 0.0, only_supernova: bool = False) -> None:
    """Print raw channel signal table from last scan for filter quality review."""
    cache = _load_cache()
    channels = cache.get("channels_raw", [])
    if not channels:
        print("  No raw channel data. Run scan first (new format saves channels_raw).")
        return

    # Apply filters
    rows = [c for c in channels if c["top_outlier_ratio"] >= min_outlier]
    if only_supernova:
        rows = [c for c in rows if c["is_supernova"]]

    scanned_at = cache.get("scanned_at", "unknown")
    print(f"\n  Raw Channels — {len(rows)} shown (scanned {scanned_at[:10]})")
    print(f"  Filter: outlier>={min_outlier}x {'| supernova only' if only_supernova else ''}\n")
    print(f"  {'Channel':<38} {'Subs':>7} {'Outlier':>9} {'v/day':>8} {'Eng%':>5} {'Cmnt%':>6} {'Videos':>7}  Flags  Seed")
    print("  " + "-" * 120)

    rows.sort(key=lambda c: c["top_outlier_ratio"], reverse=True)
    for c in rows:
        flags = ""
        if c["is_supernova"]:   flags += "[NOVA]"
        if c["has_viral_proof"] and not c["is_supernova"]: flags += "[V]"
        if c["is_emerging"]:    flags += "[E]"
        name = c["channel_name"][:37]
        subs = f"{c['subscribers']//1000}k" if c['subscribers'] >= 1000 else str(c['subscribers'])
        outlier = f"{c['top_outlier_ratio']:.1f}x"
        vpd = f"{c['top_videos'][0]['views_per_day']:,.0f}" if c['top_videos'] else "—"
        eng = f"{c['avg_engagement_rate']*100:.2f}"
        cmnt = f"{c['comment_view_ratio']*100:.3f}"
        seed = c["seed_query"][:35]
        print(f"  {name:<38} {subs:>7} {outlier:>9} {vpd:>8} {eng:>5} {cmnt:>6} {c['video_count_sampled']:>7}  {flags:<12} {seed}")

        # Show top video for context
        if c["top_videos"]:
            v = c["top_videos"][0]
            title = v["title"][:70]
            print(f"    -> {v['views']:>9,} views | {v['views_per_day']:>8,.0f}/day | {title}")
    print()


# ─── Niche overlap checker ────────────────────────────────────────────────────

async def _check_niche_overlap(
    new_niche: dict,
    existing_channels: list[tuple[str, dict]],
    llm,
) -> list[dict]:
    """Check semantic overlap + Content Pillar fit for each existing channel.

    PROMPT (DeepSeek Flash, ~$0.0002/call):
      Given an existing channel config and a new niche, determine:
      1. Do they target the same core audience? (overlap)
      2. Would this niche work as a Content Pillar series on that channel?

    Returns list of conflict dicts:
      {
        "channel_id": str,
        "channel_name": str,
        "overlap_score": 0.0-1.0,
        "content_pillar_fit": bool,
        "pillar_name": str,     # suggested series name if fit=True
        "reason": str,
      }
    """
    import asyncio
    import re

    async def _check_one(channel_id: str, cfg: dict) -> dict | None:
        existing_desc = (
            f"Channel ID: {channel_id}\n"
            f"Channel Name: {cfg.get('name', channel_id)}\n"
            f"Niche/Category: {cfg.get('niche', '')}\n"
            f"Brand voice: {cfg.get('brand_voice', '')[:200]}\n"
            f"Audience profile: {json.dumps(cfg.get('audience', {}))[:300]}\n"
            f"Content pillars: {json.dumps(cfg.get('content_pillars', []))[:200]}"
        )
        new_desc = (
            f"Niche ID: {new_niche.get('niche_id', '')}\n"
            f"Niche Name: {new_niche.get('niche_name', '')}\n"
            f"Audience: {new_niche.get('audience_description', '')[:300]}\n"
            f"Pain points: {json.dumps(new_niche.get('pain_points', []))[:200]}\n"
            f"Content triggers: {json.dumps(new_niche.get('content_triggers', []))[:200]}"
        )
        prompt = (
            "You are a YouTube channel strategy analyst evaluating niche compatibility.\n\n"
            f"EXISTING CHANNEL:\n{existing_desc}\n\n"
            f"NEW NICHE:\n{new_desc}\n\n"
            "Answer with EXACTLY this JSON (no markdown, no extra text):\n"
            "{\n"
            '  "overlap_score": 0.0,\n'
            '  "content_pillar_fit": false,\n'
            '  "pillar_name": "",\n'
            '  "reason": "one sentence"\n'
            "}\n\n"
            "Rules:\n"
            "- overlap_score: 0.0-1.0. How much do these two niches target the SAME core audience?\n"
            "  0.9+ = almost identical audience\n"
            "  0.7-0.9 = same broad audience, different angle\n"
            "  0.5-0.7 = partial overlap\n"
            "  < 0.5 = different audiences\n"
            "- content_pillar_fit: true if this niche topic would work as a SERIES on the existing channel\n"
            "  (same audience would watch both, doesn't dilute channel identity)\n"
            "- pillar_name: if content_pillar_fit=true, suggest a series name (e.g. 'Sleep & Recovery Series')\n"
            "- reason: explain your assessment in one sentence"
        )
        try:
            response = await llm.complete(
                system="You are a YouTube channel strategy analyst. Return valid JSON only.",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=200,
            )
            text = response.content.strip()
            m = re.search(r'\{.*?\}', text, re.DOTALL)
            if not m:
                return None
            data = json.loads(m.group())
            score = float(data.get("overlap_score", 0.0))
            # Only return if meaningful overlap
            if score < 0.5:
                return None
            return {
                "channel_id":         channel_id,
                "channel_name":       cfg.get("name", channel_id),
                "overlap_score":      score,
                "content_pillar_fit": bool(data.get("content_pillar_fit", False)),
                "pillar_name":        data.get("pillar_name", ""),
                "reason":             data.get("reason", ""),
            }
        except Exception as exc:
            structlog.get_logger().warning("Overlap check failed", channel=channel_id, error=str(exc))
            return None

    tasks = [_check_one(cid, cfg) for cid, cfg in existing_channels]
    results = await asyncio.gather(*tasks)
    conflicts = [r for r in results if r is not None]
    # Sort by overlap_score descending
    conflicts.sort(key=lambda x: x["overlap_score"], reverse=True)
    return conflicts


# ─── Create command ───────────────────────────────────────────────────────────

async def cmd_create(niche_id: str, market: str = "US") -> None:
    from omnicast.config.settings import get_settings
    from omnicast.llm.client import LLMClient
    from omnicast.agents.channel_builder import ChannelBuilderAgent

    cache = _load_cache()
    niches = cache.get("niches", [])
    if not niches:
        print("  [ERROR] No cached niches. Run: python -X utf8 niche_flow.py --scan")
        sys.exit(1)

    niche_data = next((n for n in niches if n.get("niche_id") == niche_id), None)
    if niche_data is None:
        print(f"  [ERROR] Niche '{niche_id}' not found.")
        print(f"  Available: {', '.join(n.get('niche_id', '') for n in niches)}")
        sys.exit(1)

    settings = get_settings()

    # ── Check for existing channels with same or overlapping niche ────────────
    if CHANNELS_DIR.exists():
        existing_channels: list[tuple[str, dict]] = []
        exact_match: str | None = None

        for existing_path in CHANNELS_DIR.glob("*.json"):
            try:
                cfg = json.loads(existing_path.read_text(encoding="utf-8"))
                channel_id = existing_path.stem
                existing_niche = str(cfg.get("niche", cfg.get("niche_id", "")))
                # Fast exact/substring match first
                if niche_id in existing_niche or niche_id == cfg.get("niche_id", ""):
                    exact_match = channel_id
                else:
                    existing_channels.append((channel_id, cfg))
            except Exception:
                continue

        if exact_match:
            print(f"  [WARN] Niche '{niche_id}' already has a channel: {exact_match}")
            print(f"  [INFO] To run pipeline: python content_flow.py --channel {exact_match}")
            print()
            ans = input("  Create another channel anyway? [y/N] ").strip().lower()
            if ans != "y":
                print("  Aborted.")
                sys.exit(0)

        elif existing_channels:
            print(f"  [AI] Checking {len(existing_channels)} existing channel(s) for audience overlap...")
            _ds_flash = settings.deepseek_flash_model
            _llm_check = LLMClient(provider="deepseek", model=_ds_flash)
            conflicts = await _check_niche_overlap(niche_data, existing_channels, _llm_check)

            if conflicts:
                print()
                print(f"  [OVERLAP] Found {len(conflicts)} semantically similar channel(s):")
                for c in conflicts:
                    score_pct = int(c["overlap_score"] * 100)
                    fit_tag = " [PILLAR FIT]" if c["content_pillar_fit"] else ""
                    print(f"    • {c['channel_id']} ({score_pct}% overlap){fit_tag}")
                    print(f"      {c['reason']}")
                    if c["content_pillar_fit"] and c["pillar_name"]:
                        print(f"      → Suggested series: \"{c['pillar_name']}\"")
                print()

                # Best pillar fit
                best_pillar = next(
                    (c for c in conflicts if c["content_pillar_fit"]), None
                )

                if best_pillar:
                    ch_name = best_pillar["channel_name"]
                    ch_id   = best_pillar["channel_id"]
                    pillar  = best_pillar["pillar_name"] or niche_data.get("niche_name", "")
                    print(f"  ╔══════════════════════════════════════════════════════════╗")
                    print(f"  ║  This niche fits [{ch_name}] as a Content Pillar        ║")
                    print(f"  ║  Suggested series: \"{pillar}\"")
                    print(f"  ╚══════════════════════════════════════════════════════════╝")
                    print()
                    print(f"  [y] Add \"{pillar}\" as Content Pillar → update channels/{ch_id}.json")
                    print(f"  [n] Create a new standalone channel for this niche")
                    print(f"  [q] Cancel")
                    print()
                    ans = input("  Choice [y/n/q]: ").strip().lower()

                    if ans == "q":
                        print("  Aborted.")
                        sys.exit(0)
                    elif ans == "y":
                        _add_content_pillar(ch_id, pillar, niche_data)
                        print(f"  [OK] Content Pillar \"{pillar}\" added to {ch_id}.")
                        print(f"  Run: python content_flow.py --channel {ch_id}")
                        sys.exit(0)
                    # else: fall through to create new channel
                    print()
                else:
                    # Overlap but no pillar fit → ask if continue
                    ans = input("  Create new channel anyway? [y/N] ").strip().lower()
                    if ans != "y":
                        print("  Aborted.")
                        sys.exit(0)
            else:
                print("  [OK] No audience overlap detected.")

    banner(f"Channel Builder -- {niche_data['niche_name']}")
    print(f"  Niche ID : {niche_id}")
    print(f"  Audience : {niche_data.get('audience_description', '')}")
    print(f"  Market   : {market}")
    print(f"  Est. RPM : ${niche_data.get('estimated_rpm', 0):.0f}")
    print()

    _ds_chat = settings.deepseek_chat_model  # non-reasoning, no <think> token waste
    _ds_flash = settings.deepseek_flash_model
    llm = LLMClient(provider="deepseek", model=_ds_chat)
    flash_llm = LLMClient(provider="deepseek", model=_ds_flash)

    # ── Stage 0: Channel Name Debate ─────────────────────────────────────────
    from omnicast.agents.channel_name_debate import ChannelNameDebateAgent, render_debate_table

    print("  [AI] Running name debate (Generate → Handle Check → Score → Select)...")
    t_debate = time.perf_counter()
    debate_agent = ChannelNameDebateAgent(
        flash_llm=flash_llm,
        chat_llm=llm,
        yt_api_key=settings.youtube_api_key or "",
    )
    debate_result = await debate_agent.debate(niche_data, n_candidates=6)
    debate_elapsed = time.perf_counter() - t_debate
    print(f"  [OK] Debate complete ({debate_elapsed:.1f}s)")
    print()
    print(render_debate_table(debate_result))
    print()

    # User confirmation loop
    approved_name = debate_result.winner.name
    approved_channel_id = debate_result.winner.channel_id

    while True:
        print(f"  [Enter]  Accept winner: \"{approved_name}\"")
        print(f"  [1-{len(debate_result.all_candidates)}]     Pick a different candidate")
        print(f"  [m]      Enter name manually")
        print(f"  [q]      Abort")
        print()
        choice = input("  Choice: ").strip().lower()

        if choice in ("", "enter"):
            break  # accept winner
        elif choice == "q":
            print("  Aborted.")
            sys.exit(0)
        elif choice == "m":
            manual = input("  Channel name: ").strip()
            if manual:
                approved_name = manual
                import re as _re_name
                approved_channel_id = _re_name.sub(
                    r"[^a-z0-9_]", "", manual.lower().replace(" ", "_")
                )[:25].rstrip("_")
            break
        elif choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(debate_result.all_candidates):
                chosen = debate_result.all_candidates[idx]
                approved_name = chosen.name
                approved_channel_id = chosen.channel_id
                print(f"  Selected: \"{approved_name}\"")
            else:
                print(f"  Invalid. Enter 1-{len(debate_result.all_candidates)}.")
            break
        else:
            print("  Invalid input.")

    print()
    print(f"  [✓] Name approved: \"{approved_name}\"  (id: {approved_channel_id})")
    print()
    print("  [AI] Generating channel config (brand voice, hook, competitors)...")

    agent = ChannelBuilderAgent(llm=llm, youtube_api_key=settings.youtube_api_key or "")

    t0 = time.perf_counter()
    cfg = await agent.build(
        niche=niche_data,
        market=market,
        approved_name=approved_name,
        approved_channel_id=approved_channel_id,
    )
    elapsed = time.perf_counter() - t0

    if cfg is None:
        print("  [ERROR] Channel builder failed. Check logs above.")
        sys.exit(1)

    niche_enum = _map_niche(cfg.niche)
    channel_dict = cfg.to_dict()
    channel_dict["niche"] = niche_enum
    channel_dict["market"] = market
    channel_dict["channel_type"] = "hub"
    channel_dict["language"] = "en"
    channel_dict["ref_channels"] = cfg.competitor_handles
    channel_dict["source_niche_id"] = niche_id   # link back → niche discovery

    CHANNELS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = CHANNELS_DIR / f"{cfg.channel_id}.json"
    out_path.write_text(
        json.dumps(channel_dict, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    # Sync to vault.db (best-effort — vault.py --save is optional step)
    _sync_channel_to_vault(niche_id, cfg.channel_id)

    step("Channel ID", cfg.channel_id)
    step("Name", cfg.name)
    step("Niche (enum)", niche_enum)
    step("Brand voice", cfg.brand_voice[:65])
    step("Tone", cfg.tone)
    step("Visual style", cfg.visual_style)
    step("Hook format", cfg.hook_format[:70])
    step("RPM floor", f"${cfg.rpm_floor:.0f}")
    step("Competitor handles", str(len(cfg.competitor_handles)))
    step("Build time", f"{elapsed:.1f}s")
    step("Saved", str(out_path))

    print(f"\n  Audience profile:")
    audience = cfg.audience
    if audience:
        print(f"    Age range  : {audience.get('age_range', '')}")
        pain = audience.get('pain_points', [])
        if pain:
            print(f"    Pain points: {' | '.join(pain[:3])}")
        triggers = audience.get('content_triggers', [])
        if triggers:
            print(f"    Triggers   : {' | '.join(triggers[:3])}")

    print(f"\n  Competitor handles validated:")
    for h in cfg.competitor_handles:
        print(f"    {h}")

    print(f"\n  NEXT: Review {out_path.name}, then run:")
    print(f"    python content_flow.py --channel {cfg.channel_id} --phase 1")


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _add_content_pillar(channel_id: str, pillar_name: str, niche_data: dict) -> None:
    """Add a new Content Pillar to an existing channel JSON.

    Modifies channels/{channel_id}.json in-place.
    Adds/extends the 'content_pillars' array.
    """
    path = CHANNELS_DIR / f"{channel_id}.json"
    if not path.exists():
        print(f"  [WARN] Channel file not found: {path}")
        return
    try:
        cfg = json.loads(path.read_text(encoding="utf-8"))
        pillars: list[dict] = cfg.get("content_pillars", [])
        pillars.append({
            "pillar_name":        pillar_name,
            "source_niche_id":    niche_data.get("niche_id", ""),
            "audience":           niche_data.get("audience_description", ""),
            "pain_points":        niche_data.get("pain_points", []),
            "content_triggers":   niche_data.get("content_triggers", []),
            "estimated_rpm":      niche_data.get("estimated_rpm", 0),
            "added_at":           _now(),
        })
        cfg["content_pillars"] = pillars
        path.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception as exc:
        print(f"  [ERROR] Failed to update channel JSON: {exc}")


async def _dedup_against_vault(
    niche_dicts: list[dict],
    settings,
) -> list[dict]:
    """Semantic dedup: filter new niches against existing vault niches.

    PROMPT (DeepSeek Flash): see agents/niche_dedup.py
    Called in cmd_scan() after LLM clustering, before saving cache.

    Flow:
      1. Load vault niches (status != archived)
      2. For each new niche, check similarity vs all vault niches
      3. Auto-skip duplicates (score >= 0.85)
      4. Ask user for borderline (score 0.60-0.85)
      5. Return filtered list

    Returns original list unchanged if vault is empty or dedup fails.
    """
    from omnicast.llm.client import LLMClient
    from omnicast.agents.niche_dedup import NicheDedupAgent

    # Load existing vault niches
    vault_niches: list[dict] = []
    try:
        from omnicast.vault.db import init_db, list_niches
        from omnicast.vault.models import NicheStatus
        init_db(VAULT_DB)
        records = list_niches(path=VAULT_DB)
        vault_niches = [
            {
                "niche_id": r.niche_id,
                "niche_name": r.niche_name,
                "audience_description": r.niche_data.get("audience_description", ""),
                "category": r.niche_data.get("category", ""),
                "status": r.status.value,
            }
            for r in records
            if r.status != NicheStatus.ARCHIVED
        ]
    except Exception as exc:
        structlog.get_logger().warning("Vault load failed for dedup", error=str(exc))
        return niche_dicts  # fail open

    if not vault_niches:
        return niche_dicts  # nothing to dedup against

    print(f"\n  [Dedup] Checking {len(niche_dicts)} niches vs {len(vault_niches)} vault entries...")
    _ds_flash = settings.deepseek_flash_model
    llm_dedup = LLMClient(provider="deepseek", model=_ds_flash)
    agent = NicheDedupAgent(llm=llm_dedup)

    kept, duplicates, borderline = await agent.filter_niches(niche_dicts, vault_niches)

    if duplicates:
        print(f"  [Dedup] Auto-skipped {len(duplicates)} duplicate(s):")
        for n in duplicates:
            dd = n.get("_dedup", {})
            match_id = dd.get("top_match_id", "?")
            score_pct = int(dd.get("top_match_score", 0) * 100)
            reason = dd.get("top_match_reason", "")
            print(f"    ✗ {n['niche_name']} ({score_pct}% match → {match_id})")
            print(f"      {reason}")

    if borderline:
        print(f"\n  [Dedup] {len(borderline)} borderline niche(s) — similar but not identical:")
        accepted_borderline = []
        for n in borderline:
            dd = n.get("_dedup", {})
            match_id = dd.get("top_match_id", "?")
            score_pct = int(dd.get("top_match_score", 0) * 100)
            reason = dd.get("top_match_reason", "")
            print(f"\n    ? {n['niche_name']} ({score_pct}% similar to [{match_id}])")
            print(f"      {reason}")
            ans = input("      Keep this niche? [y/N] ").strip().lower()
            if ans == "y":
                accepted_borderline.append(n)
            else:
                print(f"      Skipped.")

        kept = kept + accepted_borderline

    # Strip _dedup metadata before saving
    for n in kept:
        n.pop("_dedup", None)

    step(
        "Dedup result",
        f"{len(kept)} kept / {len(duplicates)} skipped / {len(borderline) - len([n for n in borderline if n.get('_dedup')])} borderline accepted",
    )
    return kept


def _sync_channel_to_vault(niche_id: str, channel_id: str) -> None:
    """Mark niche ACTIVE in vault.db when a channel is created from it.

    Best-effort: silently skips if niche not in vault (vault.py --save is optional).
    Chain: niche_cache.json → (optional) vault.db niches → channels/*.json
    """
    try:
        from omnicast.vault.db import init_db, mark_niche_activated
        init_db(VAULT_DB)
        updated = mark_niche_activated(niche_id, channel_id, VAULT_DB)
        if updated:
            step("Vault", f"Niche {niche_id} → ACTIVE (channel_id={channel_id})")
    except Exception:
        pass  # vault sync is optional, don't abort channel creation


def _sync_to_api(niche_dicts: list[dict], channels_analyzed: int) -> None:
    """Keep output/niche_results.json in sync for dashboard API."""
    try:
        from omnicast.api.state import write_niche_results
        write_niche_results(niche_dicts, channels_analyzed)
    except Exception:
        pass


# ─── Entry point ──────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="OmniCast Flow A -- Niche Discovery + Channel Creation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -X utf8 niche_flow.py --scan                           # US, dynamic seeds
  python -X utf8 niche_flow.py --scan --market JP               # Japan market
  python -X utf8 niche_flow.py --scan --market KR --verbose     # Korea, show raw signal
  python -X utf8 niche_flow.py --scan --no-dynamic-seeds        # use static fallback seeds
  python -X utf8 niche_flow.py --list
  python -X utf8 niche_flow.py --create perimenopause_health --market US
        """,
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--scan", action="store_true", help="Scan YouTube -> rank niches")
    group.add_argument("--list", action="store_true", help="Show cached niches")
    group.add_argument("--channels", action="store_true", help="Show raw channel signal from last scan")
    group.add_argument("--create", metavar="NICHE_ID", help="Create channel from niche")

    parser.add_argument(
        "--market",
        default="US",
        choices=["US", "UK", "AU", "CA", "JP", "KR"],
        help="Target market (default: US)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="With --scan: show raw channel signal + generated seeds",
    )
    parser.add_argument(
        "--no-dynamic-seeds",
        action="store_true",
        help="Skip Step 0 seed generation, use static fallback seeds",
    )
    parser.add_argument(
        "--min-outlier",
        type=float,
        default=0.0,
        metavar="X",
        help="With --channels: only show channels with outlier >= Xx (e.g. --min-outlier 5)",
    )
    parser.add_argument(
        "--supernova-only",
        action="store_true",
        help="With --channels: only show supernova channels (<10k subs, outlier>10x)",
    )

    args = parser.parse_args()

    if args.scan:
        asyncio.run(cmd_scan(
            verbose=args.verbose,
            market=args.market,
            dynamic_seeds=not args.no_dynamic_seeds,
        ))
    elif args.list:
        asyncio.run(cmd_list())
    elif args.channels:
        asyncio.run(cmd_channels(
            min_outlier=args.min_outlier,
            only_supernova=args.supernova_only,
        ))
    elif args.create:
        asyncio.run(cmd_create(args.create, market=args.market))


if __name__ == "__main__":
    main()
