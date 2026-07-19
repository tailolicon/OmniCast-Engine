"""Tests for Debate Orchestrator."""

import pytest
from unittest.mock import AsyncMock, MagicMock
from dataclasses import replace

from omnicast.agents.orchestrator import (
    DebateOrchestrator, DebateConfig, DebateResult,
)
from omnicast.agents.writer import WriterAgent
from omnicast.agents.critic import CriticAgent
from omnicast.agents.thinking import ThinkingAgent
from omnicast.agents.compliance import ComplianceChecker
from omnicast.services.budget import BudgetManager
from omnicast.llm.client import LLMClient
from omnicast.models.script import (
    TopicBrief, ScriptDraft, ScriptSegment, CriticFeedback,
    CriticDimension, DebateRound,
)
from omnicast.models.enums import Niche, Market, TopicSource
from omnicast.shared.errors import AgentError


def _make_mock_llm(total_cost: float = 0.0) -> MagicMock:
    llm = MagicMock()
    llm.total_cost = total_cost
    return llm


@pytest.fixture
def mock_writer() -> AsyncMock:
    writer = AsyncMock(spec=WriterAgent)
    writer.name = "writer"
    writer.cost = 0.01
    writer._llm = _make_mock_llm(0.01)
    return writer


@pytest.fixture
def mock_critic() -> AsyncMock:
    critic = AsyncMock(spec=CriticAgent)
    critic.name = "critic"
    critic.cost = 0.005
    critic._llm = _make_mock_llm(0.005)
    return critic


@pytest.fixture
def mock_thinker() -> AsyncMock:
    thinker = AsyncMock(spec=ThinkingAgent)
    thinker.execute.return_value = "Notes: transition weak."
    thinker._llm = _make_mock_llm(0.003)
    return thinker


@pytest.fixture
def mock_compliance() -> AsyncMock:
    comp = AsyncMock(spec=ComplianceChecker)
    comp.execute.return_value = (True, [])
    return comp


@pytest.fixture
def mock_budget() -> AsyncMock:
    budget = AsyncMock(spec=BudgetManager)
    budget.can_spend.return_value = True
    budget.record_spend = MagicMock()
    return budget


@pytest.fixture
def sample_brief() -> TopicBrief:
    return TopicBrief(
        title="Test Topic",
        niche=Niche.FINANCE,
        market=Market.US,
        source=TopicSource.MANUAL,
    )


@pytest.fixture
def sample_draft() -> ScriptDraft:
    return ScriptDraft(
        variant_id="A",
        brief_title="Test",
        hook="Short hook.",
        segments=[
            ScriptSegment(index=0, heading="Intro", content="Welcome.",
                          estimated_duration_seconds=25, has_pattern_interrupt=True),
            ScriptSegment(index=1, heading="Main", content="Content.",
                          estimated_duration_seconds=80, has_pattern_interrupt=True),
        ],
        outro="Thanks!",
        word_count=1500,
        estimated_duration_seconds=600,
    )


class TestDebateConfig:
    def test_defaults(self):
        config = DebateConfig()
        assert config.max_rounds == 7
        assert config.convergence_delta == 3
        assert config.budget_per_variant_usd == 0.50

    def test_frozen(self):
        config = DebateConfig()
        with pytest.raises(AttributeError):
            config.max_rounds = 10


class TestDebateOrchestrator:
    async def test_run_generates_variants(
        self, mock_writer, mock_critic, mock_thinker,
        mock_compliance, mock_budget, sample_brief, sample_draft,
    ):
        # Writer generates 2 variants
        mock_writer.execute.return_value = [
            sample_draft,
            ScriptDraft(variant_id="B", brief_title="Test", hook="Hook B.",
                        segments=sample_draft.segments, outro="End.",
                        word_count=1500, estimated_duration_seconds=600),
        ]
        # Critic approves immediately
        mock_critic.execute.return_value = CriticFeedback(
            variant_id="A", total_score=85, approved=True,
        )

        config = DebateConfig(max_rounds=3, approval_threshold=70)
        orch = DebateOrchestrator(
            writer=mock_writer, critic=mock_critic, thinker=mock_thinker,
            compliance=mock_compliance, budget=mock_budget, config=config,
        )
        results = await orch.run(sample_brief, num_variants=2)
        assert len(results) == 2
        assert all(isinstance(r, DebateResult) for r in results)

    async def test_approved_on_high_score(
        self, mock_writer, mock_critic, mock_thinker,
        mock_compliance, mock_budget, sample_brief, sample_draft,
    ):
        mock_writer.execute.return_value = [sample_draft]
        mock_critic.execute.return_value = CriticFeedback(
            variant_id="A", total_score=80, approved=True,
        )
        config = DebateConfig(approval_threshold=70)
        orch = DebateOrchestrator(
            writer=mock_writer, critic=mock_critic, thinker=mock_thinker,
            compliance=mock_compliance, budget=mock_budget, config=config,
        )
        results = await orch.run(sample_brief, num_variants=1)
        assert results[0].approved is True
        assert results[0].exit_reason == "approved"

    async def test_converges_on_low_improvement(
        self, mock_writer, mock_critic, mock_thinker,
        mock_compliance, mock_budget, sample_brief, sample_draft,
    ):
        mock_writer.execute.return_value = [sample_draft]
        mock_writer.revise.return_value = sample_draft  # unchanged

        # Critic gives stable low scores (small delta)
        scores = [60, 61, 62]  # delta < 3 after round 2
        call_count = 0

        async def critic_side_effect(*args, **kwargs):
            nonlocal call_count
            idx = min(call_count, len(scores) - 1)
            call_count += 1
            return CriticFeedback(
                variant_id="A", total_score=scores[idx], approved=False,
            )

        mock_critic.execute.side_effect = critic_side_effect
        config = DebateConfig(max_rounds=5, convergence_delta=3, approval_threshold=70)
        orch = DebateOrchestrator(
            writer=mock_writer, critic=mock_critic, thinker=mock_thinker,
            compliance=mock_compliance, budget=mock_budget, config=config,
        )
        results = await orch.run(sample_brief, num_variants=1)
        assert results[0].converged is True
        assert results[0].exit_reason == "converged"

    async def test_convergence_returns_best_round_not_regressed_last_round(
        self, mock_writer, mock_critic, mock_thinker,
        mock_compliance, mock_budget, sample_brief, sample_draft,
    ):
        revised = sample_draft.model_copy(update={"hook": "A worse revised hook."})
        mock_writer.execute.return_value = [sample_draft]
        mock_writer.revise.return_value = revised
        mock_critic.execute.side_effect = [
            CriticFeedback(variant_id="A", total_score=80, approved=False),
            CriticFeedback(variant_id="A", total_score=65, approved=False),
        ]
        orch = DebateOrchestrator(
            writer=mock_writer, critic=mock_critic, thinker=mock_thinker,
            compliance=mock_compliance, budget=mock_budget,
            config=DebateConfig(max_rounds=2, convergence_delta=3,
                                approval_threshold=90, run_tournament=False,
                                run_evolution=False),
        )

        result = (await orch.run(sample_brief, num_variants=1))[0]

        assert result.final_score == 80
        assert result.final_draft.hook == sample_draft.hook
        assert result.rounds[-1].feedback.total_score == 65

    async def test_thinking_agent_is_not_called_when_notes_do_not_feed_revision(
        self, mock_writer, mock_critic, mock_thinker,
        mock_compliance, mock_budget, sample_brief, sample_draft,
    ):
        mock_writer.execute.return_value = [sample_draft]
        mock_critic.execute.return_value = CriticFeedback(
            variant_id="A", total_score=85, approved=True,
        )
        orch = DebateOrchestrator(
            writer=mock_writer, critic=mock_critic, thinker=mock_thinker,
            compliance=mock_compliance, budget=mock_budget,
            config=DebateConfig(run_tournament=False, run_evolution=False),
        )

        await orch.run(sample_brief, num_variants=1)

        mock_thinker.execute.assert_not_awaited()

    async def test_evolution_is_freshly_scored_without_synthetic_bonus(
        self, mock_writer, mock_critic, mock_thinker,
        mock_compliance, mock_budget, sample_brief, sample_draft,
    ):
        second = sample_draft.model_copy(update={"variant_id": "B", "hook": "Hook B."})
        evolved = sample_draft.model_copy(update={"variant_id": "evolved", "hook": "Merged hook."})
        mock_writer.execute.return_value = [sample_draft, second]
        mock_writer.ensure_length.return_value = evolved
        mock_critic.execute.side_effect = [
            CriticFeedback(variant_id="A", total_score=60, approved=False),
            CriticFeedback(variant_id="B", total_score=62, approved=False),
            CriticFeedback(variant_id="evolved", total_score=58, approved=False),
        ]
        evolution = MagicMock()
        evolution.execute = AsyncMock(return_value=evolved)
        evolution._llm = _make_mock_llm(0.02)
        evolution._last_cost_usd = 0.02
        orch = DebateOrchestrator(
            writer=mock_writer, critic=mock_critic, thinker=mock_thinker,
            compliance=mock_compliance, budget=mock_budget,
            config=DebateConfig(max_rounds=1, approval_threshold=90,
                                run_tournament=False, run_evolution=True),
            evolution=evolution,
        )

        results = await orch.run(sample_brief, num_variants=2)
        evolved_result = next(r for r in results if r.variant_id == "evolved")

        assert evolved_result.final_score == 58
        assert evolved_result.approved is False
        assert evolved_result.rounds[-1].feedback.total_score == 58

    async def test_max_rounds_stop(
        self, mock_writer, mock_critic, mock_thinker,
        mock_compliance, mock_budget, sample_brief, sample_draft,
    ):
        mock_writer.execute.return_value = [sample_draft]
        mock_writer.revise.return_value = sample_draft
        # Always improve enough to avoid convergence, but never approve
        round_num = 0

        async def critic_side_effect(*args, **kwargs):
            nonlocal round_num
            round_num += 1
            return CriticFeedback(
                variant_id="A", total_score=40 + round_num * 5, approved=False,
            )

        mock_critic.execute.side_effect = critic_side_effect
        config = DebateConfig(max_rounds=3, convergence_delta=3, approval_threshold=90)
        orch = DebateOrchestrator(
            writer=mock_writer, critic=mock_critic, thinker=mock_thinker,
            compliance=mock_compliance, budget=mock_budget, config=config,
        )
        results = await orch.run(sample_brief, num_variants=1)
        assert results[0].exit_reason == "max_rounds"
        assert len(results[0].rounds) <= 3
        assert mock_writer.revise.await_count == 2

    async def test_loop_lock_detection(self):
        orch_class = DebateOrchestrator.__new__(DebateOrchestrator)
        rounds = [
            DebateRound(
                round_number=i,
                draft=ScriptDraft(variant_id="A", brief_title="T", hook="H"),
                feedback=CriticFeedback(variant_id="A", total_score=50),
                score_delta=0,
            )
            for i in range(6)
        ]
        assert orch_class._detect_loop_lock(rounds) is True

    async def test_no_loop_lock_improving(self):
        orch_class = DebateOrchestrator.__new__(DebateOrchestrator)
        rounds = [
            DebateRound(
                round_number=i,
                draft=ScriptDraft(variant_id="A", brief_title="T", hook="H"),
                feedback=CriticFeedback(variant_id="A", total_score=50 + i * 5),
                score_delta=5,
            )
            for i in range(6)
        ]
        assert orch_class._detect_loop_lock(rounds) is False
