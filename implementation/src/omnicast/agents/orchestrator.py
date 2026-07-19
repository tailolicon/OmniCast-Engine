"""Debate Orchestrator — Co-Scientist style: adaptive rounds + Elo tournament + Evolution."""

from __future__ import annotations

from dataclasses import dataclass, field

import structlog

from omnicast.agents.writer import WriterAgent
from omnicast.agents.critic import CriticAgent, VO_PASS, PROD_PASS
from omnicast.agents.thinking import ThinkingAgent
from omnicast.agents.evals import run_binary_evals
from omnicast.agents.compliance import ComplianceChecker
from omnicast.services.budget import BudgetManager
from omnicast.models.script import (
    TopicBrief, ScriptDraft, CriticFeedback, DebateRound,
)
from omnicast.shared.errors import AgentError
from omnicast.config.niches import NicheConfig, get_niche_config

logger = structlog.get_logger()


@dataclass(frozen=True)
class DebateConfig:
    """Configuration for debate loop."""
    max_rounds: int = 7
    convergence_delta: int = 3        # stop if score improves < this
    budget_per_variant_usd: float = 0.50
    approval_threshold: int = 70
    run_tournament: bool = True       # Elo pairwise tournament after debate
    run_evolution: bool = True        # merge top variants after tournament


@dataclass
class DebateResult:
    """Result of one variant's debate loop."""
    variant_id: str
    final_draft: ScriptDraft
    final_score: int
    approved: bool
    converged: bool
    rounds: list[DebateRound] = field(default_factory=list)
    total_cost_usd: float = 0.0
    binary_eval_results: dict[str, bool] = field(default_factory=dict)
    exit_reason: str = ""
    elo_score: float = 1000.0


class DebateOrchestrator:
    """Runs the full Co-Scientist-style debate pipeline.

    Pipeline:
    1. Writer generates N variants (different angles)
    2. Each variant: adaptive Writer ↔ Critic rounds (stop on convergence)
    3. Elo pairwise tournament — variants compete for ranking
    4. EvolutionAgent merges top-ranked variants into final script
    """

    def __init__(
        self,
        writer: WriterAgent,
        critic: CriticAgent,
        thinker: ThinkingAgent,
        compliance: ComplianceChecker,
        budget: BudgetManager,
        config: DebateConfig | None = None,
        evolution=None,         # EvolutionAgent | None
        visual_director=None,   # VisualDirectorAgent | None
        event_callback=None,    # Callable[[dict], None] | None — live event sink
    ) -> None:
        self._writer = writer
        self._critic = critic
        self._thinker = thinker
        self._compliance = compliance
        self._budget = budget
        self._config = config or DebateConfig()
        self._evolution = evolution
        self._visual_director = visual_director
        self._event_cb = event_callback  # called synchronously; must be fast

    def _emit(self, event: dict) -> None:
        """Fire-and-forget event to caller. Never raises."""
        if self._event_cb:
            try:
                self._event_cb(event)
            except Exception:
                pass

    @staticmethod
    def _model_of(agent) -> str:
        """Best-effort model id of an agent's LLM (operator-facing detail)."""
        try:
            return getattr(getattr(agent, "_llm", None), "_model", "") or "?"
        except Exception:
            return "?"

    @staticmethod
    def _llm_cost(*agents) -> float:
        """Return cumulative cost once per distinct LLM client."""
        seen: set[int] = set()
        total = 0.0
        for agent in agents:
            client = getattr(agent, "_llm", None)
            if client is None or id(client) in seen:
                continue
            seen.add(id(client))
            try:
                total += float(getattr(client, "total_cost", 0.0) or 0.0)
            except (TypeError, ValueError):
                continue
        return total

    async def run(
        self,
        brief: TopicBrief,
        *,
        num_variants: int = 3,
        channel=None,  # ChannelProfile | None
    ) -> list[DebateResult]:
        """Generate variants, run debate, tournament, then evolution."""
        # Get niche config + channel-level overrides from ChannelProfile
        niche_cfg = None
        audience: dict | None = None
        channel_brand: dict | None = None
        if channel:
            from omnicast.config.channel import ChannelProfile
            if isinstance(channel, ChannelProfile):
                # Free-text sub_niche values do not necessarily map to the
                # registry. Honor the channel's explicit SSOT key so a horror
                # channel cannot silently enter the psychology explainer path.
                cfg_key = (getattr(channel, "niche_config_key", "") or "").strip()
                if cfg_key and "." in cfg_key:
                    cfg_niche, cfg_sub = cfg_key.split(".", 1)
                    niche_cfg = get_niche_config(cfg_niche, cfg_sub)
                elif cfg_key:
                    niche_cfg = get_niche_config(cfg_key)
                else:
                    niche_cfg = get_niche_config(channel.niche.value, channel.sub_niche)
                audience = channel.audience if channel.audience else None
                # Channel-level fields override NicheConfig defaults
                channel_brand = {
                    "brand_voice": channel.brand_voice,
                    "tone": channel.tone,
                    "hook_format": channel.hook_format,   # LLM-generated, beats NicheConfig
                    "voice_persona": channel.voice_persona,
                }

        self._emit({"type": "writer_start", "agent": "writer", "model": self._model_of(self._writer),
                    "msg": f"Writer Agent ({self._model_of(self._writer)}): generating {num_variants} variants…"})
        try:
            variants = await self._writer.execute(
                brief,
                num_variants=num_variants,
                niche_cfg=niche_cfg,
                audience=audience,
                channel_brand=channel_brand,
            )
        except Exception as exc:
            raise AgentError(f"Writer failed to generate variants: {exc}") from exc

        self._emit({"type": "writer_done", "msg": f"Writer: {len(variants)} variant(s) ready — starting debate"})

        # Phase 1: Debate each variant independently
        results = []
        for draft in variants:
            self._emit({"type": "debate_start", "variant_id": draft.variant_id, "msg": f"Debate: variant_{draft.variant_id} entering arena"})
            result = await self._debate_variant(draft, brief, niche_cfg, channel_brand=channel_brand)
            results.append(result)

        # Phase 2: Elo pairwise tournament
        if self._config.run_tournament and len(results) > 1:
            self._emit({"type": "tournament_start", "msg": f"Tournament: {len(results)} variants competing (Elo)"})
            results = await self._run_elo_tournament(results, brief)
            logger.info(
                "Elo tournament complete",
                winner=results[0].variant_id,
                elo=results[0].elo_score,
            )
            self._emit({"type": "tournament_done", "msg": f"Tournament: winner = variant_{results[0].variant_id} (Elo {results[0].elo_score:.0f})"})

        # Phase 3: Evolution — merge top variants into superior final script.
        # COST GATE: only when NO variant got approved. An approved script ships
        # as-is — measured 2026-07-08: the evolution chain (1 Claude call + 2-3
        # huge expand calls) produced a 71 that LOST to the approved 84 anyway.
        if (self._config.run_evolution and self._evolution and len(results) > 1
                and not any(r.approved for r in results)):
            self._emit({"type": "evolution_start", "agent": "evolution", "model": self._model_of(self._evolution),
                        "msg": f"Evolution Agent ({self._model_of(self._evolution)}): merging top variants into final script…"})
            try:
                _evolution_cost_before = self._llm_cost(
                    self._writer, self._critic, self._evolution, self._compliance)
                # Without the Elo tournament, results arrive unranked — sort by
                # score so evolution really merges the TOP variants.
                _ranked = sorted(results, key=lambda r: r.final_score, reverse=True)
                top_variants = [r.final_draft for r in _ranked[:3]]
                winner_id = _ranked[0].variant_id
                evolved_draft = await self._evolution.execute(
                    top_variants, brief, winner_id=winner_id, niche_cfg=niche_cfg
                )
                # The evolved draft is what WINS (inserted at index 0), yet it never
                # passed the writer's word-floor gate — the merge LLM lands short
                # (baseline: 748-word evolved winner < 8-min mid-roll floor). Expand
                # it through the same path the generated variants use.
                try:
                    evolved_draft = await self._writer.ensure_length(
                        evolved_draft, brief,
                        niche_cfg=niche_cfg, channel_brand=channel_brand)
                except Exception as _len_exc:
                    logger.warning("Evolved word-floor expand failed", error=str(_len_exc))
                evolved_feedback = await self._critic.execute(
                    evolved_draft,
                    brief,
                    threshold=self._config.approval_threshold,
                    niche_cfg=niche_cfg,
                    channel_brand=channel_brand,
                )
                evolved_compliance = True
                if evolved_feedback.approved:
                    try:
                        evolved_compliance, _ = await self._compliance.execute(
                            evolved_draft, niche=brief.niche)
                    except Exception as _compliance_exc:
                        logger.warning(
                            "Evolved compliance check failed", error=str(_compliance_exc))
                        evolved_compliance = False
                evolved_round = DebateRound(
                    round_number=1,
                    draft=evolved_draft,
                    feedback=evolved_feedback,
                    score_delta=evolved_feedback.total_score - _ranked[0].final_score,
                )
                evolution_cost = self._llm_cost(
                    self._writer, self._critic, self._evolution, self._compliance
                ) - _evolution_cost_before
                evolved_result = DebateResult(
                    variant_id="evolved",
                    final_draft=evolved_draft,
                    final_score=evolved_feedback.total_score,
                    approved=evolved_feedback.approved and evolved_compliance,
                    converged=True,
                    rounds=[evolved_round],
                    binary_eval_results=run_binary_evals(evolved_draft),
                    exit_reason="evolved",
                    elo_score=1000.0,
                    total_cost_usd=max(0.0, evolution_cost),
                )
                results.append(evolved_result)
                logger.info("Evolution complete", variants_merged=len(top_variants))
                self._emit({"type": "evolution_done", "msg": f"Evolution: done — score {evolved_result.final_score}"})
            except Exception as exc:
                logger.warning("Evolution failed, using best variant", error=str(exc))
                self._emit({"type": "evolution_fail", "msg": f"Evolution failed: {exc}"})

        results.sort(key=lambda r: (r.approved, r.final_score), reverse=True)
        best = results[0] if results else None
        self._emit({"type": "pipeline_done", "msg": f"Pipeline complete — best score {best.final_score if best else '?'}", "approved": best.approved if best else False})
        return results

    async def _debate_variant(
        self,
        draft: ScriptDraft,
        brief: TopicBrief,
        niche_cfg: NicheConfig | None = None,
        channel_brand: dict | None = None,
    ) -> DebateResult:
        """Run adaptive debate loop for single variant.

        Stops when: approved | delta < convergence_delta | loop-lock | budget | max_rounds.
        """
        rounds: list[DebateRound] = []
        current_draft = draft
        exit_reason = ""
        # Snapshot every distinct client. Writer/Critic may share one client, so
        # summing by agent can double-count.
        _cost_before = self._llm_cost(
            self._writer, self._critic, self._compliance, self._visual_director)
        # Safe default feedback in case no rounds complete
        feedback = CriticFeedback.model_construct(
            variant_id=draft.variant_id,
            total_score=0,
            approved=False,
        )

        for round_num in range(1, self._config.max_rounds + 1):
            _variant_spend = self._llm_cost(
                self._writer, self._critic, self._compliance, self._visual_director
            ) - _cost_before
            if _variant_spend >= self._config.budget_per_variant_usd:
                exit_reason = "variant_budget_stop"
                logger.warning(
                    "Per-variant budget reached",
                    variant_id=draft.variant_id,
                    spent_usd=_variant_spend,
                )
                break
            if not self._budget.can_spend(0.05):
                exit_reason = "budget_stop"
                logger.warning("Budget limit reached", variant_id=draft.variant_id)
                break

            # Critic review
            try:
                feedback = await self._critic.execute(
                    current_draft,
                    brief,
                    threshold=self._config.approval_threshold,
                    niche_cfg=niche_cfg,
                    channel_brand=channel_brand,
                )
            except Exception as exc:
                raise AgentError(f"Critic review failed: {exc}") from exc

            # Delta-based convergence (Co-Scientist style)
            prev_score = rounds[-1].feedback.total_score if rounds else 0
            score_delta = feedback.total_score - prev_score

            round_record = DebateRound(
                round_number=round_num,
                draft=current_draft,
                feedback=feedback,
                thinking_notes=current_draft.thinking_notes,
                score_delta=score_delta,
            )
            rounds.append(round_record)

            logger.info(
                "Debate round complete",
                variant_id=draft.variant_id,
                round=round_num,
                score=feedback.total_score,
                delta=score_delta,
                approved=feedback.approved,
            )

            # Live event for dashboard
            _delta_str = (f" (+{score_delta})" if score_delta > 0 else f" ({score_delta})" if score_delta < 0 else "") if round_num > 1 else ""
            _status = "✅ APPROVED" if feedback.approved else f"❌ score {feedback.total_score}{_delta_str}"
            # Routing decision (mirrors Co-Scientist two-stage split for operator clarity)
            # Length + continuity failures are WRITER problems — must not be routed
            # to the VisualDirector (which only fixes visuals) just because prod<23.
            _hard = any("HARD GATE" in r or "CONTINUITY" in r
                        for r in (feedback.rejection_reasons or []))
            if feedback.approved:
                _route = "approved"
            elif _hard or feedback.voiceover_score < 53:
                _route = "→ Writer (rewrite/expand)"
            elif feedback.production_score < 23:
                _route = "Prod<23 → VisualDirector refines visuals/sfx"
            else:
                _route = "revise"
            self._emit({
                "type": "round",
                "agent": "critic",
                "model": self._model_of(self._critic),
                "variant_id": draft.variant_id,
                "round": round_num,
                "score": feedback.total_score,
                "vo_score": feedback.voiceover_score,
                "prod_score": feedback.production_score,
                "score_delta": score_delta,
                "approved": feedback.approved,
                "routing": _route,
                "rejection_reasons": feedback.rejection_reasons[:3],
                "specific_fixes": (feedback.specific_fixes or [])[:3],   # → Writer
                "visual_fixes": (feedback.visual_fixes or [])[:3],       # → VisualDirector
                # 8-dimension breakdown (hook, anti-cliche, retention, editorial,
                # compliance, pacing, visual, sfx) for the expandable score grid.
                "dimensions": [
                    {"name": d.name, "score": d.score, "max": d.max_score, "feedback": (d.feedback or "")[:80]}
                    for d in (feedback.dimensions or [])
                ],
                "msg": f"Critic ({self._model_of(self._critic)}) → variant_{draft.variant_id} R{round_num}: "
                       f"VO {feedback.voiceover_score}/70 · Prod {feedback.production_score}/30 · Total {feedback.total_score}{_delta_str} — {_status} · {_route}",
            })

            # Termination checks
            if feedback.approved:
                exit_reason = "approved"
                break

            if round_num > 1 and score_delta < self._config.convergence_delta:
                exit_reason = "converged"
                logger.info(
                    "Converged — stopping early",
                    variant_id=draft.variant_id,
                    delta=score_delta,
                )
                self._emit({"type": "converged", "variant_id": draft.variant_id, "msg": f"variant_{draft.variant_id}: converged (delta={score_delta}) — stopping"})
                break

            if self._detect_loop_lock(rounds):
                exit_reason = "loop_lock"
                logger.warning("Loop lock detected", variant_id=draft.variant_id)
                self._emit({"type": "loop_lock", "variant_id": draft.variant_id, "msg": f"variant_{draft.variant_id}: loop-lock detected — stopping"})
                break

            if round_num >= self._config.max_rounds:
                exit_reason = "max_rounds"
                self._emit({
                    "type": "max_rounds",
                    "variant_id": draft.variant_id,
                    "msg": f"variant_{draft.variant_id}: max rounds reached",
                })
                break

            # ── Two-stage routing ──────────────────────────────────────────
            # Good VO but weak production → Visual Director only (lock VO)
            vo_ok = feedback.voiceover_score >= VO_PASS
            prod_ok = feedback.production_score >= PROD_PASS

            if vo_ok and not prod_ok and self._visual_director is not None:
                logger.info(
                    "Routing to Visual Director — VO locked",
                    variant_id=draft.variant_id,
                    vo_score=feedback.voiceover_score,
                    prod_score=feedback.production_score,
                )
                self._emit({"type": "visual_director", "variant_id": draft.variant_id, "msg": f"Visual Director → variant_{draft.variant_id}: VO locked, fixing visuals only"})
                try:
                    current_draft = await self._visual_director.execute(
                        current_draft,
                        brief,
                        niche_cfg=niche_cfg,
                        visual_fixes=feedback.visual_fixes,
                        channel_brand=channel_brand,
                    )
                except Exception as exc:
                    logger.warning("Visual Director failed, falling back to Writer", error=str(exc))
                    current_draft = await self._writer.revise(
                        current_draft, feedback, brief, niche_cfg=niche_cfg,
                        channel_brand=channel_brand)
            else:
                # VO needs work (or no visual director) → Writer rewrites
                self._emit({"type": "writer_revise", "variant_id": draft.variant_id, "msg": f"Writer → variant_{draft.variant_id}: revising (round {round_num+1})"})
                try:
                    current_draft = await self._writer.revise(
                        current_draft, feedback, brief, niche_cfg=niche_cfg,
                        channel_brand=channel_brand)
                except Exception as exc:
                    raise AgentError(f"Writer revision failed: {exc}") from exc
        else:
            exit_reason = "max_rounds"
            self._emit({"type": "max_rounds", "variant_id": draft.variant_id, "msg": f"variant_{draft.variant_id}: max rounds reached"})

        # A revision can regress. Ship the best scored round, not blindly the
        # final round that happened to trigger convergence.
        best_round = max(
            rounds,
            key=lambda r: (r.feedback.approved, r.feedback.total_score),
            default=None,
        )
        if best_round is not None:
            final_draft = best_round.draft
            final_feedback = best_round.feedback
        else:
            final_draft = current_draft
            final_feedback = feedback

        binary_results = run_binary_evals(final_draft)

        # Compliance — only if approved (YMYL niche)
        compliance_passed = True
        if final_feedback.approved:
            try:
                compliance_passed, _ = await self._compliance.execute(
                    final_draft, niche=brief.niche
                )
            except Exception as exc:
                logger.warning("Compliance check failed", error=str(exc))
                compliance_passed = False

        _cost_after = self._llm_cost(
            self._writer, self._critic, self._compliance, self._visual_director)
        total_cost = max(0.0, _cost_after - _cost_before)
        if total_cost:
            self._budget.record_spend(total_cost, agent="debate_variant")

        return DebateResult(
            variant_id=draft.variant_id,
            final_draft=final_draft,
            final_score=final_feedback.total_score,
            approved=final_feedback.approved and compliance_passed,
            converged=exit_reason == "converged",
            rounds=rounds,
            binary_eval_results=binary_results,
            exit_reason=exit_reason,
            total_cost_usd=total_cost,
        )

    async def _run_elo_tournament(
        self,
        results: list[DebateResult],
        brief: TopicBrief,
    ) -> list[DebateResult]:
        """Pairwise Elo tournament — each variant pair compared by Critic.

        Higher-rated variant beating lower-rated gains fewer points (like chess).
        After all pairs, sort by Elo descending.
        """
        K = 32  # Elo K-factor
        elo: dict[str, float] = {r.variant_id: 1000.0 for r in results}

        for i, r1 in enumerate(results):
            for r2 in results[i + 1:]:
                try:
                    winner_id = await self._critic.compare_variants(
                        r1.final_draft, r2.final_draft, brief
                    )
                except Exception as exc:
                    logger.warning("Pairwise comparison failed, skipping", error=str(exc))
                    continue

                # Elo update
                ea = 1.0 / (1.0 + 10 ** ((elo[r2.variant_id] - elo[r1.variant_id]) / 400))
                eb = 1.0 - ea

                if winner_id == r1.variant_id:
                    elo[r1.variant_id] += K * (1 - ea)
                    elo[r2.variant_id] += K * (0 - eb)
                else:
                    elo[r1.variant_id] += K * (0 - ea)
                    elo[r2.variant_id] += K * (1 - eb)

                logger.info(
                    "Pairwise comparison",
                    winner=winner_id,
                    elo_a=round(elo[r1.variant_id], 1),
                    elo_b=round(elo[r2.variant_id], 1),
                )

        # Attach Elo scores and sort
        for r in results:
            r.elo_score = round(elo[r.variant_id], 1)

        results.sort(key=lambda r: r.elo_score, reverse=True)
        return results

    def _detect_loop_lock(self, rounds: list[DebateRound]) -> bool:
        """Detect loop-lock: 5+ rounds, max score < 60, last 3 rounds flat (±2)."""
        if len(rounds) < 5:
            return False
        if max(r.feedback.total_score for r in rounds) >= 60:
            return False
        recent = [r.feedback.total_score for r in rounds[-3:]]
        return max(recent) - min(recent) <= 2
