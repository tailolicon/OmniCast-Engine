# TASK_C: Writer Agent

## Model: sonnet
## Estimated time: 35 minutes
## Dependencies: TASK_A (LLM Client + Base), TASK_B (Script Models + KB)

## Overview

Writer Agent generates N=3 script variants from a TopicBrief.
Each variant uses a different angle (storytelling, data-driven, contrarian).
Writer revises based on CriticFeedback in the debate loop.

## Files

| File | Lines | Description |
|------|------:|-------------|
| `src/omnicast/agents/writer.py` | ~180 | Writer Agent |
| `tests/unit/test_writer.py` | ~180 | Pre-written tests |

## Context Files

- `src/omnicast/agents/base.py` — BaseAgent
- `src/omnicast/llm/client.py` — LLMClient, LLMResponse
- `src/omnicast/models/script.py` — TopicBrief, ScriptDraft, ScriptSegment, CriticFeedback
- `src/omnicast/models/enums.py` — Niche
- `src/omnicast/kb/patterns.py` — PatternStore
- `src/omnicast/shared/errors.py` — AgentError

## Interface Definition

```python
"""Writer Agent — generates script variants from TopicBrief."""

from __future__ import annotations

import structlog

from omnicast.agents.base import BaseAgent
from omnicast.llm.client import LLMClient
from omnicast.models.script import TopicBrief, ScriptDraft, CriticFeedback
from omnicast.kb.patterns import PatternStore
from omnicast.shared.errors import AgentError

logger = structlog.get_logger()

ANGLES = ["storytelling", "data_driven", "contrarian"]


class WriterAgent(BaseAgent):
    """Generates script variants and revises based on critic feedback.

    Two modes:
    - generate(): Create N=3 initial variants from brief
    - revise(): Revise a single variant based on CriticFeedback
    """

    def __init__(
        self,
        llm: LLMClient,
        pattern_store: PatternStore | None = None,
    ) -> None:
        """
        Args:
            llm: LLM client for API calls
            pattern_store: Optional KB for injecting learned patterns into prompts
        """
        raise NotImplementedError

    @property
    def name(self) -> str:
        return "writer"

    @property
    def system_prompt(self) -> str:
        """System prompt for script generation.
        Includes anti-AI-cliche instructions, structure guidelines, etc."""
        raise NotImplementedError

    async def execute(
        self,
        brief: TopicBrief,
        *,
        num_variants: int = 3,
    ) -> list[ScriptDraft]:
        """
        Generate script variants from brief.

        Steps:
        1. If pattern_store available, fetch relevant patterns for brief
        2. Build prompt with brief + patterns + lessons
        3. For each angle in ANGLES[:num_variants]:
           a. Call LLM with angle-specific instructions
           b. Parse response into ScriptDraft
           c. Calculate word_count and estimated_duration
        4. Return list of ScriptDraft variants

        Raises: AgentError on LLM/parse failure
        """
        raise NotImplementedError

    async def revise(
        self,
        draft: ScriptDraft,
        feedback: CriticFeedback,
        brief: TopicBrief,
    ) -> ScriptDraft:
        """
        Revise a draft based on critic feedback.

        Steps:
        1. Build revision prompt with:
           - Original draft
           - Critic feedback (rejection_reasons, specific_fixes)
           - Brief context
        2. Call LLM for revision
        3. Parse into new ScriptDraft (version incremented)
        4. Preserve variant_id from original

        Raises: AgentError on failure
        """
        raise NotImplementedError

    def _build_generation_prompt(
        self,
        brief: TopicBrief,
        angle: str,
        patterns: list[str],
    ) -> str:
        """Build the user prompt for variant generation."""
        raise NotImplementedError

    def _build_revision_prompt(
        self,
        draft: ScriptDraft,
        feedback: CriticFeedback,
        brief: TopicBrief,
    ) -> str:
        """Build the user prompt for revision."""
        raise NotImplementedError

    def _parse_draft(self, content: str, variant_id: str, brief_title: str) -> ScriptDraft:
        """Parse LLM text output into ScriptDraft model.
        Raises: AgentError if parsing fails."""
        raise NotImplementedError
```

## DO NOT

- ❌ Do not call Critic from within Writer — separation of concerns
- ❌ Do not hardcode system prompt text longer than 50 lines — break into constants
- ❌ Do not skip pattern injection when pattern_store is available
- ❌ Do not modify the brief — it's frozen
- ❌ Do not generate more than num_variants

## Pre-Written Tests

### tests/unit/test_writer.py

```python
"""Tests for Writer Agent."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from omnicast.agents.writer import WriterAgent, ANGLES
from omnicast.llm.client import LLMClient, LLMResponse
from omnicast.models.script import TopicBrief, ScriptDraft, CriticFeedback, CriticDimension
from omnicast.models.enums import Niche, Market, TopicSource
from omnicast.kb.patterns import PatternStore
from omnicast.shared.errors import AgentError


@pytest.fixture
def mock_llm() -> AsyncMock:
    llm = AsyncMock(spec=LLMClient)
    llm.total_cost = 0.01
    return llm


@pytest.fixture
def mock_pattern_store() -> AsyncMock:
    store = AsyncMock(spec=PatternStore)
    store.get_patterns_for_brief.return_value = []
    return store


@pytest.fixture
def sample_brief() -> TopicBrief:
    return TopicBrief(
        title="5 Investment Mistakes to Avoid",
        niche=Niche.FINANCE,
        market=Market.US,
        source=TopicSource.GOOGLE_TRENDS,
        angle="",
        key_points=["Overtrading", "No stop loss", "FOMO"],
        target_duration_min=10,
    )


@pytest.fixture
def sample_draft() -> ScriptDraft:
    return ScriptDraft(
        variant_id="A",
        brief_title="5 Investment Mistakes",
        hook="Did you know 90% of retail traders lose money?",
        segments=[],
        word_count=1500,
        estimated_duration_seconds=600,
        version=1,
    )


@pytest.fixture
def sample_feedback() -> CriticFeedback:
    return CriticFeedback(
        variant_id="A",
        total_score=65,
        approved=False,
        rejection_reasons=["Hook too generic"],
        specific_fixes=["Replace with a specific statistic"],
        round_number=1,
    )


def _make_llm_response(content: str) -> LLMResponse:
    return LLMResponse(
        content=content,
        model="claude-sonnet-4-6",
        input_tokens=500,
        output_tokens=1000,
        cost_usd=0.0165,
        stop_reason="end_turn",
    )


class TestWriterAgent:
    async def test_name(self, mock_llm):
        writer = WriterAgent(llm=mock_llm)
        assert writer.name == "writer"

    async def test_system_prompt_not_empty(self, mock_llm):
        writer = WriterAgent(llm=mock_llm)
        assert len(writer.system_prompt) > 50

    async def test_generate_returns_variants(self, mock_llm, sample_brief):
        # Mock LLM to return parseable script content
        mock_llm.complete.return_value = _make_llm_response(
            "HOOK: A bold statement.\n"
            "SEGMENT 1: Introduction\n"
            "Content here about investment mistakes.\n"
            "SEGMENT 2: Main Point\n"
            "More content.\n"
            "OUTRO: Thanks for watching."
        )
        writer = WriterAgent(llm=mock_llm)
        variants = await writer.execute(sample_brief, num_variants=3)
        assert len(variants) == 3
        assert all(isinstance(v, ScriptDraft) for v in variants)
        # Each variant should have a different variant_id
        ids = [v.variant_id for v in variants]
        assert len(set(ids)) == 3

    async def test_generate_single_variant(self, mock_llm, sample_brief):
        mock_llm.complete.return_value = _make_llm_response("HOOK: Test.\nOUTRO: End.")
        writer = WriterAgent(llm=mock_llm)
        variants = await writer.execute(sample_brief, num_variants=1)
        assert len(variants) == 1

    async def test_generate_with_patterns(
        self, mock_llm, mock_pattern_store, sample_brief
    ):
        from omnicast.models.script import EngagementPattern
        from datetime import datetime, timezone, timedelta

        mock_pattern_store.get_patterns_for_brief.return_value = [
            EngagementPattern(
                pattern_id="EP-001",
                niche=Niche.FINANCE,
                market=Market.US,
                finding="Numbered lists improve retention",
                confidence=0.8,
                sample_size=15,
                decay_date=datetime.now(timezone.utc) + timedelta(days=90),
            )
        ]
        mock_llm.complete.return_value = _make_llm_response("HOOK: Test.\nOUTRO: End.")
        writer = WriterAgent(llm=mock_llm, pattern_store=mock_pattern_store)
        variants = await writer.execute(sample_brief, num_variants=1)
        assert len(variants) == 1
        mock_pattern_store.get_patterns_for_brief.assert_called_once()

    async def test_revise_increments_version(
        self, mock_llm, sample_draft, sample_feedback, sample_brief
    ):
        mock_llm.complete.return_value = _make_llm_response(
            "HOOK: A shocking new statistic.\nOUTRO: End."
        )
        writer = WriterAgent(llm=mock_llm)
        revised = await writer.revise(sample_draft, sample_feedback, sample_brief)
        assert isinstance(revised, ScriptDraft)
        assert revised.version == sample_draft.version + 1
        assert revised.variant_id == "A"  # preserved

    async def test_revise_uses_feedback(
        self, mock_llm, sample_draft, sample_feedback, sample_brief
    ):
        mock_llm.complete.return_value = _make_llm_response("HOOK: Fixed.\nOUTRO: End.")
        writer = WriterAgent(llm=mock_llm)
        await writer.revise(sample_draft, sample_feedback, sample_brief)
        # Verify feedback was included in the prompt
        call_args = mock_llm.complete.call_args
        messages = call_args.kwargs["messages"]
        user_msg = messages[0]["content"]
        assert "Hook too generic" in user_msg or "specific" in user_msg.lower()

    async def test_llm_error_raises_agent_error(self, mock_llm, sample_brief):
        mock_llm.complete.side_effect = AgentError("API down")
        writer = WriterAgent(llm=mock_llm)
        with pytest.raises(AgentError):
            await writer.execute(sample_brief)

    async def test_angles_constant(self):
        assert len(ANGLES) == 3
        assert "storytelling" in ANGLES
        assert "data_driven" in ANGLES
        assert "contrarian" in ANGLES
```

## Verify

```bash
uv run pytest tests/unit/test_writer.py -v
uv run ruff check src/omnicast/agents/writer.py
uv run pyright src/omnicast/agents/writer.py
```
