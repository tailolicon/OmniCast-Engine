"""Built-in pipeline step implementations.

Each step is an async callable:
    async def run(inputs: dict, context: StepContext) -> dict

The returned dict becomes StepResult.outputs and is available to downstream
steps via the Jinja2 template context as ``steps.<step_id>.<key>``.

Step registry: map "omnicast.xxx" → async callable.
External plugins can register custom steps via ``register_step()``.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import sys
from pathlib import Path
from typing import Any, Protocol

import structlog

logger = structlog.get_logger()

# ── Step context ─────────────────────────────────────────────────────────────


class StepContext:
    """Runtime context injected into every step."""

    def __init__(
        self,
        execution_id: str,
        pipeline_id: str,
        inputs: dict[str, Any],
        step_outputs: dict[str, dict[str, Any]],
    ) -> None:
        self.execution_id = execution_id
        self.pipeline_id = pipeline_id
        self.inputs = inputs
        self.step_outputs = step_outputs   # {step_id: {output_key: value}}


class StepFn(Protocol):
    async def __call__(self, inputs: dict[str, Any], ctx: StepContext) -> dict[str, Any]: ...


# ── Registry ─────────────────────────────────────────────────────────────────

_REGISTRY: dict[str, StepFn] = {}


def register_step(type_id: str, fn: StepFn) -> None:
    """Register a custom step type. Call before PipelineRunner is used."""
    _REGISTRY[type_id] = fn


def get_step(type_id: str) -> StepFn:
    if type_id not in _REGISTRY:
        raise ValueError(f"Unknown pipeline step type: {type_id!r}. "
                         f"Available: {sorted(_REGISTRY)}")
    return _REGISTRY[type_id]


def _llm_client(default_provider: str, model: str | None = None,
                db_path: Path | None = None, cli_effort: str | None = None,
                role: str = ""):
    """Resolve text capability, then create the existing LLMClient as adapter.
    Delegates to the shared factory (WO-2) so every LLM call site uses one policy.

    cli_effort/role are optional and Claude-CLI-specific; omitting them preserves
    every existing caller's behaviour exactly."""
    from omnicast.capabilities.llm_factory import create_llm
    return create_llm(default_provider, model=model, db_path=db_path,
                      cli_effort=cli_effort, role=role)


def _runtime_flag(env_name: str, settings_attr: str, settings) -> bool:
    """Read a boolean switch from the environment, then from Settings.

    Both sources are needed. pydantic-settings reads implementation/.env into the
    Settings MODEL; it does not populate os.environ. Only the API-server path calls
    load_dotenv, so a CLI/step run would silently ignore a .env-only switch if this
    read os.environ alone. Env var wins so an operator can override per run — the
    same precedence LLMClient already uses for OMNICAST_CLAUDE_BACKEND.
    """
    raw = (
        os.environ.get(env_name, "")
        or str(getattr(settings, settings_attr, "") or "")
    ).strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _narrative_role_clients(
    settings,
    *,
    vault_path: Path | None = None,
    deepseek_pro=None,
    deepseek_flash=None,
    client_factory=None,
) -> dict:
    """Resolve one immutable client per unit_first role, once, for this run.

    Nothing global is mutated: every role is a value passed into the pipeline, so
    two channels in one process cannot disturb each other, and non-unit flows keep
    their own clients untouched.

    Two modes:

    * ``claude_only`` (OMNICAST_NARRATIVE_CLAUDE_ONLY=1) — the temporary mode for
      an exhausted DeepSeek quota. EVERY role is a Claude CLI client and no
      DeepSeek client is passed to the pipeline at all, so no DeepSeek call can
      happen: not a first primary attempt, not a health probe. Fallbacks are
      deliberately None — within one Anthropic subscription a model swap is not a
      fallback (one quota, one health domain), and offering one would only buy a
      pointless retry against the same dead domain. If Claude itself dies the run
      aborts fail-closed, which is correct: there is nothing left to judge with.
    * default — unchanged DeepSeek-first routing with Sonnet fallbacks, so
      restoring DeepSeek needs no code change.
    """
    make = client_factory or _llm_client
    claude_only = _runtime_flag(
        "OMNICAST_NARRATIVE_CLAUDE_ONLY", "omnicast_narrative_claude_only", settings
    )
    max_quality = _runtime_flag(
        "OMNICAST_NARRATIVE_MAX_QUALITY", "omnicast_narrative_max_quality", settings
    )

    def _opt(env_name: str, default: str) -> str:
        return (os.environ.get(env_name, "") or default).strip()

    # Live 2026-07-17 16:03: a Sonnet/medium planner produced premises the auditor
    # correctly killed on TRADE reasoning — a locksmith trapped by a door he had
    # just keyed, an apprentice returning alone to a stalker for a third night,
    # a non-emergency call with a man pressed to the glass. Those are judgement
    # failures, not format failures, and the plan is the cheapest place in the run
    # to buy judgement: one call decides whether three writer calls are worth
    # making. Under max-quality the planner is Opus.
    planner_model = _opt(
        "OMNICAST_NARRATIVE_PLANNER_MODEL",
        "claude-opus-5" if max_quality else "claude-sonnet-5",
    )
    writer_model = _opt(
        "OMNICAST_NARRATIVE_WRITER_MODEL",
        "claude-opus-5" if max_quality
        else (getattr(settings, "claude_model", "") or "claude-sonnet-5"),
    )
    judge_model = _opt("OMNICAST_NARRATIVE_JUDGE_FALLBACK_MODEL", "claude-sonnet-5")
    challenger_model = _opt("OMNICAST_NARRATIVE_CHALLENGER_MODEL", "claude-opus-5")
    annotation_model = _opt("OMNICAST_NARRATIVE_ANNOTATION_MODEL", "claude-sonnet-5")
    # EFFORT IS A PROPERTY OF THE ROLE, NOT THE MODEL. Live 2026-07-17 14:32: a
    # Sonnet *planner* call ran 7 minutes and 11,924 output tokens and a Sonnet
    # *re-audit* ran 6 minutes, because the CLI was invoked with no --effort and
    # every stage inherited its default reasoning depth. Planning and judging are
    # structured, bounded jobs; prose is where depth pays.
    # "high", not "max": the plan-stage failures were reasoning-quality failures,
    # which the model change addresses, and there is no measurement showing max
    # buys more plan judgement than high. There IS a measurement of what plan-stage
    # depth costs — the 14:32 run spent 31 minutes there and never reached the
    # writer. Depth is priced in wall clock at exactly the stage that has already
    # starved this pipeline of prose four times, so it is not spent on a guess.
    planner_effort = _opt(
        "OMNICAST_NARRATIVE_PLANNER_EFFORT", "high" if max_quality else "medium"
    )
    judge_effort = _opt("OMNICAST_NARRATIVE_JUDGE_EFFORT", "medium")
    writer_effort = _opt(
        "OMNICAST_NARRATIVE_WRITER_EFFORT", "max" if max_quality else "high"
    )
    challenger_effort = _opt(
        "OMNICAST_NARRATIVE_CHALLENGER_EFFORT", "max" if max_quality else "high"
    )

    def claude(model: str, effort: str, role: str):
        return make("anthropic", model=model, db_path=vault_path,
                    cli_effort=effort, role=role)

    planner = claude(planner_model, planner_effort, "planner")
    writer = claude(writer_model, writer_effort, "writer")
    # FOREIGN-PROVIDER ADVERSARY (external review 2026-07-20, both reviewers):
    # Opus challenging Sonnet is a manager grading their own company's work —
    # same base data, same RLHF, shared blind spots. Set
    # OMNICAST_NARRATIVE_CHALLENGER_PROVIDER=deepseek (with live balance!) to
    # give the release challenger a genuinely different lineage. With no
    # balance the challenger is unreachable and releases fail closed — set the
    # flag only after topping up. Default unchanged: Opus.
    challenger_provider = _opt(
        "OMNICAST_NARRATIVE_CHALLENGER_PROVIDER", "anthropic"
    ).lower()
    if challenger_provider == "deepseek" and deepseek_pro is not None:
        challenger = deepseek_pro
    else:
        challenger = claude(challenger_model, challenger_effort, "release_challenger")
    # Generator-side cost routing: plan repairs and surgical patches are ALWAYS
    # re-validated by the checkers (preflight + plan audit; trial gate + blind
    # selector + monotonic re-score), so both producers run on the cheap tier.
    # Live 2026-07-18: the planner role burned 44% of a run's quota, most of it
    # on repair/retry re-emissions that did not need Opus-depth judgement.
    plan_repair_model = _opt("OMNICAST_NARRATIVE_PLAN_REPAIR_MODEL", "claude-sonnet-5")
    plan_repair_effort = _opt("OMNICAST_NARRATIVE_PLAN_REPAIR_EFFORT", "medium")
    patch_model = _opt("OMNICAST_NARRATIVE_PATCH_MODEL", "claude-sonnet-5")
    patch_effort = _opt("OMNICAST_NARRATIVE_PATCH_EFFORT", "medium")
    plan_repair = claude(plan_repair_model, plan_repair_effort, "plan_repair")
    patch = claude(patch_model, patch_effort, "repair_writer")
    roles: dict[str, object] = {
        "plan_repair": plan_repair,
        "patch": patch,
        "judge_mode": "claude_only" if claude_only else "deepseek_first",
        "planner": planner,
        "writer": writer,
        "challenger": challenger,
    }
    model_roles = {
        "planner": f"{planner_model}/{planner_effort}",
        "writer": f"{writer_model}/{writer_effort}",
        "release_challenger": f"{challenger_model}/{challenger_effort}",
    }

    # Independent judge fallback on the operator's GOOGLE account (opt-in after
    # `gemini` login): in claude_only mode every judge shares one Anthropic
    # account, and a provider hiccup aborted whole runs with "no independent
    # fallback configured". A different company is a real failure domain.
    gemini_fallback = None
    if _runtime_flag(
        "OMNICAST_NARRATIVE_GEMINI_FALLBACK", "omnicast_narrative_gemini_fallback",
        settings,
    ):
        from omnicast.llm.gemini_cli import GeminiCLIClient
        gemini_model = _opt("OMNICAST_NARRATIVE_GEMINI_MODEL", "gemini-2.5-pro")
        gemini_fallback = GeminiCLIClient(model=gemini_model, role="judge_fallback")
        model_roles["judge_fallback"] = f"{gemini_model} (google)"

    if claude_only:
        roles.update({
            "critic": claude(judge_model, judge_effort, "critic_score"),
            # Same model and effort as the critic, but its own client so the CLI
            # log line says role=plan_audit instead of role=critic_score. The
            # identity is not disguised — model_roles below reports both stages
            # pointing at the same model, which is the truth.
            "plan_audit": claude(judge_model, judge_effort, "plan_audit"),
            "compliance": claude(judge_model, judge_effort, "story_compliance"),
            "annotation": claude(annotation_model, judge_effort, "annotation"),
            # A different MODEL for the audit escalation, so the "escalation must
            # not be the same client as the primary" rule still has something to
            # escalate TO. It is a different reader; it is not a different account.
            "plan_audit_escalation": claude(
                challenger_model, judge_effort, "plan_audit_escalation"
            ),
            # None when Gemini is not enabled: within one Anthropic account a
            # model swap is not a fallback. With Gemini on, the escalation is a
            # different COMPANY — a real second failure domain.
            "critic_fallback": gemini_fallback,
            "compliance_escalation": gemini_fallback,
            "annotation_fallback": gemini_fallback,
        })
        model_roles.update({
            "critic_score": f"{judge_model}/{judge_effort}",
            "plan_audit": f"{judge_model}/{judge_effort}",
            "plan_repair": f"{plan_repair_model}/{plan_repair_effort}",
            "repair_writer": f"{patch_model}/{patch_effort}",
            "story_compliance": f"{judge_model}/{judge_effort}",
            "annotation": f"{annotation_model}/{judge_effort}",
            "plan_audit_escalation": f"{challenger_model}/{judge_effort}",
        })
    else:
        judge_fallback = claude(judge_model, judge_effort, "judge_fallback")
        roles.update({
            "critic": deepseek_pro,
            # One client: DeepSeek has no per-role labelling to gain, and the
            # stages stay distinguishable through call_counts and model_roles.
            "plan_audit": deepseek_pro,
            "compliance": deepseek_flash,
            "annotation": deepseek_flash,
            "plan_audit_escalation": judge_fallback,
            "critic_fallback": judge_fallback,
            # NOT deepseek_pro: that is the same account as the primary, i.e. one
            # balance and one outage. A fallback that dies with its primary is not
            # a fallback.
            "compliance_escalation": judge_fallback,
            "annotation_fallback": claude(
                annotation_model, judge_effort, "annotation_fallback"
            ),
        })
        model_roles.update({
            "critic_score": "deepseek(primary)",
            "plan_audit": "deepseek(primary)",
            "plan_repair": f"{plan_repair_model}/{plan_repair_effort}",
            "repair_writer": f"{patch_model}/{patch_effort}",
            "story_compliance": "deepseek(primary)",
            "annotation": "deepseek(primary)",
            "judge_fallback": f"{judge_model}/{judge_effort}",
        })
    roles["model_roles"] = model_roles
    roles["max_quality"] = max_quality
    return roles


def _needs_length_only_fill(draft, feedback, brief, revise_below: int) -> bool:
    """True when the script is good enough but fails only the deterministic length gate.

    Sending an 85-point draft through a full rewrite merely because it is short
    produced three extra Claude calls and a worse 65-point candidate. Length is
    repaired with scene insertions; actual voice/continuity defects still revise.
    """
    from omnicast.agents.critic import VO_PASS, PROD_PASS, _canonical_spoken
    from omnicast.models.script import spoken_word_floor

    words = len(_canonical_spoken(draft).split())
    floor = spoken_word_floor(getattr(brief, "target_duration_min", None))
    under_length = words < int(floor * 0.9)
    quality_passes = (
        feedback.total_score >= revise_below
        and feedback.voiceover_score >= VO_PASS
        and feedback.production_score >= PROD_PASS
        and not feedback.continuity_issues
    )
    return bool(not feedback.approved and under_length and quality_passes)


def _script_result_rank(result, brief) -> tuple[bool, bool, int, int, int]:
    """Rank outputs without letting a short hard-gate failure win on score."""
    from omnicast.agents.critic import _canonical_spoken
    from omnicast.models.script import spoken_word_floor

    words = len(_canonical_spoken(result.final_draft).split())
    floor = spoken_word_floor(getattr(brief, "target_duration_min", None))
    length_ok = words >= int(floor * 0.9)
    # Among usable drafts, quality score wins. If every draft is under-length,
    # prefer the one closest to usable instead of shipping a 500-word fragment
    # merely because its subjective score is five points higher.
    primary = int(result.final_score) if length_ok else words
    return bool(result.approved), length_ok, primary, int(result.final_score), words


# ── Built-in steps ────────────────────────────────────────────────────────────

async def _step_discovery(inputs: dict[str, Any], ctx: StepContext) -> dict[str, Any]:
    """Phase 1: Topic discovery for a channel.

    Mirrors the proven server flow: DiscoveryOrchestrator.for_channel(profile).run()
    -> DiscoveryResult. Picks the top approved brief as the topic for downstream
    steps. (The previous wiring used a non-existent constructor/signature.)
    """
    channel_id: str = inputs["channel_id"]
    logger.info("pipeline.discovery: starting", channel=channel_id,
                execution=ctx.execution_id)
    from pathlib import Path as _P
    impl_root = _P(__file__).resolve().parents[3]
    sys.path.insert(0, str(impl_root))

    from omnicast.vault import db as vault_db
    vault_db.init_db(impl_root / "output" / "vault.db")

    from omnicast.config.channel import ChannelProfileLoader
    from omnicast.discovery.orchestrator import DiscoveryOrchestrator

    loader = ChannelProfileLoader(impl_root / "channels")
    channel = await loader.load(channel_id)
    orch = DiscoveryOrchestrator.for_channel(channel)
    result = await orch.run()

    # Prefer an auto-approved brief; fall back to the highest-scoring review topic.
    topic, score = "", 0
    if result.briefs:
        b = result.briefs[0]
        topic = getattr(b, "title", "") or ""
        score = int(getattr(b, "score", 0) or 0)
    elif result.scored_topics:
        top = max(result.scored_topics, key=lambda s: getattr(s, "score", 0))
        topic = getattr(top, "title", "") or ""
        score = int(getattr(top, "score", 0) or 0)
    if not topic:
        raise RuntimeError("discovery produced no usable topic")

    queue = [
        {
            "rank": i + 1,
            "title": getattr(b, "title", "") or "",
            "score": int(getattr(b, "score", 0) or 0),
            "audience_segment": getattr(b, "target_audience", "") or "",
            "pain_point": getattr(b, "pain_point", "") or "",
            "content_angle": getattr(b, "content_angle", "") or "",
            "source_url": getattr(b, "source_url", "") or "",
        }
        for i, b in enumerate(result.briefs)
        if getattr(b, "title", "")
    ]
    # Carry the winning brief's audience intelligence downstream so the script step
    # builds a RICH brief (depth) instead of a thin one. Next topic = 2nd brief → outro teaser.
    top_b = result.briefs[0] if result.briefs else None
    logger.info("pipeline.discovery: done", channel=channel_id, topic=topic[:60],
                approved=result.approved_count)
    return {
        "topic": topic, "score": score, "topic_queue": queue,
        "audience": getattr(top_b, "target_audience", "") if top_b else "",
        "pain_point": getattr(top_b, "pain_point", "") if top_b else "",
        "content_angle": getattr(top_b, "content_angle", "") if top_b else "",
        "next_topic": queue[1]["title"] if len(queue) > 1 else "",
    }


async def _step_script(inputs: dict[str, Any], ctx: StepContext) -> dict[str, Any]:
    """Phase 2: Script generation via the Writer/Critic/Evolution debate.

    Mirrors the proven server flow (DebateOrchestrator) and writes the same
    output/scripts/<channel>/<topic_slug>/variant_*.txt|json files the render step
    + dashboard expect. Returns the best variant's .txt path. (The previous wiring
    referenced a non-existent ScriptOrchestrator.)
    """
    channel_id: str = inputs["channel_id"]
    topic: str = inputs.get("topic") or ""
    if not topic:
        raise ValueError("script step requires 'topic' input")
    logger.info("pipeline.script: starting", channel=channel_id, topic=topic[:60])

    # ── Observability (dashboard) — best-effort, works from BOTH entry paths ──
    # Before this, CLI runs recorded NOTHING (no events, no cost, no live log)
    # and API runs recorded cost_usd=0 — "Chi phí hôm nay" stayed $0.00 and the
    # debate was invisible in the app.
    try:
        from omnicast.api import state as _api_state
    except Exception:
        _api_state = None
    _is_api = "api" in (getattr(ctx, "pipeline_id", "") or "")

    def _live(msg: str, _type: str = "info", **kw) -> None:
        if _api_state:
            try:
                _api_state.append_live_log(channel_id, {"type": _type, "msg": msg, **kw})
            except Exception:
                pass

    def _prog(stage: str, pct: int, detail: str = "") -> None:
        if _api_state:
            try:
                _api_state.set_active_job_progress(
                    channel_id, stage=stage, pct=pct, detail=detail)
            except Exception:
                pass

    if _api_state and not _is_api:  # CLI run — register like the API path does
        try:
            _api_state.set_active_job(channel_id, "script_generation", topic=topic)
            _api_state.clear_live_log(channel_id)
            _api_state.write_pipeline_event(channel_id, "script_generation", "started",
                                            topic=topic)
        except Exception:
            pass

    # Per-run LLM cost accounting: the session accumulator is process-wide, so a
    # long-lived backend would otherwise report CUMULATIVE spend in every meta.
    try:
        from omnicast.llm.client import reset_session_cost as _reset_cost
        _reset_cost()
    except Exception:
        pass

    import json as _json
    import re as _re
    from pathlib import Path as _P
    from omnicast.config.settings import get_settings
    from omnicast.config.channel import ChannelProfileLoader
    from omnicast.config.niches import get_niche_config
    from omnicast.models.script import ScriptDraft, ScriptSegment, TopicBrief, TopicSource
    from omnicast.agents.writer import WriterAgent
    from omnicast.agents.critic import CriticAgent
    from omnicast.agents.thinking import ThinkingAgent
    from omnicast.agents.compliance import ComplianceChecker
    from omnicast.agents.evolution import EvolutionAgent
    from omnicast.agents.visual_director import VisualDirectorAgent
    from omnicast.agents.orchestrator import DebateOrchestrator, DebateConfig, DebateResult
    from omnicast.services.budget import BudgetManager

    impl_root = _P(__file__).resolve().parents[3]
    vault_path = impl_root / "output" / "vault.db"
    from omnicast.vault import db as vault_db
    vault_db.init_db(vault_path)
    if vault_db.topic_has_script_product(channel_id, topic, vault_path):
        raise RuntimeError(f"Topic already has a script/product: {topic}")

    settings = get_settings()
    loader = ChannelProfileLoader(impl_root / "channels")
    channel = await loader.load(channel_id)
    # niche_config_key ("psychology.horror") overrides the niche/sub_niche lookup —
    # free-text sub_niche never matches a NICHE_CONFIGS key, so without this a
    # horror channel silently got the generic psychology (science-explainer) rules.
    _ncfg_key = (getattr(channel, "niche_config_key", "") or "").strip()
    if _ncfg_key and "." in _ncfg_key:
        _nk, _sk = _ncfg_key.split(".", 1)
        niche_cfg = get_niche_config(_nk, _sk)
    elif _ncfg_key:
        niche_cfg = get_niche_config(_ncfg_key)
    else:
        niche_cfg = get_niche_config(channel.niche.value, channel.sub_niche)

    # Audience intelligence (from discovery brief; fall back to channel.audience).
    aud_in = (inputs.get("audience") or "").strip()
    if not aud_in and isinstance(channel.audience, dict):
        aud_in = (channel.audience.get("segment") or channel.audience.get("description") or "").strip()
    pain_in = (inputs.get("pain_point") or "").strip()
    angle_in = (inputs.get("content_angle") or "").strip()
    next_topic = (inputs.get("next_topic") or "").strip()

    # Cross-video anti-repetition: feed the channel's recent names/motifs FORWARD
    # so the writer invents fresh ones (closes the loop the fingerprint guard opens).
    _avoid_kp = ""
    try:
        from omnicast.agents import cross_video as _xv
        _an, _am = _xv.recent_avoid(channel_id)
        _aa = _xv.recent_archetypes(channel_id)
        if _an or _am:
            _avoid_kp = ("DO NOT REUSE from recent videos on this channel — "
                         f"character names: {', '.join(_an[:15]) or 'none'}; "
                         f"motifs: {', '.join(_am) or 'none'}. Invent fresh names/props.")
        if _aa:
            _avoid_kp = (_avoid_kp + "\n" if _avoid_kp else "") + (
                "Recent videos already used these threat/escape archetypes — vary from "
                f"them, do not repeat the same shape: {', '.join(_aa)}.")
    except Exception as _xv_exc:  # noqa: BLE001
        # Fail-open is deliberate (a broken history file must not block a run)
        # but SILENT fail-open is not: without this line every video after a
        # corrupt fingerprint store would quietly lose all cross-video
        # anti-repetition (external review 2026-07-20 flagged the bare pass).
        logger.warning("cross-video freshness unavailable; generating without it",
                       channel=channel_id, error=str(_xv_exc)[:200])

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
        competitor_intel_required=bool(
            getattr(channel, "competitor_intel_required", False)),
        **TopicBrief.scope_fields_from_channel(channel, title=topic),
        target_audience=aud_in,
        pain_point=pain_in,
        content_angle=angle_in,
        next_topic=next_topic,
        key_points=[p for p in [
            _avoid_kp,
            f"Operator brief: {inputs.get('operator_desc', '').strip()}" if inputs.get("operator_desc") else "",
            niche_cfg.hook_examples[0][:80] if niche_cfg.hook_examples else "",
            f"Key insight from {niche_cfg.proof_sources[0]}" if niche_cfg.proof_sources else "",
            f"Insider angle: {niche_cfg.insider_angle}",
            f"Content angle: {angle_in}" if angle_in else "",
            f"Audience pain: {pain_in}" if pain_in else "",
        ] if p],
    )

    llm_claude = _llm_client("anthropic", db_path=vault_path)
    llm_pro = _llm_client("deepseek", model=settings.deepseek_pro_model, db_path=vault_path)
    llm_flash = _llm_client("deepseek", model=settings.deepseek_flash_model, db_path=vault_path)
    # SPEED/COST (measured 2026-07-08: ~34min/$0.27 per script, ~20 LLM calls):
    # - Writer on deepseek-chat (non-reasoning): v4-pro burned 7-14k REASONING
    #   tokens per 5-14k-token draft (2-4 min/call, ~85% of wall time). Drafting
    #   doesn't need chain-of-thought — Critic (kept on v4-pro) + hard gates +
    #   Claude polish are the quality anchors.
    # - max_rounds 2: measured rounds 3+ only ever LOWERED scores (74→66, 69→55).
    # - run_tournament False: 2 variants are already scored by Critic — the extra
    #   Elo pairwise call added latency and once ranked a 66 ABOVE an 84.
    llm_writer = _llm_client("deepseek", model=settings.deepseek_chat_model, db_path=vault_path)

    _channel_brand_top = {
        "brand_voice": getattr(channel, "brand_voice", "") or "",
        "tone": getattr(channel, "tone", "") or "",
        "hook_format": getattr(channel, "hook_format", "") or "",
        "voice_persona": getattr(channel, "voice_persona", "") or "",
    }
    _audience_top = channel.audience if isinstance(getattr(channel, "audience", None), dict) else None

    # ── FLOW SWITCH (OMNICAST_SCRIPT_FLOW = claude_first | debate) ───────────
    # claude_first (default): the double-payment problem, measured 2026-07-08 —
    # the debate paid deepseek ~$0.15 for drafts that Claude then REWROTE for
    # ~$0.35 (69→92). Claude writing ONE draft directly costs ~$0.20 and its
    # from-scratch quality ≥ its rewrite quality. deepseek-v4-pro stays as the
    # cheap judge (~$0.01/score); one Claude revise only if <82/unapproved.
    # Typical: 2-3 LLM calls, ~$0.20-0.30, ~8-12 min (vs 26-40 min debate).
    # Unit-first is opt-in through a named channel profile. This prevents a horror
    # strategy from silently changing unrelated narrative channels.
    _script_profile_id = (getattr(channel, "script_profile", "") or "").strip()
    _default_flow = (
        "unit_first"
        if niche_cfg.content_format == "narrative" and _script_profile_id
        else "claude_first"
    )
    _flow = os.environ.get("OMNICAST_SCRIPT_FLOW", _default_flow).strip().lower()
    _narrative_result = None
    if _flow == "unit_first":
        if niche_cfg.content_format != "narrative":
            raise ValueError("unit_first currently requires a narrative channel strategy")
        if not _script_profile_id:
            raise ValueError("unit_first requires channel.script_profile")
        from omnicast.agents.narrative_pipeline import (
            NamedChannelStrategy,
            NarrativeRunExhausted,
            NarrativeUnitPipeline,
        )
        from omnicast.config.narrative_quality import resolve_script_profile

        _quality_strategy = NamedChannelStrategy.from_quality_profile(
            resolve_script_profile(_script_profile_id)
        )

        # ── MODEL ROLES ──────────────────────────────────────────────────────
        # One immutable client per role, resolved once for this run (see
        # _narrative_role_clients). claude_only is the temporary mode for an
        # exhausted DeepSeek quota: every role becomes a Claude CLI client and no
        # DeepSeek client is even constructed for this flow, so no DeepSeek call
        # is reachable. Unset restores DeepSeek-first with no code change.
        _roles = _narrative_role_clients(
            settings, vault_path=vault_path,
            deepseek_pro=llm_pro, deepseek_flash=llm_flash,
        )
        _judge_mode = _roles["judge_mode"]
        _model_roles = _roles["model_roles"]
        logger.info(
            "pipeline.script: unit_first model roles",
            judge_mode=_judge_mode, max_quality=_roles["max_quality"],
            **_model_roles,
        )

        _prog("Planning story compilation", 20, detail=topic[:60])
        _live(
            f"Planner ({_model_roles['planner']}, judge_mode={_judge_mode}): "
            "locking distinct story briefs…",
            "agent_start",
        )
        # Whether these variable names REALLY denote different providers is decided
        # at runtime by resolved LLMClient identity, never by the name — the
        # CapabilityBus can resolve "anthropic" onto DeepSeek (as it did on
        # 2026-07-17, where every recorded cost was a DeepSeek model). The pipeline
        # records the answer instead of assuming it, and the challenger is measured
        # against the judges that ACTUALLY ran, including fallbacks.
        _unit = NarrativeUnitPipeline(
            planner_llm=_roles["planner"],
            writer_llm=_roles["writer"],
            plan_repair_llm=_roles["plan_repair"],
            patch_llm=_roles["patch"],
            critic_llm=_roles["critic"],
            plan_audit_llm=_roles["plan_audit"],
            annotation_llm=_roles["annotation"],
            annotation_fallback_llm=_roles["annotation_fallback"],
            compliance_llm=_roles["compliance"],
            compliance_escalation_llm=_roles["compliance_escalation"],
            critic_fallback_llm=_roles["critic_fallback"],
            plan_audit_escalation_llm=_roles["plan_audit_escalation"],
            release_challenger_llm=_roles["challenger"],
            quality_strategy=_quality_strategy,
            judge_mode=_judge_mode,
            model_roles=_model_roles,
        )
        try:
            _narrative_result = await _unit.run_with_retry(
                brief,
                channel_brand=_channel_brand_top,
                recent_avoid=_avoid_kp,
                annotate=True,
                max_attempts=int(os.environ.get("OMNICAST_UNIT_ATTEMPTS", "2")),
            )
        except NarrativeRunExhausted as _exhausted:
            # Every attempt failed, so there is no result to dump — and this is the
            # run that spent the most and produced least, i.e. exactly the one whose
            # bill must not disappear. Persist the evidence, then re-raise unchanged.
            # No score and no script are invented: this folder is not a product.
            from omnicast.storage import products as _fail_products
            _fail_dir = _fail_products.new_product_dir(channel_id, topic)
            (_fail_dir / "narrative_failure_audit.json").write_text(_json.dumps({
                "channel": channel_id,
                "topic": topic,
                "outcome": "aborted",
                "stage": "narrative_run_exhausted",
                "judge_mode": _judge_mode,
                "model_roles": _model_roles,
                "reason": str(_exhausted)[:2000],
                "evidence": _exhausted.evidence.model_dump(mode="json"),
                "rejected_plans": [
                    _plan.model_dump(mode="json") for _plan in _exhausted.rejected_plans
                ],
            }, indent=2, ensure_ascii=False), encoding="utf-8")
            logger.error(
                "pipeline.script: narrative run exhausted; no candidate produced",
                attempts=_exhausted.evidence.attempts_executed,
                aggregate_cost_usd=_exhausted.evidence.aggregate_cost_usd,
                aggregate_notional_cost_usd=_exhausted.evidence.aggregate_notional_cost_usd,
                calls=_exhausted.evidence.aggregate_call_counts,
                audit=str(_fail_dir / "narrative_failure_audit.json"),
            )
            _live(
                f"Narrative run exhausted after {_exhausted.evidence.attempts_executed} "
                f"attempt(s), ${_exhausted.evidence.aggregate_cost_usd:.4f} marginal / "
                f"${_exhausted.evidence.aggregate_notional_cost_usd:.4f} notional; "
                f"evidence: {_fail_dir.name}/narrative_failure_audit.json",
                "agent_error",
            )
            raise
        _prog("Narrative release gate", 82,
              detail=f"score {_narrative_result.scorecard.total_score}/100")
        _challenge = _narrative_result.release_challenge
        _live(
            f"Unit-first audit: {_narrative_result.scorecard.total_score}/100; "
            f"{_narrative_result.gate_report.total_words} words; "
            f"{len(_narrative_result.gate_report.failures)} hard failures; "
            f"{_narrative_result.attempts_executed} attempt(s), "
            f"${_narrative_result.aggregate_cost_usd:.4f} marginal / "
            f"${_narrative_result.aggregate_notional_cost_usd:.4f} notional; "
            f"challenger={_challenge.status if _challenge else 'not_reached'}"
            + (
                " (NOT provider-independent)"
                if _challenge is not None
                and _challenge.status in {"passed", "failed"}
                and not _challenge.challenger_is_independent
                else ""
            ),
            "critic_score", score=_narrative_result.scorecard.total_score,
        )
        if _challenge is not None and _challenge.status in {"passed", "failed"} \
                and not _challenge.challenger_is_independent:
            # A challenger on the critic's own provider still reads with the
            # critic's assumptions; the veto is worth less than it looks.
            logger.warning(
                "pipeline.script: release challenger is not provider-independent",
                challenger_status=_challenge.status,
            )
        # Preserve a narration-only candidate for needs_edit diagnostics. It is
        # never promoted to canonical script.txt unless every release gate passes.
        # Same cold-open dedup as assemble_draft: story_1 often opens with the
        # cold open verbatim, and a separate hook would speak it twice.
        _unit_stories = _narrative_result.stories
        _unit_cold = _narrative_result.plan.cold_open
        _unit_hook = (
            "" if _unit_stories
            and _unit_stories[0].narration.strip().startswith(_unit_cold.strip())
            else _unit_cold
        )
        _unit_draft = _narrative_result.draft or ScriptDraft(
            variant_id="unit_first",
            brief_title=topic,
            hook=_unit_hook,
            segments=[ScriptSegment(
                index=index,
                heading=story.title,
                content=story.narration,
                estimated_duration_seconds=round(len(story.narration.split()) / 2.5),
            ) for index, story in enumerate(_narrative_result.stories, 1)],
            word_count=_narrative_result.gate_report.total_words,
            estimated_duration_seconds=round(_narrative_result.gate_report.total_words / 2.5),
        )
        results = [DebateResult(
            variant_id="unit_first", final_draft=_unit_draft,
            final_score=_narrative_result.scorecard.total_score,
            approved=_narrative_result.production_ready,
            converged=True, rounds=[], exit_reason=(
                "production_ready" if _narrative_result.production_ready else "needs_edit"
            ),
        )]
    elif _flow == "claude_first":
        _cw = WriterAgent(llm=llm_claude)
        _cc = CriticAgent(llm=llm_pro)
        _prog("Writer (Claude) drafting", 30, detail=topic[:60])
        _live("Writer (claude-sonnet): drafting full script with prosody…", "agent_start")
        drafts = await _cw.execute(
            brief, num_variants=1, niche_cfg=niche_cfg,
            audience=_audience_top, channel_brand=_channel_brand_top)
        d0 = drafts[0]
        _live(f"Draft ready — {d0.word_count} spoken words, "
              f"{sum(len(s.scenes) for s in d0.segments) + len(d0.hook_scenes) + len(d0.outro_scenes)} scenes",
              "agent_done")
        _prog("Critic (deepseek-pro) scoring", 55)
        _live("Critic (deepseek-v4-pro): scoring draft…", "agent_start")
        fb = await _cc.execute(d0, brief, niche_cfg=niche_cfg,
                               channel_brand=_channel_brand_top)
        _live(f"Critic: {fb.total_score}/100 (VO {fb.voiceover_score}/70, "
              f"prod {fb.production_score}/30){' — APPROVED' if fb.approved else ''}",
              "critic_score", score=fb.total_score)
        best_draft, best_fb = d0, fb
        # Revise threshold (OMNICAST_REVISE_BELOW, default 82). The revise pass
        # re-emits the WHOLE script (~10-15k output tokens ≈ $0.15-0.25) — it is
        # the single biggest cost lever. Lower the bar for cheap mode; an
        # APPROVED draft always skips regardless.
        _revise_below = int(os.environ.get("OMNICAST_REVISE_BELOW", "82"))
        if _needs_length_only_fill(d0, fb, brief, _revise_below):
            from omnicast.agents.critic import _canonical_spoken as _canon_words
            _prog("Writer filling length", 72,
                  detail="high-quality draft — inserting only missing scenes")
            _live("Writer (claude-sonnet): adding missing scenes only…", "agent_start")
            d1 = await _cw.ensure_length(
                d0, brief, niche_cfg=niche_cfg,
                channel_brand=_channel_brand_top, audience=_audience_top)
            if len(_canon_words(d1).split()) > len(_canon_words(d0).split()):
                fb1 = await _cc.execute(
                    d1, brief, niche_cfg=niche_cfg,
                    channel_brand=_channel_brand_top)
                _live(f"Length-filled draft scored {fb1.total_score}/100"
                      f"{' — APPROVED' if fb1.approved else ''}", "critic_score",
                      score=fb1.total_score)
                if (fb1.approved and not fb.approved) or fb1.total_score > fb.total_score \
                        or (fb1.total_score == fb.total_score and
                            len(_canon_words(d1).split()) > len(_canon_words(d0).split())):
                    best_draft, best_fb = d1, fb1
        elif not fb.approved or fb.total_score < _revise_below:
            _prog("Writer (Claude) revising", 72,
                  detail=f"score {fb.total_score} < {_revise_below} — targeted revision")
            _live("Writer (claude-sonnet): revising per critic feedback…", "agent_start")
            d1 = await _cw.revise(
                d0, fb, brief, niche_cfg=niche_cfg,
                channel_brand=_channel_brand_top, audience=_audience_top)
            fb1 = await _cc.execute(d1, brief, niche_cfg=niche_cfg,
                                    channel_brand=_channel_brand_top)
            _live(f"Revision scored {fb1.total_score}/100"
                  f"{' — APPROVED' if fb1.approved else ''}", "critic_score",
                  score=fb1.total_score)
            if fb1.total_score > fb.total_score or (fb1.approved and not fb.approved):
                best_draft, best_fb = d1, fb1
        logger.info("pipeline.script: claude_first flow",
                    score=best_fb.total_score, approved=best_fb.approved)
        results = [DebateResult(
            variant_id="claude", final_draft=best_draft,
            final_score=best_fb.total_score, approved=best_fb.approved,
            converged=True, rounds=[], exit_reason="claude_first")]
    else:
        # Measured horror A/B (2026-07-15): merge+expand+fresh-score cost extra
        # calls yet produced a 920-word cliché-heavy draft that did not beat the
        # source variants. Keep Evolution available for explicit experiments,
        # but do not pay for it in normal debate runs.
        _run_evolution = os.environ.get(
            "OMNICAST_DEBATE_EVOLUTION", "0"
        ).strip().lower() in {"1", "true", "yes", "on"}

        def _debate_evt(e: dict) -> None:
            # Forward every orchestrator event (debate rounds, scores, evolution)
            # into the app's live monitor — the debate was previously invisible.
            _live(str(e.get("msg", ""))[:200], str(e.get("type", "debate")))

        orchestrator = DebateOrchestrator(
            writer=WriterAgent(llm=llm_writer),
            critic=CriticAgent(llm=llm_pro),
            thinker=ThinkingAgent(llm=llm_flash),
            compliance=ComplianceChecker(llm=llm_flash),
            budget=BudgetManager(daily_budget_usd=settings.daily_llm_budget_usd),
            config=DebateConfig(max_rounds=2, convergence_delta=3, approval_threshold=70,
                                run_tournament=False, run_evolution=_run_evolution),
            evolution=EvolutionAgent(llm=llm_claude) if _run_evolution else None,
            visual_director=VisualDirectorAgent(llm=llm_flash),
            event_callback=_debate_evt,
        )
        _prog("Debate: writer × critic", 35, detail="2 variants, deepseek-chat writer")
        results = await orchestrator.run(brief, num_variants=2, channel=channel)
    if not results:
        raise RuntimeError("script generation produced no variants")

    # ── Cross-video repetition guard: flag character names / motifs reused across
    # this channel's recent scripts (a single critic can't see prior videos). ──
    try:
        from omnicast.agents import cross_video as _xv
        from omnicast.agents.critic import _canonical_spoken as _canon
        _best = max(results, key=lambda r: _script_result_rank(r, brief))
        # Feed the compilation's typed archetypes into the rolling fingerprint so
        # the NEXT video's planner is told to vary from them (unit_first only —
        # other flows have no locked mechanism plan and pass archetypes=None).
        _archetypes = None
        if _narrative_result is not None:
            _archetypes = [
                f"{getattr(s, 'threat_identity', '')}/{getattr(s, 'escape_mechanism', '')}"
                for s in _narrative_result.plan.stories
            ]
        _reuse = (_xv.check_and_record(channel_id, _canon(_best.final_draft),
                                       archetypes=_archetypes)
                  if _best.approved else [])
        for _f in _reuse:
            logger.warning("pipeline.script: cross-video reuse", channel=channel_id, flag=_f)
            _live("⚠ cross-video reuse — " + _f, "reuse_warn")
    except Exception as _xve:
        logger.warning("cross-video guard skipped", error=str(_xve))

    # ONE self-contained product folder per run (see omnicast.storage.products):
    #   products/{channel}/{stamp}_{slug}/ {script.txt, variants/, video.mp4, meta.json}
    from omnicast.storage import products as _products
    product_dir = _products.new_product_dir(channel_id, topic)
    vdir = _products.variants_dir(product_dir)

    def _scene_dict(seg_heading: str, sc) -> dict:
        """Full scene serialization INCLUDING prosody (pace/pause_after_ms/
        emphasis). The old whitelist silently dropped prosody, so the renderer
        never saw the delivery direction — the main 'flat robot voice' cause."""
        return {
            "segment": seg_heading, "voiceover": sc.voiceover,
            "visual_prompt": sc.visual_prompt, "sfx": sc.sfx, "duration_s": sc.duration_s,
            "pace": getattr(sc, "pace", "normal"),
            "pause_after_ms": getattr(sc, "pause_after_ms", 0),
            "emphasis": list(getattr(sc, "emphasis", []) or []),
        }

    def _all_scene_dicts(d) -> list[dict]:
        out = [_scene_dict("HOOK", sc) for sc in (d.hook_scenes or [])]
        for seg in (d.segments or []):
            out += [_scene_dict(seg.heading, sc) for sc in (seg.scenes or [])]
        out += [_scene_dict("OUTRO", sc) for sc in (d.outro_scenes or [])]
        return out

    for r in results:
        d = r.final_draft
        txt = (d.hook + "\n\n") if d.hook else ""
        for seg in (d.segments or []):
            txt += f"[{seg.heading}]\n{seg.content}\n\n"
        txt += d.outro
        base = f"variant_{r.variant_id}_score{r.final_score}"
        (vdir / f"{base}.txt").write_text(txt, encoding="utf-8")
        (vdir / f"{base}.json").write_text(_json.dumps({
            "variant_id": r.variant_id, "score": r.final_score, "approved": r.approved,
            "hook": d.hook, "outro": d.outro, "scenes": _all_scene_dicts(d),
            "channel_id": channel_id, "topic": topic,
        }, indent=2, ensure_ascii=False), encoding="utf-8")
        # Raw LLM output — the only way to diagnose whether the model actually
        # followed the format (prosody fields, scene JSON) vs a parse problem.
        if getattr(d, "raw_content", ""):
            (vdir / f"{base}.raw.txt").write_text(d.raw_content, encoding="utf-8")

    best = max(results, key=lambda r: _script_result_rank(r, brief))

    # ── COMMERCIAL POLISH PASS (Claude) ────────────────────────────────────
    # DeepSeek revisions plateau at ~65-75 and often REGRESS (measured 74→66).
    # For commercial-grade output the WINNING draft gets ONE Claude rewrite
    # driven by the freshest critic feedback, then is re-scored — kept only if
    # it actually beats the original. Cost ≈ +$0.10-0.20/run.
    _POLISH_MIN = 82   # commercial floor: below this, always try the polish
    # Also polish when the winner is UNAPPROVED at any score (e.g. an 84-point
    # script hard-gated for being under the word floor — Claude's revise path
    # re-expands to the floor while keeping prosody).
    # claude_first flow already IS Claude write+revise — a third Claude attempt
    # rarely helps and doubles cost, so polish only applies to the debate flow.
    if _flow not in {"claude_first", "unit_first"} \
            and (best.final_score < _POLISH_MIN or not best.approved):
        try:
            _channel_brand = {
                "brand_voice": getattr(channel, "brand_voice", "") or "",
                "tone": getattr(channel, "tone", "") or "",
                "hook_format": getattr(channel, "hook_format", "") or "",
                "voice_persona": getattr(channel, "voice_persona", "") or "",
            }
            _critic = CriticAgent(llm=llm_pro)
            if getattr(best, "rounds", None):
                _fb1 = max(
                    best.rounds,
                    key=lambda r: (r.feedback.approved, r.feedback.total_score),
                ).feedback
            else:  # evolved draft has no debate rounds — score it fresh
                _fb1 = await _critic.execute(
                    best.final_draft, brief,
                    niche_cfg=niche_cfg, channel_brand=_channel_brand)
            _claude_writer = WriterAgent(llm=llm_claude)
            _polished = await _claude_writer.revise(
                best.final_draft, _fb1, brief, niche_cfg=niche_cfg,
                channel_brand=_channel_brand)
            _fb2 = await _critic.execute(
                _polished, brief, niche_cfg=niche_cfg, channel_brand=_channel_brand)
            logger.info("pipeline.script: claude polish",
                        before=best.final_score, after=_fb2.total_score,
                        kept=_fb2.total_score > best.final_score)
            _pbase = f"variant_polished_score{_fb2.total_score}"
            _ptxt = _polished.hook + "\n\n"
            for seg in (_polished.segments or []):
                _ptxt += f"[{seg.heading}]\n{seg.content}\n\n"
            _ptxt += _polished.outro
            (vdir / f"{_pbase}.txt").write_text(_ptxt, encoding="utf-8")
            (vdir / f"{_pbase}.json").write_text(_json.dumps({
                "variant_id": "polished", "score": _fb2.total_score,
                "approved": _fb2.approved, "hook": _polished.hook,
                "outro": _polished.outro, "scenes": _all_scene_dicts(_polished),
                "channel_id": channel_id, "topic": topic,
            }, indent=2, ensure_ascii=False), encoding="utf-8")
            if getattr(_polished, "raw_content", ""):
                (vdir / f"{_pbase}.raw.txt").write_text(
                    _polished.raw_content, encoding="utf-8")
            # Keep the polish if it scores higher OR if it turns an unapproved
            # winner into an approved one (approval > a couple raw points).
            if _fb2.total_score > best.final_score or (_fb2.approved and not best.approved):
                best.variant_id = "polished"
                best.final_draft = _polished
                best.final_score = _fb2.total_score
                best.approved = _fb2.approved
        except Exception as _pe:
            logger.warning("pipeline.script: claude polish skipped", error=str(_pe))

    if _narrative_result is not None:
        (product_dir / "narrative_audit.json").write_text(_json.dumps(
            _narrative_result.model_dump(mode="json", exclude={"draft"}),
            indent=2, ensure_ascii=False), encoding="utf-8")

    # A rejected candidate remains inspectable but is not a renderable product.
    # This gate also closes the historical claude_first/debate hole where any
    # highest-scoring draft was promoted even when Critic rejected it.
    if not best.approved:
        _candidate = vdir / f"variant_{best.variant_id}_score{best.final_score}.txt"
        _needs_edit = product_dir / "needs_edit.txt"
        _needs_edit.write_text(_candidate.read_text(encoding="utf-8"), encoding="utf-8")
        try:
            from omnicast.llm.client import get_session_cost as _get_reject_cost
            _reject_cost = _get_reject_cost()
        except Exception:
            _reject_cost = None
        _products.write_meta(
            product_dir, channel=channel_id, topic=topic, slug=product_dir.name,
            stage="needs_edit", script=None, best_variant=best.variant_id,
            score=best.final_score, approved=False, script_approved=False,
            content_locked=bool(_narrative_result and _narrative_result.content_locked),
            production_ready=False, release_gate_version=1,
            candidate="needs_edit.txt",
            deterministic_gates=(
                _narrative_result.gate_report.model_dump(mode="json")
                if _narrative_result else None
            ),
            critical_issues=(
                _narrative_result.scorecard.critical_issues
                if _narrative_result else []
            ),
            llm_cost_script_usd=(_reject_cost["total"] if _reject_cost else None),
            llm_cost_script_by_model=(_reject_cost["by_model"] if _reject_cost else None),
        )
        raise RuntimeError(
            f"Script failed release gate ({best.final_score}/100); candidate saved at {_needs_edit}"
        )

    # The approved script becomes the canonical product script.txt (rendered next).
    best_txt = _products.script_path(product_dir)
    best_txt.write_text(
        (vdir / f"variant_{best.variant_id}_score{best.final_score}.txt").read_text(encoding="utf-8"),
        encoding="utf-8")
    script_path = str(best_txt)

    # ── FACT-CITATION LEDGER (YMYL finance rubric only, fail-closed) ─────────
    # An approved finance script is NOT releasable until every figure carries a
    # source + date and year-sensitive figures cite the current rule year. The
    # LLM proposes the binding; gate_fact_ledger validates deterministically.
    _fact_gate_report = None
    if (getattr(niche_cfg, "rubric_id", "") or "") == "finance_explainer_v1":
        from datetime import datetime as _dt, timezone as _tz

        from omnicast.agents.fact_ledger_agent import FactLedgerAgent
        from omnicast.compliance.fact_ledger import gate_fact_ledger, render_markdown

        _script_text = best_txt.read_text(encoding="utf-8")
        _prog("Fact ledger (claim→source)", 78, detail="binding every figure to a source")
        _live("FactLedger (claude): binding every figure to a source + year…", "agent_start")
        _ledger = await FactLedgerAgent(llm=llm_claude).execute(
            _script_text,
            proof_sources=list(getattr(niche_cfg, "proof_sources", []) or []),
            current_year=_dt.now(_tz.utc).year,
            model_label="claude",
        )
        _fact_gate_report = gate_fact_ledger(_script_text, _ledger)
        (product_dir / "fact_ledger.json").write_text(_json.dumps({
            "ledger": _ledger.model_dump(mode="json"),
            "gate": _fact_gate_report.model_dump(mode="json"),
        }, indent=2, ensure_ascii=False), encoding="utf-8")
        (product_dir / "fact_ledger.md").write_text(
            render_markdown(_ledger, _fact_gate_report), encoding="utf-8")
        _live(f"Fact ledger: {_fact_gate_report.covered_count}/{_fact_gate_report.claim_count} "
              f"claims covered — GATE {'PASSED' if _fact_gate_report.passed else 'FAILED'}",
              "gate")
        if not _fact_gate_report.passed:
            _needs = product_dir / "needs_citations.txt"
            _needs.write_text(_script_text, encoding="utf-8")
            _products.write_meta(
                product_dir, channel=channel_id, topic=topic, slug=product_dir.name,
                stage="needs_citations", script=None, best_variant=best.variant_id,
                score=best.final_score, approved=True, script_approved=True,
                production_ready=False, release_gate_version=1,
                candidate="needs_citations.txt",
                fact_ledger_gate=_fact_gate_report.model_dump(mode="json"),
            )
            raise RuntimeError(
                "Fact-ledger gate FAILED (fail-closed — every figure needs a source "
                "and current-year recency): " + "; ".join(_fact_gate_report.notes[:3]))

    # PROSODY SIDECAR: script.json = full storyboard (all scenes incl. prosody)
    # of the winning draft. render_real_video prefers this over prose script.txt
    # so per-scene pace/pause/emphasis actually reach TTS. Skipped only if the
    # draft has no scenes (legacy prosody output).
    def _clamp_pauses(scene_dicts: list[dict]) -> list[dict]:
        """vfact benchmark: 3-6 DELIBERATE pauses >=400ms per 10min. Models emit
        14-23 (measured) — uniform drama = no drama. Keep only the K longest
        pauses at full length; downgrade the rest to a 250ms micro-beat."""
        est_min = max(1.0, sum(len(s["voiceover"].split()) for s in scene_dicts) / 150.0)
        k = max(3, round(est_min * 0.6))          # ~6 per 10 minutes
        big = sorted((i for i, s in enumerate(scene_dicts)
                      if (s.get("pause_after_ms") or 0) >= 400),
                     key=lambda i: -scene_dicts[i]["pause_after_ms"])
        for i in big[k:]:
            scene_dicts[i]["pause_after_ms"] = 250
        return scene_dicts

    _best_scenes = _clamp_pauses(_all_scene_dicts(best.final_draft))
    if _best_scenes:
        (product_dir / "script.json").write_text(_json.dumps({
            "topic": topic, "channel_id": channel_id,
            "variant_id": best.variant_id, "score": best.final_score,
            "scenes": _best_scenes,
        }, indent=2, ensure_ascii=False), encoding="utf-8")

    # LENGTH GUARD (mirrors server phase2): evolution often MERGES variants into a
    # shorter script. A thin 700-word script renders a shallow video. Expand the
    # best one back to ~1300 spoken words so depth matches the manual flow.
    def _spoken_words(text: str) -> int:
        # Count spoken words for EITHER format: JSON ("vo" fields) or plain prose
        # (hook + [SECTION HEADING] lines + paragraphs + outro). The old "vo"-only
        # count silently returned 0 on prose scripts → expand never fired.
        vo = _re.findall(r'"vo"\s*:\s*"(.*?)"', text, _re.S)
        if vo:
            return sum(len(v.split()) for v in vo)
        body = _re.sub(r'^\s*\[[^\]]+\]\s*$', '', text, flags=_re.M)  # drop heading lines
        return len(body.split())

    try:
        _TARGET_VO = 1300
        _MAX_VO = 1500          # hard ceiling — an over-expanded script = a bloated,
        _ACCEPT_MAX = 1700      # repetitive 18-min video + huge Flow image load.
        cur = best_txt.read_text(encoding="utf-8") if best_txt.exists() else ""
        best_vo = _spoken_words(cur)
        # A prosody storyboard (script.json) beats +100 words of prose: expanding
        # rewrites prose only, which forces deleting the sidecar and the renderer
        # loses ALL pace/pause/emphasis. If the draft already clears the 8-min
        # floor (1200 vo words), keep the storyboard and skip the expand.
        _strict = os.environ.get("OMNICAST_STRICT", "1") != "0"
        if (product_dir / "script.json").exists() and best_vo >= 1200:
            logger.info("pipeline.script: expand skipped — prosody storyboard kept",
                        vo_words=best_vo)
        elif _strict and (product_dir / "script.json").exists():
            # STRICT: prose-expand would DELETE the prosody sidecar (pace/pause/
            # emphasis) — that's a quality downgrade, not a fix. A short script
            # here means the writer/critic gates failed upstream: fail loudly.
            raise RuntimeError(
                f"Script has only {best_vo} spoken words with a prosody storyboard — "
                "STRICT mode refuses the prose expand that would destroy prosody. "
                "Fix the writer length gates and regenerate.")
        elif cur and 0 < best_vo < _TARGET_VO:
            logger.info("pipeline.script: expanding", from_words=best_vo, target=_TARGET_VO)
            exp = _llm_client("deepseek", model=settings.deepseek_chat_model, db_path=vault_path)
            pr = (f"Expand this YouTube script to BETWEEN {_TARGET_VO} AND {_MAX_VO} spoken "
                  f"words (currently ~{best_vo}). Do NOT exceed {_MAX_VO} words — pad just "
                  "enough with extra concrete examples, data points, and short mini-stories "
                  "woven into the EXISTING BODY sections only. Keep the EXACT SAME STRUCTURE "
                  "AND FORMAT as the input (same hook, same [SECTION HEADINGS] / JSON blocks, "
                  "same single outro). Leave the HOOK and the OUTRO/CTA WORD-FOR-WORD UNCHANGED "
                  "— do NOT lengthen them, do NOT add channel-promo or recap sentences to the "
                  "outro. Do NOT add new sections or a second outro, do NOT repeat yourself. "
                  f"No scam/demonetize words. Output the FULL expanded script ONLY.\n\n{cur}")
            r = await exp.complete(
                system="You expand video scripts while preserving their exact structure and format.",
                messages=[{"role": "user", "content": pr[:16000]}],
                max_tokens=15000, temperature=0.4)
            new_vo = _spoken_words(r.content or "")
            # Accept only a real, non-bloated expansion. Reject overshoot (model
            # sometimes balloons prose 3x) → keep the original tighter script.
            if r.content and best_vo * 1.1 < new_vo <= _ACCEPT_MAX:
                best_txt.write_text(r.content, encoding="utf-8")
                # script.json no longer matches the expanded prose — remove it so
                # the renderer doesn't render a stale, shorter storyboard.
                (product_dir / "script.json").unlink(missing_ok=True)
                logger.info("pipeline.script: length-expanded", from_words=best_vo, to_words=new_vo)
            else:
                logger.warning("pipeline.script: expand rejected",
                               from_words=best_vo, new_words=new_vo, accept_max=_ACCEPT_MAX)
        else:
            logger.info("pipeline.script: expand not needed", vo_words=best_vo)
    except Exception as e:
        logger.warning("pipeline.script: expand skipped", error=str(e))

    _prog("Saving product", 92, detail=product_dir.name)
    _script_cost = None
    try:
        from omnicast.llm.client import get_session_cost
        _script_cost = get_session_cost()
    except Exception:
        pass
    _products.write_meta(
        product_dir, channel=channel_id, topic=topic, slug=product_dir.name,
        # PILLAR SSOT. `brief.pillar_id` is the answer the scorer and the writer
        # both used; packaging reads it back off this metadata. Without this
        # line the field the renderer looks for is never written, so packaging
        # silently falls back to re-classifying the script text — and a video
        # already filed under one pillar can take another pillar's playbook.
        pillar_id=getattr(brief, "pillar_id", "") or "",
        intel_archetype=getattr(brief, "intel_archetype", "") or "",
        audience_segment=getattr(brief, "audience_segment", "") or "",
        content_format=getattr(brief, "content_format", "") or "",
        stage="script", script="script.txt", best_variant=best.variant_id,
        score=best.final_score, approved=True, script_approved=True,
        content_locked=True, production_ready=True, release_gate_version=1,
        script_sha256=hashlib.sha256(
            _products.script_path(product_dir).read_bytes()
        ).hexdigest(),
        storyboard_sha256=(
            hashlib.sha256((product_dir / "script.json").read_bytes()).hexdigest()
            if (product_dir / "script.json").exists() else None
        ),
        deterministic_gates=(
            _narrative_result.gate_report.model_dump(mode="json")
            if _narrative_result else None
        ),
        critical_issues=(
            _narrative_result.scorecard.critical_issues
            if _narrative_result else []
        ),
        fact_ledger_gate=(
            _fact_gate_report.model_dump(mode="json") if _fact_gate_report else None
        ),
        llm_cost_script_usd=(_script_cost["total"] if _script_cost else None),
        llm_cost_script_by_model=(_script_cost["by_model"] if _script_cost else None))
    from datetime import datetime, timezone
    vault_db.mark_topic_used_by_title(
        channel_id, topic, datetime.now(timezone.utc).isoformat(), product_dir.name, vault_path
    )

    # ── Observability: the completed event carries score AND cost, and the run
    # cost feeds "Chi phí hôm nay" (both were $0.00/-missing before). ─────────
    _run_cost = float(_script_cost["total"]) if _script_cost else 0.0
    if _api_state:
        try:
            _api_state.write_pipeline_event(
                channel_id, "script_generation", "completed",
                topic=topic, score=int(best.final_score), cost_usd=_run_cost,
                extra={"script_path": script_path, "variant": best.variant_id,
                       "flow": _flow, "approved": bool(best.approved)})
            if _run_cost:
                _api_state.accumulate_cost(_run_cost, category="LLM Script")
            _live(f"Done — score {best.final_score}, ${_run_cost:.2f}, "
                  f"variant {best.variant_id}", "phase_complete")
            if not _is_api:
                _api_state.clear_active_job(channel_id)
        except Exception:
            pass

    logger.info("pipeline.script: done", channel=channel_id, script_path=script_path,
                product=product_dir.name, score=best.final_score,
                llm_cost_usd=(_script_cost["total"] if _script_cost else None))
    return {"script_path": script_path, "product_dir": str(product_dir),
            "variant_id": best.variant_id, "score": best.final_score,
            "approved": True, "content_locked": True,
            "production_ready": True, "release_gate_version": 1}


async def _step_render(inputs: dict[str, Any], ctx: StepContext) -> dict[str, Any]:
    """Phase 3: FFmpeg render via subprocess."""
    channel_id: str = inputs["channel_id"]
    script_path: str = inputs.get("script_path") or ""
    if not script_path:
        raise ValueError("render step requires 'script_path' input")

    from pathlib import Path as _P
    from omnicast.storage import products as _products
    _release_issues = _products.release_issues_for_script(_P(script_path))
    if _release_issues:
        raise RuntimeError(
            "Render blocked by script release gate: " + ", ".join(_release_issues)
        )
    impl_root = _P(__file__).resolve().parents[3]
    render_script = impl_root / "render_real_video.py"

    # Render INTO the same product folder as the script — video.mp4 lands next to
    # script.txt + variants/ + meta.json (render_real_video derives thumb/title/
    # _assets/_status from --out, so they all stay co-located & isolated per video).
    from omnicast.storage import products as _products
    product_dir = _products.product_dir_for_asset(_P(script_path))
    if not _products.is_product_dir(product_dir):
        # Legacy/manual script outside products/ — make a product folder for it.
        product_dir = _products.new_product_dir(channel_id, _P(script_path).stem)
    out_mp4 = _products.video_path(product_dir)

    # Repair budget (Orkas draft-repair pattern): the scheduler re-runs failed
    # pipelines, and every re-render of the SAME script re-spends Flow quota /
    # credits. After 3 failures with unchanged inputs the render is blocked
    # until the script/config changes or _repair_state.json is deleted.
    from omnicast.pipeline.repair_budget import RepairBudget, content_signature
    try:
        _script_text = _P(script_path).read_text(encoding="utf-8", errors="replace")
    except Exception:
        _script_text = script_path
    _sig = content_signature(
        _script_text, channel_id,
        f"shorts={bool(inputs.get('shorts'))}",
        f"beat_words={inputs.get('beat_words', 12)}")
    _budget = RepairBudget.load(product_dir / "_repair_state.json")
    if _budget.blocked(_sig):
        _le = (_budget.state.get("last_error") or {})
        raise RuntimeError(
            f"Render blocked by repair budget: {_budget.failed_attempts} failed "
            f"renders with unchanged inputs (last: {_le.get('code')}: "
            f"{_le.get('message', '')[:120]}). Fix the script/config, or delete "
            f"{product_dir / '_repair_state.json'} to force a retry.")

    def _audit_rendered_output() -> dict:
        from omnicast.media.output_audit import OutputQualityAuditor

        audit = OutputQualityAuditor().inspect_product(out_mp4, product_dir)

        # §9 quality gates run INSIDE `inspect_product`, before the sidecar is
        # written, and their failures are already audit issues by the time we
        # get here — so `audit["passed"]` below is a real gate. Running them out
        # here appended a report to a file that had already been written and
        # never fed the verdict back, which is telemetry, not a gate.
        quality = audit.get("quality_gates") or {}

        try:
            _products.write_meta(
                product_dir,
                output_audit="_output_audit.json",
                output_audit_passed=bool(audit.get("passed")),
                output_audit_issues=audit.get("issues") or [],
                quality_gate_coverage=quality.get("coverage"),
                quality_gates_failed=quality.get("failed") or [],
                quality_needs_human=quality.get("needs_human") or [],
                # The publish gate reads this. The render does NOT fail on it:
                # blocking the render blocked the only route to the review that
                # would clear the flag.
                requires_human_review=bool(audit.get("requires_human_review")),
                artifact_sha256=OutputQualityAuditor.artifact_hash(out_mp4),
            )
        except Exception as exc:
            logger.warning("pipeline.render: output audit meta write failed", error=str(exc))
        if not audit.get("passed"):
            issues = ", ".join(str(issue) for issue in audit.get("issues") or [])
            _budget.record_failure(_sig, "output_audit", issues)
            raise RuntimeError(f"Output audit failed: {issues}")
        if audit.get("requires_human_review"):
            logger.info(
                "pipeline.render: product flagged for human review",
                channel=channel_id,
                gates=audit.get("human_review_gates") or [],
                note="render succeeded; publish is gated until a review is recorded")
        return audit

    async def _auto_queue_approval() -> None:
        """After a render passes QC, auto-create a HITL approval so PASS videos reach
        Duyệt & Đăng instead of sitting in Studio (defect Đ6 — the 24/7 chain's last
        step used to be manual). Best-effort; never fails the render. Skips Shorts and
        can be disabled with OMNICAST_AUTO_QUEUE=0."""
        if os.environ.get("OMNICAST_AUTO_QUEUE", "1") == "0" or inputs.get("shorts"):
            return
        try:
            import httpx
            port = os.environ.get("OMNICAST_PORT", "8767")
            async with httpx.AsyncClient(timeout=15) as client:
                await client.post(
                    f"http://127.0.0.1:{port}/api/publish/{channel_id}",
                    json={"video_path": str(out_mp4)})
            logger.info("pipeline.render: auto-queued for approval", channel=channel_id)
        except Exception as exc:
            logger.info("pipeline.render: auto-queue skipped", channel=channel_id, error=str(exc))

    beat_words = int(inputs.get("beat_words", 12))  # vfact benchmark: ~4-5s/shot (was 18)
    base = [sys.executable, "-X", "utf8", str(render_script),
            "--script", str(script_path), "--channel", channel_id,
            "--beat-words", str(beat_words), "--subtitles", "--out", str(out_mp4)]
    if inputs.get("shorts"):
        base.append("--shorts")

    async def _run(extra: list[str]) -> tuple[int, str]:
        proc = await asyncio.create_subprocess_exec(
            *(base + extra), cwd=str(impl_root),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        out, err = await proc.communicate()
        # Renderer prints its audit/error diagnostics to STDOUT — discarding it
        # made every audit block look like a silent crash (codex verify).
        combined = ((err.decode(errors="replace") if err else "")
                    + "\n" + (out.decode(errors="replace")[-2000:] if out else ""))
        return proc.returncode, combined.strip()

    from omnicast.compliance.fact_ledger import AUDIT_EXIT_CODE as _AUDIT_RC

    def _audit_stop(rc: int, err: str) -> None:
        """A fact/chart AUDIT failure is a compliance stop, not a render bug —
        no retry, no --all-stock degrade, on ANY render path."""
        if rc == _AUDIT_RC:
            _budget.record_failure(_sig, "render_ymyl_audit", err[-300:])
            raise RuntimeError(
                "Render BLOCKED by YMYL fact/chart audit (no retry, no fallback): "
                + err[-500:])

    # FLOW_SKIP=1 → go straight to all-stock (fast, reliable acceptance runs / when
    # Flow is flaky). Otherwise try Flow first for the richest visuals.
    if os.environ.get("FLOW_SKIP") == "1":
        logger.info("pipeline.render: FLOW_SKIP=1 → all-stock", channel=channel_id)
        rc, err = await _run(["--all-stock"])
        _audit_stop(rc, err)
        if rc != 0 or not out_mp4.exists():
            _budget.record_failure(_sig, "render_all_stock", err[-300:])
            raise RuntimeError(f"Render failed (all-stock). rc={rc}: {err[-500:]}")
        size_mb = round(out_mp4.stat().st_size / 1e6, 2)
        _tf = out_mp4.with_name(out_mp4.stem + "_title.txt")
        try:
            _products.write_meta(product_dir, stage="render", video=out_mp4.name,
                thumbnail=out_mp4.with_name(out_mp4.stem + "_thumb.png").name,
                title_file=_tf.name,
                title=(_tf.read_text(encoding="utf-8").strip() if _tf.exists() else None),
                size_mb=size_mb, visuals="all-stock", flow_degraded=False)
        except Exception:
            pass
        audit = _audit_rendered_output()
        _budget.record_success(_sig, "all-stock render + audit passed")
        await _auto_queue_approval()
        logger.info("pipeline.render: done", channel=channel_id, out=str(out_mp4), flow="skipped")
        return {"video_path": str(out_mp4), "product_dir": str(product_dir),
                "file_size_mb": size_mb, "flow_degraded": False, "visuals": "all-stock",
                "output_audit": audit.get("metadata", {}).get("audit_sidecar", "_output_audit.json")}

    # Try Flow image gen first (richest visuals). If it fails — most commonly the
    # Flow browser session expired (Playwright timeout) — fall back to all-stock
    # B-roll so the pipeline ALWAYS produces a video instead of dead-ending.
    logger.info("pipeline.render: starting (flow)", channel=channel_id, out=str(out_mp4))
    rc, err = await _run(["--images", "flow"])
    flow_ok = (rc == 0 and out_mp4.exists())
    flow_degraded = False
    # A fact/chart AUDIT failure is a compliance stop, not a Flow outage — the
    # --all-stock retry would bypass the very check that fired (codex audit
    # 2026-07-26 finding 7). Distinct exit code → hard stop, no degradation.
    _audit_stop(rc, err)
    if not flow_ok:
        # Most Flow failures = the Google login session in .flow_profile expired
        # (Playwright can't find the prompt box / times out). Make that LOUD and
        # actionable instead of silently shipping a lower-quality all-stock video.
        _low = (err or "").lower()
        _expired = any(s in _low for s in (
            "timeout", "role=\"textbox\"", "role='textbox'", "textbox",
            "login", "sign in", "logged out", "session"))
        if _expired:
            logger.error(
                "pipeline.render: FLOW SESSION LIKELY EXPIRED → re-login required. "
                "Run:  python -X utf8 scripts/flow_login.py   "
                "(falling back to all-stock for THIS video)",
                channel=channel_id, tail=err[-300:])
        else:
            logger.warning("pipeline.render: flow failed → all-stock fallback",
                           channel=channel_id, tail=err[-300:])
        flow_degraded = True
        rc, err = await _run(["--all-stock"])
        _audit_stop(rc, err)
        if rc != 0 or not out_mp4.exists():
            _budget.record_failure(_sig, "render_flow_allstock", err[-300:])
            raise RuntimeError(f"Render failed (flow + all-stock). rc={rc}: {err[-500:]}")

    size_mb = round(out_mp4.stat().st_size / 1e6, 2)
    _title_f = out_mp4.with_name(out_mp4.stem + "_title.txt")
    try:
        _products.write_meta(
            product_dir, stage="render", video=out_mp4.name,
            thumbnail=out_mp4.with_name(out_mp4.stem + "_thumb.png").name,
            title_file=_title_f.name,
            title=(_title_f.read_text(encoding="utf-8").strip() if _title_f.exists() else None),
            size_mb=size_mb, visuals=("flow" if flow_ok else "all-stock"),
            flow_degraded=flow_degraded)
    except Exception as _me:
        logger.warning("pipeline.render: meta write failed", error=str(_me))

    audit = _audit_rendered_output()
    _budget.record_success(_sig, f"render + audit passed ({'flow' if flow_ok else 'all-stock'})")
    await _auto_queue_approval()
    logger.info("pipeline.render: done", channel=channel_id, out=str(out_mp4),
                product=product_dir.name, flow=("ok" if flow_ok else "all-stock-fallback"))
    return {"video_path": str(out_mp4), "product_dir": str(product_dir),
            "file_size_mb": size_mb, "flow_degraded": flow_degraded,
            "visuals": "flow" if flow_ok else "all-stock",
            "output_audit": audit.get("metadata", {}).get("audit_sidecar", "_output_audit.json")}


async def _step_upload(inputs: dict[str, Any], ctx: StepContext) -> dict[str, Any]:
    """Phase 4: YouTube Data API v3 upload."""
    channel_id: str = inputs["channel_id"]
    video_path: str = inputs.get("video_path") or ""
    if not video_path:
        raise ValueError("upload step requires 'video_path' input")

    from pathlib import Path as _P
    impl_root = _P(__file__).resolve().parents[3]
    sys.path.insert(0, str(impl_root))

    from omnicast.api.render_routes import _yt_oauth, upload_video  # type: ignore
    mgr = _yt_oauth()
    if not mgr.has_token(channel_id):
        raise PermissionError(f"No YouTube OAuth token for channel {channel_id}. "
                              "Authorize via the dashboard first.")

    privacy = inputs.get("privacy", "private")
    logger.info("pipeline.upload: starting", channel=channel_id, privacy=privacy)
    result = await upload_video(channel_id, video=None, privacy=privacy)
    if not isinstance(result, dict):  # e.g. a policy-block JSONResponse
        raise RuntimeError(f"upload rejected (non-OK response): {result!r}")
    url = result.get("url", "")
    logger.info("pipeline.upload: done", channel=channel_id, url=url)
    return {"url": url, "video_id": result.get("youtube_video_id", ""),
            "status": result.get("status")}


async def _step_policy_check(inputs: dict[str, Any], ctx: StepContext) -> dict[str, Any]:
    """Run the YouTube policy watcher (fetch + diff + LLM extract)."""
    from pathlib import Path as _P
    from omnicast.compliance.policy_fetcher import run_policy_check
    from omnicast.config.settings import get_settings
    from omnicast.vault import db as vault_db
    impl_root = _P(__file__).resolve().parents[3]
    VAULT_DB = impl_root / "output" / "vault.db"
    vault_db.init_db(VAULT_DB)
    settings = get_settings()
    llm = _llm_client("deepseek", model=settings.deepseek_flash_model, db_path=VAULT_DB)
    new_rules = await run_policy_check(llm, VAULT_DB)
    return {"new_pending_rules": new_rules}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _load_channel(channel_id: str, impl_root: Path) -> dict:
    import json
    p = impl_root / "channels" / f"{channel_id}.json"
    if not p.exists():
        raise FileNotFoundError(f"Channel config not found: {p}")
    return json.loads(p.read_text(encoding="utf-8"))


# ── Register built-ins ────────────────────────────────────────────────────────

register_step("omnicast.discovery",    _step_discovery)
register_step("omnicast.script",       _step_script)
register_step("omnicast.render",       _step_render)
register_step("omnicast.upload",       _step_upload)
register_step("omnicast.policy_check", _step_policy_check)
