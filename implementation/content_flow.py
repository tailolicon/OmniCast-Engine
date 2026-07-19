"""
OmniCast Engine — Flow B: Content Pipeline
==========================================
Standalone CLI for running the full content pipeline for an existing channel.

Usage:
    python content_flow.py --channel fin_retirement_us              # full pipeline
    python content_flow.py --channel fin_retirement_us --phase 1    # topic discovery only
    python content_flow.py --channel fin_retirement_us --phase 2    # topic + script
    python content_flow.py --channel fin_retirement_us --topic "5 Retirement Mistakes"

Phases:
    1 — Topic Discovery  (YouTube scan → ChannelArchitect → best topic)
    2 — Script Generation (Writer ↔ Critic debate)
    3 — Media Pipeline   (TTS → render → thumbnail)
    4 — Upload Pipeline  (compliance → YouTube)

Output:
    output/runs/{channel_id}/{timestamp}/
        run_summary.json
        phase1_discovery.json
        phase2_scripts/variant_*.json
        phase2_scripts/debate_log.json
        phase3_media.json
        phase4_upload.json
        best_script.txt
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

import structlog

structlog.configure(processors=[structlog.dev.ConsoleRenderer(colors=True)])

ROOT = Path(__file__).parent
CHANNELS_DIR = ROOT / "channels"

import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://omnicast:dev_password@localhost:5432/omnicast")
os.environ.setdefault("RABBITMQ_URL", "amqp://omnicast:dev_password@localhost:5672/")


async def _filter_duplicate_topics(opps: list, channel_id: str, llm) -> list:
    """Remove topics too similar to existing scripts in vault.db.

    Two-pass: fast string match first, then LLM semantic check for remainder.
    Returns filtered list (first-non-dup first). Empty = all duplicates.
    """
    import re
    from omnicast.vault.db import list_scripts

    existing = list_scripts(channel_id=channel_id)
    if not existing:
        return opps  # no history → nothing to check

    existing_topics = [s.topic for s in existing]
    existing_angles = [getattr(s, "script_content", "")[:300] for s in existing]

    def _normalize(t: str) -> str:
        return re.sub(r"[^a-z0-9 ]", "", t.lower()).strip()

    clean = []
    skipped_exact = []
    skipped_semantic = []

    for opp in opps:
        norm_new = _normalize(opp.title)

        # Pass 1 — fast exact/substring match
        exact_dup = any(
            norm_new in _normalize(t) or _normalize(t) in norm_new
            for t in existing_topics
        )
        if exact_dup:
            skipped_exact.append(opp.title)
            continue

        # Pass 2 — LLM semantic check
        existing_list = "\n".join(
            f"- {t}" for t in existing_topics
        )
        prompt = (
            f"YouTube channel: {channel_id}\n\n"
            f"EXISTING VIDEOS (already published):\n{existing_list}\n\n"
            f"NEW TOPIC CANDIDATE:\nTitle: {opp.title}\n"
            f"Angle: {getattr(opp, 'content_angle', '')[:200]}\n\n"
            "Would producing the new topic violate YouTube's duplicate content policy? "
            "Consider: same core argument, same key data points, same audience pain point addressed.\n\n"
            'Answer ONLY with JSON: {"duplicate": true/false, "reason": "one sentence"}'
        )
        try:
            response = await llm.complete(
                system="You are a YouTube content strategy analyst. Be strict — YouTube penalizes repeated angles, not just repeated titles.",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=100,
            )
            import json as _json, re as _re
            m = _re.search(r'\{.*?\}', response.content, _re.DOTALL)
            if m:
                data = _json.loads(m.group())
                if data.get("duplicate"):
                    skipped_semantic.append((opp.title, data.get("reason", "")))
                    continue
        except Exception:
            pass  # LLM check failed → allow topic (safe default)

        clean.append(opp)

    # Report
    if skipped_exact:
        for t in skipped_exact:
            print(f"  [SKIP] Exact dup: {t[:65]}")
    if skipped_semantic:
        for t, reason in skipped_semantic:
            print(f"  [SKIP] Semantic dup: {t[:55]} — {reason[:60]}")

    return clean


def banner(title: str) -> None:
    print("\n" + "=" * 60)
    print(f"  {title}")
    print("=" * 60)


def step(name: str, value: str) -> None:
    print(f"  [OK] {name}: {value}")


def fail(name: str, msg: str) -> None:
    print(f"  [FAIL] {name}: {msg}")


# ─── Phase 1: Topic Discovery ────────────────────────────────────────────────

async def run_phase1(channel, niche_cfg, settings, run_id: str | None = None) -> tuple[str, object | None, dict]:
    """Scan YouTube competitors → ChannelArchitect → best topic.

    Returns (topic_str, TopicOpportunity | None, phase1_data_dict).
    """
    from omnicast.llm.client import LLMClient
    from omnicast.discovery.orchestrator import DiscoveryOrchestrator
    from omnicast.agents.channel_architect import ChannelArchitectAgent

    banner(f"Phase 1 — Topic Discovery ({channel.name})")

    t0 = time.perf_counter()
    topic: str = ""
    best_opp = None

    try:
        orchestrator = DiscoveryOrchestrator.for_channel(channel)
        result = await orchestrator.run()
        step("Raw topics", str(result.total_raw))

        all_raw = [
            t for src in result.source_results if src.success for t in src.topics
        ]

        source_counts = {
            src.source.value: len(src.topics)
            for src in result.source_results if src.success
        }

        if all_raw:
            print(f"  [AI] Channel Architect analyzing {len(all_raw)} candidates...")
            llm = LLMClient(provider="deepseek", model=settings.deepseek_flash_model)
            architect = ChannelArchitectAgent(llm=llm)
            opps = await architect.analyze(all_raw, channel, niche_cfg, top_n=5)

            if opps:
                if len(opps) > 1:
                    print(f"\n  --- All discovered topics ---")
                    for i, o in enumerate(opps[:5], 1):
                        print(f"  #{i} [{o.total_score}] {o.title[:65]}")

                # ── Duplicate content filter (YouTube policy protection) ──────
                print(f"\n  [AI] Checking {len(opps)} topic(s) against published scripts...")
                opps = await _filter_duplicate_topics(opps, channel.channel_id, llm)

                if opps:
                    best_opp = opps[0]
                    topic = best_opp.title
                    step("Best topic (deduped)", topic[:70])
                    step("Score", f"{best_opp.total_score}/100")
                    step("Audience", best_opp.audience_segment[:60])
                    step("Angle", best_opp.content_angle[:60])
                else:
                    topic = f"5 {channel.niche.value.title()} Strategies for 2026 — Fresh Angle"
                    print(f"  [WARN] All {len(opps)} candidates are duplicates — fallback: {topic}")
            else:
                topic = f"5 {channel.niche.value.title()} Mistakes That Cost You Thousands"
                print(f"  [WARN] No topics scored — fallback: {topic}")
        else:
            topic = f"5 {channel.niche.value.title()} Strategies for 2026"
            print(f"  [WARN] No raw topics — fallback: {topic}")

    except Exception as exc:
        topic = f"5 {channel.niche.value.title()} Mistakes That Cost You Thousands"
        print(f"  [WARN] Discovery failed ({exc}) — fallback: {topic}")
        source_counts = {}

    elapsed = time.perf_counter() - t0
    step("Time", f"{elapsed:.2f}s")

    phase1_data = {
        "topic": topic,
        "audience": best_opp.audience_segment if best_opp else "",
        "pain_point": best_opp.pain_point if best_opp else "",
        "content_angle": best_opp.content_angle if best_opp else "",
        "best_score": best_opp.total_score if best_opp else 0,
        "top_opportunities": [],
        "source_counts": source_counts,
        "elapsed_s": round(elapsed, 2),
        "cost_usd": 0.0,
    }

    # Save to run store if run_id provided
    if run_id:
        try:
            from omnicast.api.run_store import save_phase1
            save_phase1(run_id, phase1_data)
        except Exception as exc:
            print(f"  [WARN] run_store save failed: {exc}")

    return topic, best_opp, phase1_data


# ─── Phase 2: Script Generation ──────────────────────────────────────────────

async def run_phase2(channel, niche_cfg, settings, topic: str, best_opp, run_id: str | None = None) -> object | None:
    """Writer ↔ Critic debate → approved script. Returns best DebateResult or None."""
    from omnicast.llm.client import LLMClient
    from omnicast.agents.writer import WriterAgent
    from omnicast.agents.critic import CriticAgent
    from omnicast.agents.thinking import ThinkingAgent
    from omnicast.agents.compliance import ComplianceChecker
    from omnicast.agents.evolution import EvolutionAgent
    from omnicast.agents.visual_director import VisualDirectorAgent
    from omnicast.agents.orchestrator import DebateOrchestrator, DebateConfig
    from omnicast.services.budget import BudgetManager
    from omnicast.models.script import TopicBrief
    from omnicast.models.enums import TopicSource
    from omnicast.vault import db as vault_db

    banner(f"Phase 2 — Script Generation ({channel.name})")
    print(f"  Topic: {topic}")
    print(f"  Hook format: {niche_cfg.hook_format[:70]}")

    vault_path = ROOT / "output" / "vault.db"
    vault_db.init_db(vault_path)
    if vault_db.topic_has_script_product(channel.channel_id, topic, vault_path):
        raise RuntimeError(f"Topic already has a script/product: {topic}")

    llm_pro   = LLMClient(provider="deepseek", model=settings.deepseek_pro_model)
    llm_flash = LLMClient(provider="deepseek", model=settings.deepseek_flash_model)
    llm_claude = LLMClient(provider="anthropic")

    writer          = WriterAgent(llm=llm_pro)
    critic          = CriticAgent(llm=llm_pro)
    thinker         = ThinkingAgent(llm=llm_flash)
    compliance      = ComplianceChecker(llm=llm_flash)
    evolution       = EvolutionAgent(llm=llm_claude)
    visual_director = VisualDirectorAgent(llm=llm_flash)   # DeepSeek Flash — cheap visual task
    budget          = BudgetManager(daily_budget_usd=settings.daily_llm_budget_usd)

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

    # Build brief from best opportunity or manual topic
    if best_opp:
        brief = best_opp.to_brief(channel)
    else:
        brief = TopicBrief(
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
                f"Key insight from {niche_cfg.proof_sources[0]}" if niche_cfg.proof_sources else "",
                f"Insider angle: {niche_cfg.insider_angle}",
            ],
            source_urls=[],
        )

    t0 = time.perf_counter()
    results = await orchestrator.run(brief, num_variants=2, channel=channel)
    elapsed = time.perf_counter() - t0

    if not results:
        fail("Script generation", "No variants produced")
        return None

    best = max(results, key=lambda r: (r.approved, r.final_score))
    total_cost = sum(r.total_cost_usd for r in results)

    step("Variants", str(len(results)))
    step("Best score", f"{best.final_score}/100")
    step("Approved", str(best.approved))
    step("Rounds", str(len(best.rounds)))
    step("Cost", f"${total_cost:.4f}")
    step("Time", f"{elapsed:.2f}s")

    if not best.approved:
        print("  [WARN] No variant passed approval threshold (70).")

    # Save scripts to output/scripts/
    scripts_dir = ROOT / "output" / "scripts" / channel.channel_id
    scripts_dir.mkdir(parents=True, exist_ok=True)
    for r in results:
        d = r.final_draft
        txt = d.hook + "\n\n"
        for seg in (d.segments or []):
            txt += f"[{seg.heading}]\n{seg.content}\n\n"
        txt += d.outro
        fname = scripts_dir / f"variant_{r.variant_id}_score{r.final_score}.txt"
        fname.write_text(txt, encoding="utf-8")
        step(f"Saved variant {r.variant_id}", str(fname.name))

    # Save to run store
    if run_id:
        try:
            from omnicast.api.run_store import save_phase2_variant, save_phase2_debate_log, save_best_script_txt

            all_rounds = []
            for r in results:
                for rd in r.rounds:
                    all_rounds.append({
                        "variant_id": r.variant_id,
                        "round_number": rd.round_number if hasattr(rd, "round_number") else 0,
                        "score": rd.feedback.total_score if hasattr(rd, "feedback") and hasattr(rd.feedback, "total_score") else 0,
                        "feedback": rd.feedback.model_dump() if hasattr(rd, "feedback") and hasattr(rd.feedback, "model_dump") else str(rd.feedback) if hasattr(rd, "feedback") else "",
                    })
                save_phase2_variant(run_id, r.variant_id, {
                    "variant_id": r.variant_id,
                    "final_score": r.final_score,
                    "approved": r.approved,
                    "total_cost_usd": r.total_cost_usd,
                    "hook": r.final_draft.hook,
                    "outro": r.final_draft.outro,
                    "rounds": all_rounds,
                })

            save_phase2_debate_log(run_id, all_rounds)

            # Save best script as text
            d = best.final_draft
            txt = d.hook + "\n\n"
            for seg in (d.segments or []):
                txt += f"[{seg.heading}]\n{seg.content}\n\n"
            txt += d.outro
            save_best_script_txt(run_id, txt)
        except Exception as exc:
            print(f"  [WARN] run_store save failed: {exc}")

    # ── Persist best script to SQLite vault ──────────────────────────────────
    try:
        from datetime import datetime
        from omnicast.vault.db import init_db, mark_topic_used_by_title, upsert_script
        from omnicast.vault.models import ScriptRecord, ScriptStatus

        init_db(vault_path)  # no-op if tables exist

        # script_id = channel_id + run timestamp (stable, idempotent)
        ts_part = (run_id or "").split("/")[-1] if run_id else datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        script_id = f"{channel.channel_id}_{ts_part}"

        # Build full narration text for best variant
        d = best.final_draft
        best_txt = d.hook + "\n\n"
        for seg in (d.segments or []):
            best_txt += f"[{seg.heading}]\n{seg.content}\n\n"
        best_txt += d.outro

        lang = getattr(channel, "language", "en") or "en"
        now_iso = datetime.utcnow().isoformat()

        record = ScriptRecord(
            script_id=script_id,
            run_id=run_id or script_id,
            channel_id=channel.channel_id,
            language=lang,
            topic=topic,
            score=best.final_score,
            approved=best.approved,
            status=ScriptStatus.DRAFT,
            script_content=best_txt,
            cost_usd=round(sum(r.total_cost_usd for r in results), 4),
            created_at=now_iso,
            updated_at=now_iso,
        )
        upsert_script(record, vault_path)
        mark_topic_used_by_title(channel.channel_id, topic, now_iso, script_id, vault_path)
        step("Vault", f"script saved → {script_id}")
    except Exception as exc:
        print(f"  [WARN] Vault script save failed: {exc}")

    return best


# ─── Phase 3: Media Pipeline ─────────────────────────────────────────────────

async def run_phase3(channel, niche_cfg, topic: str, best_result, run_id: str | None = None) -> None:
    """TTS → image gen → music → subtitle → render → fingerprint."""
    from omnicast.media.orchestrator import MediaPipelineOrchestrator

    banner(f"Phase 3 — Media Pipeline ({channel.visual_style})")

    d = best_result.final_draft
    script_text = d.hook + "\n\n"
    for seg in (d.segments or []):
        txt_seg = getattr(seg, "content", str(seg))
        script_text += f"{getattr(seg, 'heading', '')}\n{txt_seg}\n\n"
    script_text += d.outro

    scene_prompts = [
        f"{niche_cfg.broll_style}, dramatic lighting",
        f"Close-up visual: {topic[:50]}",
        f"Data visualization, {niche_cfg.chart_palette} palette",
        "Text overlay key insight, dark background",
        "Resolution + CTA visual",
    ]

    output_dir = str(ROOT / "output" / channel.channel_id / "media")
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    media = MediaPipelineOrchestrator()
    brand = channel.to_brand_config()

    t0 = time.perf_counter()
    state, render_result, fingerprint = await media.run(
        video_id="run_001",
        channel_id=channel.channel_id,
        script_text=script_text,
        scene_prompts=scene_prompts,
        brand=brand,
        output_dir=output_dir,
    )
    elapsed = time.perf_counter() - t0

    step("TTS", state.tts.value)
    step("Images", state.images.value)
    step("Music", state.music.value)
    step("Subtitle", state.subtitle.value)
    step("Thumbnail", state.thumbnail.value)
    step("Render", state.render.value)
    step("Fingerprint", state.fingerprint.value)
    step("All done", str(state.all_done))
    step("Time", f"{elapsed:.2f}s")

    if run_id:
        try:
            from omnicast.api.run_store import save_phase3
            save_phase3(run_id, {
                "tts": state.tts.value,
                "images": state.images.value,
                "music": state.music.value,
                "render": state.render.value,
                "all_done": state.all_done,
                "elapsed_s": round(elapsed, 2),
            })
        except Exception as exc:
            print(f"  [WARN] run_store save failed: {exc}")


# ─── Phase 4: Upload Pipeline ─────────────────────────────────────────────────

async def run_phase4(channel, topic: str, run_id: str | None = None) -> None:
    """Compliance check → YouTube upload (dry run by default)."""
    from omnicast.upload.orchestrator import UploadPipelineOrchestrator
    from omnicast.upload.compliance import ComplianceChecker as UploadCompliance
    from omnicast.upload.scheduler import UploadScheduler
    from omnicast.upload.youtube_api import YouTubeUploader
    from omnicast.upload.oauth import OAuth2Manager
    from omnicast.upload.models import UploadMetadata

    banner(f"Phase 4 — Upload Pipeline ({channel.channel_id})")

    token_dir = str(ROOT / "output" / channel.channel_id / "tokens")
    oauth = OAuth2Manager(token_dir=token_dir)
    compliance = UploadCompliance()
    scheduler = UploadScheduler()
    uploader = YouTubeUploader(oauth_manager=oauth)

    orch = UploadPipelineOrchestrator(
        compliance=compliance,
        scheduler=scheduler,
        uploader=uploader,
    )

    metadata = UploadMetadata(
        title=topic,
        description=(
            f"{topic}\n\n"
            f"Channel: {channel.name}\n"
            "[AI] This content was created with AI assistance.\n\n"
            "0:00 Intro\n1:30 Main points\n..."
        ),
        tags=[channel.niche.value] + ([channel.sub_niche] if channel.sub_niche else []) + channel.trends_keywords[:5],
        category_id="22",
        privacy_status="private",
    )

    video_path = str(ROOT / "output" / channel.channel_id / "media" / "final.mp4")
    thumb_path = str(ROOT / "output" / channel.channel_id / "media" / "thumb_A.jpg")

    t0 = time.perf_counter()
    upload_state, upload_result = await orch.run(
        video_id="run_001",
        channel_id=channel.channel_id,
        channel_type=channel.channel_type,
        video_path=video_path,
        metadata=metadata,
        thumbnail_paths=[thumb_path],
        market=channel.market.value,
    )
    elapsed = time.perf_counter() - t0

    step("Compliance", upload_state.compliance.value)
    step("Scheduling", upload_state.scheduling.value)
    step("Upload", upload_state.upload.value)
    step("Thumbnail", upload_state.thumbnail.value)
    step("Time", f"{elapsed:.2f}s")

    if upload_result:
        step("YouTube ID", upload_result.youtube_video_id or "dry_run_id")
        step("URL", upload_result.url or "https://youtu.be/dry_run")

    if run_id:
        try:
            from omnicast.api.run_store import save_phase4
            save_phase4(run_id, {
                "compliance": upload_state.compliance.value,
                "upload": upload_state.upload.value,
                "youtube_video_id": upload_result.youtube_video_id if upload_result else None,
                "youtube_url": upload_result.url if upload_result else None,
                "elapsed_s": round(elapsed, 2),
            })
        except Exception as exc:
            print(f"  [WARN] run_store save failed: {exc}")


# ─── Main Runner ──────────────────────────────────────────────────────────────

async def run_content_pipeline(
    channel_id: str,
    topic_override: str | None,
    stop_after_phase: int | None,
) -> None:
    if stop_after_phase in (1, 2) or topic_override:
        from omnicast.pipeline.models import StepStatus
        from omnicast.pipeline.runner import PipelineRunner

        banner("OmniCast - Content Pipeline via PipelineRunner")
        print(f"  Channel : {channel_id}")
        runner = PipelineRunner(db_path=ROOT / "output" / "vault.db")

        if topic_override:
            discovery_outputs = {
                "topic": topic_override,
                "audience": "",
                "pain_point": "",
                "content_angle": "",
                "next_topic": "",
            }
            step("Topic", topic_override)
        else:
            discovery = await runner.run_single_step(
                "discovery",
                "omnicast.discovery",
                {"channel_id": channel_id},
                pipeline_id="cli_content_phase1",
                timeout_seconds=300,
            )
            if discovery.status != StepStatus.SUCCESS:
                fail("Discovery", discovery.error or "pipeline step failed")
                raise RuntimeError(discovery.error or "pipeline discovery failed")
            discovery_outputs = discovery.outputs
            step("Discovery", discovery_outputs.get("topic", ""))

        if stop_after_phase == 1:
            banner("Phase 1 Complete - stopped")
            return

        script = await runner.run_single_step(
            "script",
            "omnicast.script",
            {
                "channel_id": channel_id,
                "topic": discovery_outputs.get("topic", ""),
                "audience": discovery_outputs.get("audience", ""),
                "pain_point": discovery_outputs.get("pain_point", ""),
                "content_angle": discovery_outputs.get("content_angle", ""),
                "next_topic": discovery_outputs.get("next_topic", ""),
            },
            pipeline_id="cli_content_phase2",
            # 2100s timed out since the debate got heavier (revise + word-floor
            # expand per round, deepseek reasoning). 3900s gives full headroom.
            timeout_seconds=3900,
        )
        if script.status != StepStatus.SUCCESS:
            fail("Script", script.error or "pipeline step failed")
            raise RuntimeError(script.error or "pipeline script failed")
        step("Script", script.outputs.get("script_path", ""))
        if stop_after_phase == 2 or topic_override:
            banner("Phase 2 Complete - stopped")
            return

    from omnicast.config.settings import get_settings
    from omnicast.config.channel import ChannelProfileLoader
    from omnicast.config.niches import get_niche_config
    from omnicast.api.run_store import new_run, finish_run
    from omnicast.api.state import set_active_job, clear_active_job, write_pipeline_event

    settings = get_settings()

    # Load channel
    loader = ChannelProfileLoader(CHANNELS_DIR)
    try:
        channel = await loader.load(channel_id)
    except FileNotFoundError:
        print(f"  [ERROR] Channel '{channel_id}' not found in {CHANNELS_DIR}")
        print(f"  Run: python niche_flow.py --scan  to discover niches")
        print(f"  Then: python niche_flow.py --create <niche_id>  to create channel")
        sys.exit(1)

    niche_cfg = get_niche_config(channel.niche.value, channel.sub_niche)

    banner("OmniCast — Content Pipeline")
    print(f"  Channel : {channel.channel_id} — {channel.name}")
    print(f"  Niche   : {channel.niche.value}" + (f".{channel.sub_niche}" if channel.sub_niche else ""))
    print(f"  Style   : {channel.visual_style} | Voice: {channel.brand_voice[:50]}")
    if stop_after_phase:
        print(f"  Mode    : stop after phase {stop_after_phase}")

    # Create run artifact store entry
    run_id = new_run(channel_id)
    print(f"  Run ID  : {run_id}")

    set_active_job(channel_id, "discovery")
    write_pipeline_event(channel_id, "discovery", "started")

    t_total = time.perf_counter()

    try:
        # ── Phase 1: Topic Discovery ──────────────────────────────────────────
        if topic_override:
            topic = topic_override
            best_opp = None
            banner("Phase 1 — Topic (manual override)")
            step("Topic", topic)
        else:
            topic, best_opp, _ = await run_phase1(channel, niche_cfg, settings, run_id)

        write_pipeline_event(channel_id, "discovery", "completed", topic=topic)

        if stop_after_phase == 1:
            banner("Phase 1 Complete — stopped")
            finish_run(run_id, "completed")
            clear_active_job(channel_id)
            return

        # ── Phase 2: Script ───────────────────────────────────────────────────
        set_active_job(channel_id, "writing", topic)
        write_pipeline_event(channel_id, "writing", "started", topic=topic)

        best_result = await run_phase2(channel, niche_cfg, settings, topic, best_opp, run_id)
        if best_result is None:
            write_pipeline_event(channel_id, "writing", "failed", extra={"error": "no variants"})
            finish_run(run_id, "failed")
            clear_active_job(channel_id)
            return

        write_pipeline_event(
            channel_id, "writing", "completed",
            topic=topic, score=best_result.final_score,
            cost_usd=best_result.total_cost_usd,
        )

        if stop_after_phase == 2:
            banner("Phase 2 Complete — stopped")
            finish_run(run_id, "completed")
            clear_active_job(channel_id)
            return

        # ── Phase 3: Media ────────────────────────────────────────────────────
        set_active_job(channel_id, "media", topic)
        write_pipeline_event(channel_id, "media", "started", topic=topic)

        await run_phase3(channel, niche_cfg, topic, best_result, run_id)
        write_pipeline_event(channel_id, "media", "completed", topic=topic)

        if stop_after_phase == 3:
            banner("Phase 3 Complete — stopped")
            finish_run(run_id, "completed")
            clear_active_job(channel_id)
            return

        # ── Phase 4: Upload ───────────────────────────────────────────────────
        set_active_job(channel_id, "upload", topic)
        write_pipeline_event(channel_id, "upload", "started", topic=topic)

        await run_phase4(channel, topic, run_id)
        write_pipeline_event(channel_id, "upload", "completed", topic=topic)

    except Exception as exc:
        print(f"\n  [ERROR] Pipeline crashed: {exc}")
        write_pipeline_event(channel_id, "pipeline", "failed", extra={"error": str(exc)})
        finish_run(run_id, "failed")
        clear_active_job(channel_id)
        raise

    # ── Summary ───────────────────────────────────────────────────────────────
    total_elapsed = time.perf_counter() - t_total
    finish_run(run_id, "completed")
    clear_active_job(channel_id)

    banner("Pipeline Complete")
    print(f"  Channel : {channel.channel_id} — {channel.name}")
    print(f"  Topic   : {topic}")
    print(f"  Run ID  : {run_id}")
    print(f"  Total   : {total_elapsed:.1f}s")
    print(f"\n  Artifacts: output/runs/{run_id}/")
    print(f"  Mode: DRY RUN — set real API keys + OMNICAST_MODE=staging for live")


# ─── Entry Point ──────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="OmniCast Flow B — Content Pipeline"
    )
    parser.add_argument(
        "--channel",
        required=True,
        metavar="CHANNEL_ID",
        help="Channel ID (e.g. fin_retirement_us)",
    )
    parser.add_argument(
        "--topic",
        default=None,
        metavar="TITLE",
        help="Manual topic override (skips Phase 1 discovery)",
    )
    parser.add_argument(
        "--phase",
        type=int,
        default=None,
        metavar="N",
        choices=[1, 2, 3, 4],
        help="Stop after phase N (1=discovery, 2=script, 3=media, 4=upload)",
    )

    args = parser.parse_args()
    asyncio.run(run_content_pipeline(
        channel_id=args.channel,
        topic_override=args.topic,
        stop_after_phase=args.phase,
    ))


if __name__ == "__main__":
    main()
