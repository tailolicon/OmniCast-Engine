# TASK_E: Debate Orchestrator + Tournament + Evolution

## Model: sonnet
## Estimated time: 50 minutes
## Dependencies: TASK_C (Writer), TASK_D (Critic + Evals), TASK_F (Compliance + Budget)

## Overview

The orchestrator ties everything together:
1. **DebateOrchestrator** — runs the Writer ↔ Critic debate loop with convergence detection
2. **Tournament** — Elo-based pairwise ranking of approved variants
3. **EvolutionAgent** — combines best elements from variants (Hub channels only)

This is the last task — depends on all others.

## Files

| File | Lines | Description |
|------|------:|-------------|
| `src/omnicast/agents/orchestrator.py` | ~200 | Debate loop with convergence |
| `src/omnicast/agents/tournament.py` | ~100 | Elo rating + tournament |
| `src/omnicast/agents/evolution.py` | ~80 | Combine best elements |
| `tests/unit/test_orchestrator.py` | ~200 | Pre-written tests |
| `tests/unit/test_tournament.py` | ~120 | Pre-written tests |

## Context Files

- `src/omnicast/agents/writer.py` — WriterAgent
- `src/omnicast/agents/critic.py` — CriticAgent, HUB_THRESHOLD, SPOKE_THRESHOLD
- `src/omnicast/agents/thinking.py` — ThinkingAgent
- `src/omnicast/agents/evals.py` — run_binary_evals
- `src/omnicast/agents/compliance.py` — ComplianceChecker
- `src/omnicast/services/budget.py` — BudgetManager
- `src/omnicast/models/script.py` — all script models
- `PROJECT_CONTEXT.md` Section 5 — Tournament architecture

## Interface Definitions

### src/omnicast/agents/orchestrator.py

```python
"""Debate Orchestrator — manages Writer ↔ Critic loop with convergence detection."""

from __future__ import annotations

from dataclasses import dataclass, field

import structlog

from omnicast.agents.writer import WriterAgent
from omnicast.agents.critic import CriticAgent
from omnicast.agents.thinking import ThinkingAgent
from omnicast.agents.evals import run_binary_evals
from omnicast.agents.compliance import ComplianceChecker
from omnicast.services.budget import BudgetManager
from omnicast.models.script import (
    TopicBrief, ScriptDraft, CriticFeedback, DebateRound,
)
from omnicast.shared.errors import AgentError

logger = structlog.get_logger()


@dataclass(frozen=True)
class DebateConfig:
    """Configuration for debate loop."""
    max_rounds: int = 7
    convergence_threshold: int = 3     # min score improvement to continue
    budget_per_variant_usd: float = 0.50
    approval_threshold: int = 70       # Spoke default


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
    exit_reason: str = ""  # "approved" | "converged" | "max_rounds" | "budget_stop"


class DebateOrchestrator:
    """Runs the full debate pipeline for all variants.

    Flow per variant:
    1. ThinkingAgent self-critique
    2. CriticAgent review
    3. If not approved and not converged: Writer revises → loop back to 1
    4. Run binary evals on final draft
    5. If approved: run ComplianceChecker
    """

    def __init__(
        self,
        writer: WriterAgent,
        critic: CriticAgent,
        thinker: ThinkingAgent,
        compliance: ComplianceChecker,
        budget: BudgetManager,
        config: DebateConfig | None = None,
    ) -> None:
        raise NotImplementedError

    async def run(
        self,
        brief: TopicBrief,
        *,
        num_variants: int = 3,
    ) -> list[DebateResult]:
        """
        Generate variants and run debate loop on each.

        Steps:
        1. Writer generates N variants
        2. For each variant, run _debate_variant()
        3. Return list of DebateResult (sorted by final_score desc)

        Raises: AgentError if ALL variants fail
        """
        raise NotImplementedError

    async def _debate_variant(
        self,
        draft: ScriptDraft,
        brief: TopicBrief,
    ) -> DebateResult:
        """
        Run debate loop for single variant until termination.

        Termination conditions:
        1. Score >= threshold → APPROVED
        2. Score improvement < convergence_threshold → CONVERGED
        3. Rounds > max_rounds → HARD STOP
        4. Cost > budget_per_variant → BUDGET STOP

        Each round:
        1. ThinkingAgent produces notes
        2. Attach notes to draft
        3. CriticAgent scores
        4. Check termination
        5. If continue: Writer revises
        """
        raise NotImplementedError

    def _detect_loop_lock(
        self,
        rounds: list[DebateRound],
    ) -> bool:
        """
        Detect loop-lock: rounds >= 5, max_score < 60, trend flat.
        Returns True if loop-lock detected.
        """
        raise NotImplementedError
```

### src/omnicast/agents/tournament.py

```python
"""Elo-based tournament ranking for script variants."""

from __future__ import annotations

from dataclasses import dataclass

import structlog

from omnicast.agents.critic import CriticAgent
from omnicast.models.script import (
    ScriptDraft, TopicBrief, TournamentMatch, EloRating,
)
from omnicast.shared.errors import AgentError

logger = structlog.get_logger()

K_FACTOR = 32  # Elo K-factor


def calculate_elo(
    winner_rating: float,
    loser_rating: float,
    k: int = K_FACTOR,
) -> tuple[float, float]:
    """
    Calculate new Elo ratings after a match.

    Returns: (new_winner_rating, new_loser_rating)
    """
    raise NotImplementedError


class Tournament:
    """Run pairwise tournament between script variants."""

    def __init__(self, critic: CriticAgent) -> None:
        raise NotImplementedError

    async def run(
        self,
        variants: list[ScriptDraft],
        brief: TopicBrief,
    ) -> tuple[list[EloRating], list[TournamentMatch]]:
        """
        Run round-robin tournament.

        Steps:
        1. Initialize Elo rating 1000 for each variant
        2. For each pair (A, B):
           a. Critic compares A vs B
           b. Update Elo ratings
           c. Record TournamentMatch
        3. Sort ratings descending
        4. Return (ratings, matches)

        Raises: AgentError if < 2 variants
        """
        raise NotImplementedError

    def get_winner(self, ratings: list[EloRating]) -> str:
        """Return variant_id with highest Elo."""
        raise NotImplementedError
```

### src/omnicast/agents/evolution.py

```python
"""Evolution Agent — combine best elements from variants (Hub only)."""

from __future__ import annotations

import structlog

from omnicast.agents.base import BaseAgent
from omnicast.llm.client import LLMClient
from omnicast.models.script import ScriptDraft, TopicBrief
from omnicast.shared.errors import AgentError

logger = structlog.get_logger()


class EvolutionAgent(BaseAgent):
    """Combine best elements from multiple variants into one superior draft.

    Only used for Hub channels (high quality requirement).
    """

    def __init__(self, llm: LLMClient) -> None:
        raise NotImplementedError

    @property
    def name(self) -> str:
        return "evolution"

    @property
    def system_prompt(self) -> str:
        """Prompt: extract best hook, structure, data from variants and merge."""
        raise NotImplementedError

    async def execute(
        self,
        variants: list[ScriptDraft],
        brief: TopicBrief,
        *,
        winner_id: str | None = None,
    ) -> ScriptDraft:
        """
        Combine best elements from variants.

        Steps:
        1. Present all variants with their strengths
        2. Instruct LLM to merge best hook + structure + data
        3. Parse into new ScriptDraft (variant_id = "evolved")

        Args:
            variants: All debate-loop variants
            brief: Original brief
            winner_id: Tournament winner (gets priority)

        Returns: Evolved ScriptDraft
        Raises: AgentError on failure
        """
        raise NotImplementedError
```

## DO NOT

- ❌ Do not run tournament with < 2 variants — raise AgentError
- ❌ Do not skip binary evals after debate loop — always run
- ❌ Do not use Evolution on Spoke channels — Hub only
- ❌ Do not ignore budget_per_variant — must stop when exceeded
- ❌ Do not mutate DebateConfig — it's frozen
- ❌ Do not continue debate if loop-lock detected — log warning and exit

## Pre-Written Tests

### tests/unit/test_orchestrator.py

```python
"""Tests for Debate Orchestrator."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
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


@pytest.fixture
def mock_writer() -> AsyncMock:
    writer = AsyncMock(spec=WriterAgent)
    writer.name = "writer"
    writer.cost = 0.01
    return writer


@pytest.fixture
def mock_critic() -> AsyncMock:
    critic = AsyncMock(spec=CriticAgent)
    critic.name = "critic"
    critic.cost = 0.005
    return critic


@pytest.fixture
def mock_thinker() -> AsyncMock:
    thinker = AsyncMock(spec=ThinkingAgent)
    thinker.execute.return_value = "Notes: transition weak."
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
    budget.record_spend = AsyncMock()
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
        assert config.convergence_threshold == 3
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
        config = DebateConfig(max_rounds=5, convergence_threshold=3, approval_threshold=70)
        orch = DebateOrchestrator(
            writer=mock_writer, critic=mock_critic, thinker=mock_thinker,
            compliance=mock_compliance, budget=mock_budget, config=config,
        )
        results = await orch.run(sample_brief, num_variants=1)
        assert results[0].converged is True
        assert results[0].exit_reason == "converged"

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
        config = DebateConfig(max_rounds=3, convergence_threshold=3, approval_threshold=90)
        orch = DebateOrchestrator(
            writer=mock_writer, critic=mock_critic, thinker=mock_thinker,
            compliance=mock_compliance, budget=mock_budget, config=config,
        )
        results = await orch.run(sample_brief, num_variants=1)
        assert results[0].exit_reason == "max_rounds"
        assert len(results[0].rounds) <= 3

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
```

### tests/unit/test_tournament.py

```python
"""Tests for Tournament and Elo rating."""

import pytest
from unittest.mock import AsyncMock

from omnicast.agents.tournament import Tournament, calculate_elo, K_FACTOR
from omnicast.agents.critic import CriticAgent
from omnicast.models.script import (
    ScriptDraft, TopicBrief, TournamentMatch, EloRating,
)
from omnicast.models.enums import Niche, Market, TopicSource
from omnicast.shared.errors import AgentError


class TestCalculateElo:
    def test_equal_ratings(self):
        new_w, new_l = calculate_elo(1000, 1000)
        assert new_w > 1000
        assert new_l < 1000
        assert new_w + new_l == pytest.approx(2000, abs=0.01)  # zero-sum

    def test_underdog_wins(self):
        new_w, new_l = calculate_elo(800, 1200)
        # Underdog wins more than expected
        gain = new_w - 800
        assert gain > K_FACTOR / 2  # gains more than half K

    def test_favorite_wins(self):
        new_w, new_l = calculate_elo(1200, 800)
        gain = new_w - 1200
        assert gain < K_FACTOR / 2  # gains less than half K

    def test_k_factor_applied(self):
        new_w, _ = calculate_elo(1000, 1000, k=16)
        assert new_w == pytest.approx(1008, abs=0.1)  # K/2 for equal ratings


class TestTournament:
    @pytest.fixture
    def mock_critic(self) -> AsyncMock:
        return AsyncMock(spec=CriticAgent)

    @pytest.fixture
    def variants(self) -> list[ScriptDraft]:
        return [
            ScriptDraft(variant_id="A", brief_title="T", hook="Hook A",
                        word_count=1500, estimated_duration_seconds=600),
            ScriptDraft(variant_id="B", brief_title="T", hook="Hook B",
                        word_count=1400, estimated_duration_seconds=550),
            ScriptDraft(variant_id="C", brief_title="T", hook="Hook C",
                        word_count=1600, estimated_duration_seconds=650),
        ]

    @pytest.fixture
    def brief(self) -> TopicBrief:
        return TopicBrief(
            title="Test", niche=Niche.TECH, market=Market.US,
            source=TopicSource.MANUAL,
        )

    async def test_run_round_robin(self, mock_critic, variants, brief):
        # A beats B, B beats C, A beats C
        mock_critic.compare_variants.side_effect = ["A", "B", "A"]
        tournament = Tournament(critic=mock_critic)
        ratings, matches = await tournament.run(variants, brief)
        assert len(ratings) == 3
        assert len(matches) == 3  # 3 choose 2 pairs
        assert all(isinstance(r, EloRating) for r in ratings)
        assert all(isinstance(m, TournamentMatch) for m in matches)

    async def test_winner_has_highest_elo(self, mock_critic, variants, brief):
        mock_critic.compare_variants.side_effect = ["A", "A", "B"]
        tournament = Tournament(critic=mock_critic)
        ratings, _ = await tournament.run(variants, brief)
        winner = tournament.get_winner(ratings)
        assert winner == "A"  # A won 2 matches

    async def test_too_few_variants(self, mock_critic, brief):
        single = [ScriptDraft(variant_id="A", brief_title="T", hook="H")]
        tournament = Tournament(critic=mock_critic)
        with pytest.raises(AgentError, match="at least 2"):
            await tournament.run(single, brief)

    async def test_ratings_sorted_descending(self, mock_critic, variants, brief):
        mock_critic.compare_variants.side_effect = ["B", "C", "C"]
        tournament = Tournament(critic=mock_critic)
        ratings, _ = await tournament.run(variants, brief)
        assert ratings[0].rating >= ratings[1].rating >= ratings[2].rating

    async def test_matches_record_reason(self, mock_critic, variants, brief):
        mock_critic.compare_variants.return_value = "A"
        tournament = Tournament(critic=mock_critic)
        _, matches = await tournament.run(variants[:2], brief)
        assert len(matches) == 1
        assert matches[0].winner == "A"
```

## Verify

```bash
uv run pytest tests/unit/test_orchestrator.py tests/unit/test_tournament.py -v
uv run ruff check src/omnicast/agents/orchestrator.py src/omnicast/agents/tournament.py src/omnicast/agents/evolution.py
uv run pyright src/omnicast/agents/orchestrator.py src/omnicast/agents/tournament.py src/omnicast/agents/evolution.py
```
