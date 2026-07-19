"""
OmniCast Engine — Channel-Driven Pipeline Runner
=================================================
Runs the full content pipeline for a specific channel.
Channel config loaded from channels/{channel_id}.json.

Usage:
    python run_pipeline.py
    python run_pipeline.py --channel fin_retirement_us
    python run_pipeline.py --channel health_nutrition_us
    python run_pipeline.py --channel myth_greek_us
    python run_pipeline.py --topic "5 Finance Mistakes to Avoid in 2026"
"""

from __future__ import annotations

import asyncio
import argparse
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://omnicast:dev_password@localhost:5432/omnicast")
os.environ.setdefault("RABBITMQ_URL", "amqp://omnicast:dev_password@localhost:5672/")

sys.path.insert(0, str(Path(__file__).parent / "src"))

import structlog

structlog.configure(
    processors=[
        structlog.dev.ConsoleRenderer(colors=True),
    ]
)
log = structlog.get_logger()

from omnicast.config.settings import get_settings
from omnicast.config.channel import ChannelProfile, ChannelProfileLoader
from omnicast.config.niches import get_niche_config
from omnicast.llm.client import LLMClient
from omnicast.agents.writer import WriterAgent
from omnicast.agents.critic import CriticAgent
from omnicast.agents.thinking import ThinkingAgent
from omnicast.agents.orchestrator import DebateOrchestrator, DebateConfig
from omnicast.agents.compliance import ComplianceChecker
from omnicast.agents.evolution import EvolutionAgent
from omnicast.agents.visual_director import VisualDirectorAgent
from omnicast.services.budget import BudgetManager
from omnicast.models.script import TopicBrief
from omnicast.models.enums import TopicSource, Niche, Market, ChannelType
from omnicast.models.schemas import BrandConfig
from omnicast.media.orchestrator import MediaPipelineOrchestrator
from omnicast.upload.orchestrator import UploadPipelineOrchestrator
from omnicast.upload.models import UploadMetadata
from omnicast.discovery.orchestrator import DiscoveryOrchestrator
from omnicast.agents.channel_architect import ChannelArchitectAgent
from omnicast.agents.niche_discoverer import NicheDiscovererAgent
from omnicast.discovery.niche_scanner import NicheScanner

CHANNELS_DIR = Path(__file__).parent / "channels"

# Default channel (finance, general) — used when no --channel specified
DEFAULT_CHANNEL = ChannelProfile(
    channel_id="fin_general_us",
    name="Finance Insider",
    niche=Niche.FINANCE,
    sub_niche="",
    market=Market.US,
    visual_style="dark_cinematic",
    voice_profile="kokoro_en_us_v1",
    brand_voice="authoritative financial insider",
    tone="direct",
    ref_channels=["Graham Stephan", "Andrei Jikh"],
    trends_keywords=["investing", "stock market", "personal finance", "retirement", "401k"],
    rss_feeds=[
        "https://feeds.finance.yahoo.com/rss/2.0/headline",
        "https://www.cnbc.com/id/10000664/device/rss/rss.html",
    ],
    rpm_floor=7.0,
    target_duration_min=10,
)


def banner(title: str) -> None:
    width = 60
    print("\n" + "=" * width)
    print(f"  {title}")
    print("=" * width)


def step(name: str, result: str) -> None:
    print(f"  [OK] {name}: {result}")


async def load_channel(channel_id: str | None) -> ChannelProfile:
    """Load channel profile from JSON or return default."""
    if channel_id is None:
        return DEFAULT_CHANNEL
    loader = ChannelProfileLoader(CHANNELS_DIR)
    try:
        return await loader.load(channel_id)
    except FileNotFoundError:
        print(f"  [WARN] Channel '{channel_id}' not found in {CHANNELS_DIR} -- using default")
        return DEFAULT_CHANNEL


async def run_pipeline(channel_id: str | None = None, topic: str | None = None, phase_only: int | None = None) -> None:
    settings = get_settings()

    # --- Load Channel --------------------------------------------------------
    channel = await load_channel(channel_id)
    niche_cfg = get_niche_config(channel.niche.value, channel.sub_niche)

    banner("OmniCast Full Pipeline")
    print(f"  Mode:    {settings.omnicast_mode}")
    print(f"  Channel: {channel.channel_id} -- {channel.name}")
    print(f"  Niche:   {channel.niche.value}" + (f".{channel.sub_niche}" if channel.sub_niche else ""))
    print(f"  Style:   {channel.visual_style} | Voice: {channel.brand_voice[:50]}")
    print(f"  Hook:    {niche_cfg.hook_format[:70]}")
    print(f"  SFX:     {niche_cfg.sfx_primary} / {niche_cfg.sfx_secondary}")

    # --- Phase 1: Topic Discovery + Channel Architect -----------------------
    banner(f"Phase 1 - Topic Discovery ({channel.name})")

    t_discovery = time.perf_counter()
    discovered_brief: TopicBrief | None = None

    if topic:
        print(f"  [MANUAL] Topic override: {topic}")
    else:
        try:
            # Step 1: Scan YouTube competitors for raw outliers
            orchestrator_discovery = DiscoveryOrchestrator.for_channel(channel)
            discovery_result = await orchestrator_discovery.run()

            step("Raw topics found", str(discovery_result.total_raw))
            step("Failed sources", str(discovery_result.failed_sources or "none"))

            # Step 2: Channel Architect — audience-aware topic selection
            all_raw = []
            for src_result in discovery_result.source_results:
                if src_result.success:
                    all_raw.extend(src_result.topics)

            if all_raw:
                print(f"  [AI] Running Channel Architect on {len(all_raw)} candidates...")
                llm_flash_discovery = LLMClient(provider="deepseek", model=settings.deepseek_flash_model)
                architect = ChannelArchitectAgent(llm=llm_flash_discovery)
                opportunities = await architect.analyze(all_raw, channel, niche_cfg, top_n=5)

                if opportunities:
                    best = opportunities[0]
                    discovered_brief = best.to_brief(channel)
                    topic = discovered_brief.title

                    step("Opportunities found", str(len(opportunities)))
                    step("Selected topic", topic)
                    step("Target audience", best.audience_segment[:70])
                    step("Pain point", best.pain_point[:70])
                    step("Content angle", best.content_angle[:70])
                    step("Score", f"{best.total_score}/100 (demand={best.demand_score} fit={best.audience_fit} opp={best.opportunity})")

                    # Show runner-up topics
                    if len(opportunities) > 1:
                        print(f"\n  --- Top topics discovered ---")
                        for i, opp in enumerate(opportunities[:5], 1):
                            print(f"  #{i} [{opp.total_score}] {opp.title[:70]}")
                            print(f"       Audience: {opp.audience_segment[:60]}")
                else:
                    topic = f"5 {channel.niche.value.title()} Mistakes That Cost You Thousands"
                    print(f"  [WARN] Channel Architect found no suitable topics -- fallback: {topic}")
            else:
                topic = f"5 {channel.niche.value.title()} Mistakes That Cost You Thousands"
                print(f"  [WARN] No raw topics from scanners -- fallback: {topic}")

        except Exception as exc:
            topic = f"5 {channel.niche.value.title()} Mistakes That Cost You Thousands"
            print(f"  [WARN] Discovery failed ({exc}) -- fallback: {topic}")

    elapsed_discovery = time.perf_counter() - t_discovery
    step("Discovery time", f"{elapsed_discovery:.2f}s")
    print(f"  Topic: {topic}")

    if phase_only == 1:
        banner("Phase 1 Complete — stopping (--phase-only 1)")
        return

    # --- Phase 2: Script Generation -----------------------------------------
    banner(f"Phase 2 - Script Generation ({channel.name})")
    print(f"  Niche config: {niche_cfg.insider_angle}")
    for ex in niche_cfg.hook_examples[:2]:
        print(f"  Hook ex: {ex[:80]}")

    llm_claude = LLMClient(provider="anthropic")
    llm_pro    = LLMClient(provider="deepseek", model=settings.deepseek_pro_model)
    llm_flash  = LLMClient(provider="deepseek", model=settings.deepseek_flash_model)

    writer     = WriterAgent(llm=llm_pro)
    critic     = CriticAgent(llm=llm_pro)
    thinker          = ThinkingAgent(llm=llm_flash)
    compliance       = ComplianceChecker(llm=llm_flash)
    evolution        = EvolutionAgent(llm=llm_claude)
    visual_director  = VisualDirectorAgent(llm=llm_flash)  # DeepSeek Flash — cheap visual task
    budget           = BudgetManager(daily_budget_usd=settings.daily_llm_budget_usd)

    config = DebateConfig(
        max_rounds=7,
        convergence_delta=3,
        approval_threshold=70,
        run_tournament=True,
        run_evolution=True,
    )

    orchestrator = DebateOrchestrator(
        writer=writer,
        critic=critic,
        thinker=thinker,
        compliance=compliance,
        budget=budget,
        config=config,
        evolution=evolution,
        visual_director=visual_director,
    )

    brief = discovered_brief or TopicBrief(
        title=topic,
        niche=channel.niche,
        market=channel.market,
        source=TopicSource.MANUAL,
        angle="pain_hook",
        target_duration_min=channel.target_duration_min,
        brand_voice=channel.brand_voice,
        channel_id=channel.channel_id,
        sub_niche=channel.sub_niche,
        key_points=[
            niche_cfg.hook_examples[0][:80] if niche_cfg.hook_examples else "",
            f"Key insight from {niche_cfg.proof_sources[0]}",
            f"Insider angle: {niche_cfg.insider_angle}",
        ],
        source_urls=[],
    )

    t0 = time.perf_counter()
    results = await orchestrator.run(brief, num_variants=2, channel=channel)
    elapsed = time.perf_counter() - t0

    best = max(results, key=lambda r: (r.approved, r.final_score)) if results else None
    total_cost_all = sum(r.total_cost_usd for r in results)
    if best:
        step("Variants produced", str(len(results)))
        step("Best score", f"{best.final_score}/100")
        step("Approved", str(best.approved))
        step("Rounds", str(len(best.rounds)))
        step("Total cost", f"${total_cost_all:.4f}")
        draft = best.final_draft
        preview = (draft.hook or str(draft.segments)[:100])[:120].replace("\n", " ")
        step("Script preview", preview + "...")
        step("Time", f"{elapsed:.2f}s")
    else:
        print("  [FAIL] No variants produced")
        return

    if not best.approved:
        print("\n  [WARN] No variant passed approval -- pipeline continues in dry_run mode.")

    draft = best.final_draft
    script_text = draft.hook + "\n\n" + "\n".join(
        f"{seg.heading}\n{seg.content}" if hasattr(seg, "content") else str(seg)
        for seg in (draft.segments or [])
    ) + "\n\n" + draft.outro

    # Save scripts per channel/topic — subfolder per topic prevents collision
    import re as _re
    topic_slug = _re.sub(r"[^\w]+", "_", topic.lower()).strip("_")[:50]
    scripts_dir = Path(__file__).parent / "output" / "scripts" / channel.channel_id / topic_slug
    scripts_dir.mkdir(parents=True, exist_ok=True)
    for r in results:
        d = r.final_draft
        txt = d.hook + "\n\n"
        for seg in (d.segments or []):
            txt += f"[{seg.heading}]\n{seg.content}\n\n"
        txt += d.outro
        fname = scripts_dir / f"variant_{r.variant_id}_score{r.final_score}.txt"
        fname.write_text(txt, encoding="utf-8")
        step(f"Saved variant {r.variant_id}", str(fname))

    # --- Phase 4: Media Pipeline --------------------------------------------
    banner(f"Phase 4 - Media Pipeline ({channel.visual_style} style)")

    brand = BrandConfig(
        channel_id=channel.channel_id,
        voice_profile=channel.voice_profile,
        use_video_gen=channel.use_video_gen,
        image_gen_mode=channel.image_gen_mode,
        target_duration_min=channel.target_duration_min,
    )

    scene_prompts = [
        f"{niche_cfg.broll_style}, dramatic lighting",
        f"Close-up visual related to: {topic[:50]}",
        f"Data visualization, {niche_cfg.chart_palette} color scheme",
        "Text overlay: key insight on dark background",
        "Resolution and call-to-action visual",
    ]

    output_dir = str(Path(__file__).parent / "output" / channel.channel_id / "test_video")
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    media = MediaPipelineOrchestrator()

    t1 = time.perf_counter()
    state, render_result, fingerprint = await media.run(
        video_id="dry_run_001",
        channel_id=channel.channel_id,
        script_text=script_text,
        scene_prompts=scene_prompts,
        brand=brand,
        output_dir=output_dir,
    )
    elapsed = time.perf_counter() - t1

    step("TTS", state.tts.value)
    step("Images", state.images.value)
    step("Music", state.music.value)
    step("Subtitle", state.subtitle.value)
    step("Thumbnail", state.thumbnail.value)
    step("Render", state.render.value)
    step("Fingerprint", state.fingerprint.value)
    step("All done", str(state.all_done))
    if render_result:
        out = getattr(render_result, "output_path", None) or "dry_run_output.mp4"
        step("Output path", str(out))
    step("Time", f"{elapsed:.2f}s")

    # --- Phase 5: Upload Pipeline -------------------------------------------
    banner(f"Phase 5 - Upload Pipeline ({channel.channel_id})")

    from omnicast.upload.compliance import ComplianceChecker as UploadCompliance
    from omnicast.upload.scheduler import UploadScheduler
    from omnicast.upload.youtube_api import YouTubeUploader
    from omnicast.upload.oauth import OAuth2Manager

    compliance_checker = UploadCompliance()
    scheduler = UploadScheduler()
    oauth = OAuth2Manager(token_dir=str(Path(output_dir) / "tokens"))
    uploader = YouTubeUploader(oauth_manager=oauth)

    upload_orch = UploadPipelineOrchestrator(
        compliance=compliance_checker,
        scheduler=scheduler,
        uploader=uploader,
    )

    metadata = UploadMetadata(
        title=topic,
        description=(
            f"{topic}\n\n"
            f"Channel: {channel.name}\n"
            "[AI] This content was created with AI assistance.\n\n"
            "Timestamps:\n0:00 Intro\n1:30 Point 1\n..."
        ),
        tags=([channel.niche.value] + ([channel.sub_niche] if channel.sub_niche else []) + channel.trends_keywords[:5]),
        category_id="22",
        privacy_status="private",
    )

    t2 = time.perf_counter()
    upload_state, upload_result = await upload_orch.run(
        video_id="dry_run_001",
        channel_id=channel.channel_id,
        channel_type=channel.channel_type,
        video_path=str(Path(output_dir) / "final.mp4"),
        metadata=metadata,
        thumbnail_paths=[str(Path(output_dir) / "thumb_A.jpg")],
        market=channel.market.value,
    )
    elapsed = time.perf_counter() - t2

    step("Compliance", upload_state.compliance.value)
    step("Scheduling", upload_state.scheduling.value)
    step("Upload", upload_state.upload.value)
    step("Thumbnail", upload_state.thumbnail.value)
    if upload_result:
        step("YouTube ID", upload_result.youtube_video_id or "dry_run_id")
        step("URL", upload_result.url or "https://youtu.be/dry_run")
    step("Time", f"{elapsed:.2f}s")

    # --- Summary ------------------------------------------------------------
    banner("Pipeline Complete [DONE]")
    print(f"  Channel: {channel.channel_id} -- {channel.name}")
    print(f"  Niche:   {channel.niche.value}" + (f".{channel.sub_niche}" if channel.sub_niche else ""))
    print(f"  Topic:   {topic}")
    print(f"  Script:  {best.final_score}/100 score, {len(best.rounds)} debate rounds")
    print(f"  Style:   {channel.visual_style} | SFX: {niche_cfg.sfx_primary}")
    print(f"  Media:   {'[OK]' if state.all_done else '[FAIL]'} all phases complete")
    if upload_result:
        print(f"  Upload:  {upload_result.youtube_video_id or 'dry_run_id'} -> {upload_result.url or 'dry_run_url'}")
    print(f"\n  Mode: DRY RUN - no real API calls made")
    print(f"  Set OMNICAST_MODE=staging + API keys for real LLM\n")


async def discover_niches() -> None:
    """Broad niche discovery: scan YouTube → cluster → rank → display for user selection."""
    settings = get_settings()

    if not settings.youtube_api_key:
        print("  [ERROR] YOUTUBE_API_KEY not set in .env")
        return

    banner("OmniCast — Niche Discovery")
    print("  Scanning YouTube broadly across 20+ category seeds...")
    print("  This takes ~60-90s (API calls + LLM clustering)\n")

    # Step 1: Broad YouTube scan
    scanner = NicheScanner(api_key=settings.youtube_api_key)
    t0 = time.perf_counter()
    channels = await scanner.scan()
    scan_time = time.perf_counter() - t0

    print(f"  [OK] Channels sampled: {len(channels)}")
    print(f"  [OK] Scan time: {scan_time:.1f}s")

    if not channels:
        print("  [ERROR] No channels found. Check YouTube API key / quota.")
        return

    # Step 2: LLM niche clustering
    print(f"\n  [AI] Clustering {len(channels)} channels into niches...")
    # DeepSeek V4 Flash (cheap). Bump max_tokens so reasoning overhead doesn't starve JSON output.
    llm = LLMClient(provider="deepseek", model=settings.deepseek_flash_model)
    agent = NicheDiscovererAgent(llm=llm)

    t1 = time.perf_counter()
    niches = await agent.discover(channels, top_n=10)
    llm_time = time.perf_counter() - t1

    print(f"  [OK] LLM time: {llm_time:.1f}s")

    if not niches:
        print("  [ERROR] Niche discovery returned no results.")
        return

    # Step 3: Display ranked results
    # Fix Windows cp1252 encoding — strip non-ASCII chars in display
    import io
    safe_stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace') if hasattr(sys.stdout, 'buffer') else sys.stdout

    banner(f"Top {len(niches)} Niches Found")
    for i, niche in enumerate(niches, 1):
        text = niche.display(i)
        try:
            print(text)
        except UnicodeEncodeError:
            print(text.encode('ascii', errors='replace').decode('ascii'))
        print()

    print("=" * 60)
    print(f"  Total time: {scan_time + llm_time:.1f}s")
    print(f"\n  Pick a niche → create channel JSON in channels/")
    print(f"  Then run: python run_pipeline.py --channel <channel_id> --phase-only 1")


def main() -> None:
    parser = argparse.ArgumentParser(description="OmniCast Engine -- Channel-Driven Pipeline")
    parser.add_argument(
        "--channel",
        default=None,
        help="Channel ID (e.g. fin_retirement_us, health_nutrition_us, myth_greek_us)",
    )
    parser.add_argument(
        "--topic",
        default=None,
        help="Manual topic override (skip discovery)",
    )
    parser.add_argument(
        "--phase-only",
        type=int,
        default=None,
        metavar="N",
        help="Stop after phase N (e.g. --phase-only 1 runs discovery only)",
    )
    parser.add_argument(
        "--discover-niches",
        action="store_true",
        help="Broad niche discovery: scan YouTube → cluster → rank opportunities",
    )
    args = parser.parse_args()

    if args.discover_niches:
        asyncio.run(discover_niches())
    else:
        asyncio.run(run_pipeline(args.channel, args.topic, phase_only=args.phase_only))


if __name__ == "__main__":
    main()
