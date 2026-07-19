"""
OmniCast Writer Benchmark — Multi-Model Comparison
===================================================
Runs all available LLMs in parallel on the SAME topic + angle.
Scores each script with DeepSeek Critic. Reports cost, time, score.

Usage:
    python benchmark_writers.py
    python benchmark_writers.py --topic "Warren Buffett passive investing paradox"
    python benchmark_writers.py --angle contrarian

Optional env vars (add to .env to test more models):
    GEMINI_API_KEY     -> Gemini 2.0 Flash
    OPENAI_API_KEY     -> GPT-4o-mini
    GROQ_API_KEY       -> Llama 3.3 70B via Groq
    OPENROUTER_API_KEY -> Multiple models via OpenRouter
"""

from __future__ import annotations

import asyncio
import argparse
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://omnicast:dev@localhost:5432/omnicast")
os.environ.setdefault("RABBITMQ_URL", "amqp://omnicast:dev@localhost:5672/")

# Load .env so API keys are visible via os.environ
_env_file = Path(__file__).parent / ".env"
if _env_file.exists():
    for _line in _env_file.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _, _v = _line.partition("=")
            _k = _k.strip()
            _v = _v.strip().split("#")[0].strip()  # strip inline comments
            if _k and _v and _k not in os.environ:
                os.environ[_k] = _v

sys.path.insert(0, str(Path(__file__).parent / "src"))

import structlog
structlog.configure(processors=[structlog.dev.ConsoleRenderer(colors=False)])

from omnicast.config.settings import get_settings
from omnicast.agents.writer import WriterAgent, WRITER_SYSTEM
from omnicast.agents.critic import CriticAgent
from omnicast.llm.client import LLMClient
from omnicast.llm.cost import CostCalculator, MODEL_PRICING
from omnicast.llm import LLMResponse
from omnicast.models.script import TopicBrief, ScriptDraft
from omnicast.models.enums import Niche, Market, TopicSource
from omnicast.shared.errors import AgentError

settings = get_settings()


# ─── Model configs ────────────────────────────────────────────────────────────

@dataclass
class ModelConfig:
    label: str           # display name
    model_id: str        # API model string
    provider: str        # "anthropic" | "deepseek" | "openai_compat"
    api_key_env: str     # env var holding key
    base_url: str = ""   # empty = provider default


MODELS: list[ModelConfig] = [
    # === Always available ===
    ModelConfig(
        label="Claude Sonnet 4.6 (baseline)",
        model_id="claude-sonnet-4-6",
        provider="anthropic",
        api_key_env="CLAUDE_API_KEY",
    ),
    ModelConfig(
        label="DeepSeek V4 Pro",
        model_id="deepseek-v4-pro",
        provider="deepseek",
        api_key_env="DEEPSEEK_API_KEY",
    ),
    ModelConfig(
        label="DeepSeek V4 Flash",
        model_id="deepseek-v4-flash",
        provider="deepseek",
        api_key_env="DEEPSEEK_API_KEY",
    ),
    # === Optional: Gemini ===
    ModelConfig(
        label="Gemini 2.0 Flash",
        model_id="gemini-2.0-flash",
        provider="openai_compat",
        api_key_env="GEMINI_API_KEY",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
    ),
    # === Optional: OpenAI ===
    ModelConfig(
        label="GPT-4o-mini",
        model_id="gpt-4o-mini",
        provider="openai_compat",
        api_key_env="OPENAI_API_KEY",
        base_url="https://api.openai.com/v1",
    ),
    # === Optional: Groq (Llama) ===
    ModelConfig(
        label="Llama 3.3 70B (Groq)",
        model_id="llama-3.3-70b-versatile",
        provider="openai_compat",
        api_key_env="GROQ_API_KEY",
        base_url="https://api.groq.com/openai/v1",
    ),
    # === Optional: OpenRouter ===
    ModelConfig(
        label="Llama 3.3 70B (OpenRouter)",
        model_id="meta-llama/llama-3.3-70b-instruct",
        provider="openai_compat",
        api_key_env="OPENROUTER_API_KEY",
        base_url="https://openrouter.ai/api/v1",
    ),
]


# ─── OpenAI-compatible client ─────────────────────────────────────────────────

async def call_openai_compat(
    *,
    model_id: str,
    api_key: str,
    base_url: str,
    system: str,
    user_message: str,
    max_tokens: int = 4000,
    temperature: float = 0.7,
) -> tuple[str, int, int, float]:
    """Call any OpenAI-compatible API. Returns (content, in_tokens, out_tokens, cost_usd)."""
    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=api_key, base_url=base_url)
    resp = await client.chat.completions.create(
        model=model_id,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user_message},
        ],
        max_tokens=max_tokens,
        temperature=temperature,
    )
    content = resp.choices[0].message.content or ""
    in_tok = resp.usage.prompt_tokens if resp.usage else 0
    out_tok = resp.usage.completion_tokens if resp.usage else 0

    # Cost calculation
    pricing = MODEL_PRICING.get(model_id, (0.0, 0.0, 0.0, 0.0))
    cost = (in_tok * pricing[0] + out_tok * pricing[1]) / 1_000_000

    return content, in_tok, out_tok, cost


# ─── Benchmark result ─────────────────────────────────────────────────────────

@dataclass
class BenchmarkResult:
    label: str
    model_id: str
    script: ScriptDraft | None = None
    score: int = 0
    approved: bool = False
    cost_usd: float = 0.0
    elapsed_s: float = 0.0
    error: str = ""
    hook_preview: str = ""
    segment_count: int = 0
    word_count: int = 0
    has_open_loop: bool = False
    has_sfx: bool = False


# ─── Run one model ────────────────────────────────────────────────────────────

async def run_one_model(
    cfg: ModelConfig,
    brief: TopicBrief,
    angle: str,
    critic: CriticAgent,
    output_dir: Path,
) -> BenchmarkResult:
    result = BenchmarkResult(label=cfg.label, model_id=cfg.model_id)
    api_key = os.environ.get(cfg.api_key_env, "")
    if not api_key:
        result.error = f"No API key ({cfg.api_key_env})"
        return result

    t0 = time.perf_counter()
    try:
        # ── Generate script ──────────────────────────────────────────────────
        if cfg.provider in ("anthropic", "deepseek"):
            llm = LLMClient(
                api_key=api_key,
                model=cfg.model_id,
                provider=cfg.provider,
            )
            writer = WriterAgent(llm=llm)
            drafts = await writer.execute(brief, num_variants=1)
            draft = drafts[0]
            cost = llm.total_cost

        else:  # openai_compat
            # Build the same prompt the WriterAgent would use
            angle_instructions = {
                "pain_hook": (
                    "Open with the EXACT dollar amount or percentage the viewer is losing RIGHT NOW. "
                    "Make them feel the pain in the first sentence."
                ),
                "data_driven": (
                    "Open with a counterintuitive statistic. Lead with data. "
                    "Example: '93% of active fund managers underperform the index.'"
                ),
                "contrarian": (
                    "Open by challenging the #1 piece of conventional wisdom on this topic. "
                    "Make the viewer feel like everyone else has been lying to them."
                ),
            }
            angle_instr = angle_instructions.get(angle, angle_instructions["contrarian"])
            user_prompt = f"""Write a production-ready YouTube script optimized for 70%+ audience retention.

TOPIC: {brief.title}
NICHE: {brief.niche.value} | MARKET: {brief.market.value}
TARGET LENGTH: {brief.target_duration_min} minutes (~{brief.target_duration_min * 150} spoken words)

ANGLE: {angle_instr}

KEY POINTS:
{chr(10).join(f"- {p}" for p in brief.key_points)}

REQUIRED STRUCTURE:

HOOK:
NARRATION: [H — Pain-first with specific number. No "imagine" or "picture this".]
[VISUAL: TEXT POPUP — number fills screen]
[SFX: cash-register or alarm]
NARRATION: [I — One sentence: what this video solves]
NARRATION: [P — One credible data point as proof]
[VISUAL: show proof source]

SEGMENT 1: [Curiosity-gap heading]
NARRATION: [40-60 spoken words]
[VISUAL: describe exactly]
[SFX: if key number]
[PATTERN INTERRUPT: zoom / question / stat]
NARRATION: [continues]
[OPEN LOOP: "But X isn't the worst part. In mistake #N I'll reveal Y. For now..."]

SEGMENT 2: [Heading]
[same format]

SEGMENT 3: [Heading]
[MID-VIDEO LIKE CTA: framed as benefiting viewer's community]

SEGMENT 4: [Heading]
[MID-ROLL VIDEO CTA: natural pivot to related video]

SEGMENT 5: [Heading]
[close all open loops]

OUTRO:
NARRATION: [Specific comment question]
NARRATION: [Subscribe hook tied to THIS topic]
NARRATION: [Next video tease]
"""
            content, in_tok, out_tok, cost = await call_openai_compat(
                model_id=cfg.model_id,
                api_key=api_key,
                base_url=cfg.base_url,
                system=WRITER_SYSTEM,
                user_message=user_prompt,
                max_tokens=4000,
            )
            # Parse using WriterAgent parser
            dummy_llm = LLMClient(provider="anthropic", api_key=api_key)
            tmp_writer = WriterAgent(llm=dummy_llm)
            draft = tmp_writer._parse_draft(content, "X", brief.title)
            result.cost_usd = cost

        result.elapsed_s = time.perf_counter() - t0

        # ── Detect quality markers in raw output ─────────────────────────────
        raw_text = draft.raw_content or (draft.hook + " ".join(s.content for s in draft.segments) + draft.outro)
        result.has_open_loop = "isn't the worst" in raw_text.lower() or "open loop" in raw_text.lower() or "mistake #" in raw_text.lower()
        result.has_sfx = "[sfx:" in raw_text.lower()

        # ── Score with Critic ────────────────────────────────────────────────
        t_critic = time.perf_counter()
        try:
            feedback = await critic.execute(draft, brief)
            result.score = feedback.total_score
            result.approved = feedback.approved
        except Exception as e:
            result.score = -1
            result.error = f"Critic failed: {e}"

        # ── Populate result ──────────────────────────────────────────────────
        result.script = draft
        result.hook_preview = (draft.hook or "")[:120].replace("\n", " ")
        result.segment_count = len(draft.segments)
        result.word_count = draft.word_count
        if cfg.provider in ("anthropic", "deepseek"):
            result.cost_usd = cost

        # Save script to file
        output_dir.mkdir(parents=True, exist_ok=True)
        safe_label = cfg.label.replace(" ", "_").replace("(", "").replace(")", "").replace(".", "")

        # Save narration-only (for review)
        fname = output_dir / f"benchmark_{safe_label}.txt"
        txt = draft.hook + "\n\n"
        for seg in draft.segments:
            txt += f"[{seg.heading}]\n{seg.content}\n\n"
        txt += draft.outro
        fname.write_text(txt, encoding="utf-8")

        # Save full production script with [VISUAL:]/[SFX:] tags intact
        raw_fname = output_dir / f"benchmark_{safe_label}_production.txt"
        raw_content = draft.raw_content or txt
        raw_fname.write_text(raw_content, encoding="utf-8")

        # Save visual cue summary
        cue_fname = output_dir / f"benchmark_{safe_label}_cues.txt"
        cue_lines: list[str] = []
        all_segs = (
            [("HOOK", draft.hook_raw)]
            + [(f"SEG {s.index}: {s.heading}", s.raw_content) for s in draft.segments]
            + [("OUTRO", draft.outro_raw)]
        )
        for label, block in all_segs:
            cues = WriterAgent._parse_visual_cues(block)
            if cues:
                cue_lines.append(f"\n── {label} ({len(cues)} cues) ──")
                for c in cues:
                    cue_lines.append(f"  [{c.type.value}] {c.raw[:80]}")
        cue_fname.write_text("\n".join(cue_lines), encoding="utf-8")

    except Exception as exc:
        result.elapsed_s = time.perf_counter() - t0
        result.error = str(exc)[:200]

    return result


# ─── Main ─────────────────────────────────────────────────────────────────────

async def run_benchmark(topic: str, angle: str) -> None:
    brief = TopicBrief(
        title=topic,
        niche=Niche.FINANCE,
        market=Market.US,
        source=TopicSource.MANUAL,
        angle=angle,
        target_duration_min=10,
        key_points=[
            "Buffett recommends index funds publicly",
            "Berkshire internally manages $370B active portfolio",
            "His will puts 90% in S&P 500 for wife",
            "Active vs passive contradiction",
        ],
        source_urls=[],
    )

    # Critic uses DeepSeek V4 Pro (same as production pipeline)
    critic_llm = LLMClient(
        provider="deepseek",
        model=settings.deepseek_pro_model,
        api_key=settings.deepseek_api_key,
    )
    critic = CriticAgent(llm=critic_llm)

    output_dir = Path(__file__).parent / "output" / "benchmark"

    print(f"\n{'='*70}")
    print(f"  OmniCast Writer Benchmark")
    print(f"  Topic:  {topic}")
    print(f"  Angle:  {angle}")
    print(f"  Models: {len([m for m in MODELS if os.environ.get(m.api_key_env)])}")
    print(f"{'='*70}\n")

    # Check which models have keys
    available = [m for m in MODELS if os.environ.get(m.api_key_env)]
    skipped = [m for m in MODELS if not os.environ.get(m.api_key_env)]

    if skipped:
        print("Skipping (no API key):")
        for m in skipped:
            print(f"  - {m.label} ({m.api_key_env})")
        print()

    print(f"Running {len(available)} models in parallel...\n")

    # Run all in parallel
    tasks = [
        run_one_model(cfg, brief, angle, critic, output_dir)
        for cfg in available
    ]
    results: list[BenchmarkResult] = await asyncio.gather(*tasks)

    # Sort by score descending
    results.sort(key=lambda r: r.score, reverse=True)

    # ── Print table ───────────────────────────────────────────────────────────
    print(f"\n{'='*70}")
    print(f"  RESULTS — Ranked by Critic Score")
    print(f"{'='*70}")
    print(f"{'Rank':<5} {'Model':<35} {'Score':>6} {'Cost':>8} {'Time':>7} {'Segs':>5} {'Words':>6}")
    print("-" * 70)

    for i, r in enumerate(results, 1):
        if r.error and r.score == 0:
            print(f"  {i:<3}  {r.label:<35} {'ERROR':>6}  {'':>8}  {'':>7}  {'':>5}  {'':>6}")
            print(f"       Error: {r.error}")
            continue
        approved_mark = "OK" if r.approved else " "
        print(
            f"  {i:<3}  {r.label:<35} {r.score:>5}{approved_mark}  "
            f"${r.cost_usd:>7.4f}  {r.elapsed_s:>6.1f}s  "
            f"{r.segment_count:>4}  {r.word_count:>6}"
        )
        extras = []
        if r.has_open_loop:
            extras.append("open-loopOK")
        if r.has_sfx:
            extras.append("SFXOK")
        if extras:
            print(f"       [{', '.join(extras)}]")
        print(f"       Hook: {r.hook_preview}")
        print()

    # ── Cost comparison table ─────────────────────────────────────────────────
    print(f"\n{'='*70}")
    print(f"  COST COMPARISON (per script generation)")
    print(f"{'='*70}")
    sonnet_cost = next((r.cost_usd for r in results if "Sonnet" in r.label), 0.0)
    for r in results:
        if r.error and r.score == 0:
            continue
        if sonnet_cost > 0:
            ratio = r.cost_usd / sonnet_cost if r.cost_usd > 0 else 0
            savings = (1 - ratio) * 100
            savings_str = f"  {savings:+.0f}% vs Sonnet" if abs(savings) > 1 else "  (baseline)"
        else:
            savings_str = ""
        print(f"  {r.label:<35}  ${r.cost_usd:.4f}{savings_str}")

    # Save markdown report
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / "benchmark_report.md"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(f"# Writer Benchmark — {topic}\n\n")
        f.write(f"**Angle:** {angle}  |  **Date:** {time.strftime('%Y-%m-%d %H:%M')}\n\n")
        f.write("| Rank | Model | Score | Approved | Cost | Time | Segments | Words | Open Loop | SFX |\n")
        f.write("|------|-------|-------|----------|------|------|----------|-------|-----------|-----|\n")
        for i, r in enumerate(results, 1):
            f.write(
                f"| {i} | {r.label} | {r.score} | {'OK' if r.approved else 'FAIL'} | "
                f"${r.cost_usd:.4f} | {r.elapsed_s:.1f}s | {r.segment_count} | "
                f"{r.word_count} | {'OK' if r.has_open_loop else 'FAIL'} | {'OK' if r.has_sfx else 'FAIL'} |\n"
            )
        f.write("\n## Hook Previews\n\n")
        for r in results:
            if r.hook_preview:
                f.write(f"### {r.label}\n{r.hook_preview}...\n\n")

    print(f"\n  Report saved: {report_path}")
    print(f"  Scripts saved: {output_dir}/benchmark_*.txt\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="OmniCast Writer Benchmark")
    parser.add_argument(
        "--topic",
        default="warren buffett passive investing paradox",
        help="Topic to benchmark",
    )
    parser.add_argument(
        "--angle",
        default="contrarian",
        choices=["pain_hook", "data_driven", "contrarian"],
        help="Writing angle",
    )
    args = parser.parse_args()
    asyncio.run(run_benchmark(args.topic, args.angle))


if __name__ == "__main__":
    main()
