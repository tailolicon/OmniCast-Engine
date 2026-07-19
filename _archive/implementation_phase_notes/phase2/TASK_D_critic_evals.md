# TASK_D: Critic Agent + Thinking Agent + Binary Evals

## Model: sonnet
## Estimated time: 40 minutes
## Dependencies: TASK_A (LLM Client + Base), TASK_B (Script Models)

## Overview

Three components:
1. **ThinkingAgent** — Self-critique before Critic sees the draft (private notes)
2. **CriticAgent** — Adversarial review, scores 100 points, structured output
3. **Binary Evals** — Code-based pass/fail checks (no LLM needed)

## Files

| File | Lines | Description |
|------|------:|-------------|
| `src/omnicast/agents/thinking.py` | ~80 | ThinkingAgent (self-critique) |
| `src/omnicast/agents/critic.py` | ~180 | CriticAgent (adversarial reviewer) |
| `src/omnicast/agents/evals.py` | ~120 | Binary eval functions (code, no LLM) |
| `tests/unit/test_critic.py` | ~180 | Pre-written tests |
| `tests/unit/test_evals.py` | ~130 | Pre-written tests |

## Context Files

- `src/omnicast/agents/base.py` — BaseAgent
- `src/omnicast/models/script.py` — ScriptDraft, CriticFeedback, CriticDimension
- `PROJECT_CONTEXT.md` Section 5 — Critic Scoring rubric (100 points)
- `src/omnicast/shared/errors.py` — AgentError

## Interface Definitions

### src/omnicast/agents/thinking.py

```python
"""Thinking Agent — self-critique before Critic review."""

from __future__ import annotations

import structlog

from omnicast.agents.base import BaseAgent
from omnicast.llm.client import LLMClient
from omnicast.models.script import ScriptDraft

logger = structlog.get_logger()


class ThinkingAgent(BaseAgent):
    """Internal self-critique. Output = thinking_notes (private, Critic doesn't see).

    Uses Haiku model (cheap) for fast self-review.
    """

    def __init__(self, llm: LLMClient) -> None:
        raise NotImplementedError

    @property
    def name(self) -> str:
        return "thinking"

    @property
    def system_prompt(self) -> str:
        """Prompt: find logical gaps, weak evidence, rhetorical issues."""
        raise NotImplementedError

    async def execute(self, draft: ScriptDraft) -> str:
        """
        Analyze draft and return thinking notes.

        Steps:
        1. Build prompt with draft content
        2. Call LLM (should be Haiku for cost)
        3. Return thinking notes as string

        Returns: thinking_notes string
        Raises: AgentError on failure
        """
        raise NotImplementedError
```

### src/omnicast/agents/critic.py

```python
"""Critic Agent — adversarial review with 100-point scoring."""

from __future__ import annotations

import structlog

from omnicast.agents.base import BaseAgent
from omnicast.llm.client import LLMClient
from omnicast.models.script import ScriptDraft, CriticFeedback, CriticDimension, TopicBrief
from omnicast.shared.errors import AgentError

logger = structlog.get_logger()

# Scoring rubric (from PROJECT_CONTEXT.md Section 5)
SCORING_RUBRIC = {
    "hook_quality": 25,          # First 30s hook
    "anti_ai_cliche": 20,        # No "delve", "tapestry", "realm"
    "retention_structure": 15,   # Pattern interrupts every 60-90s
    "human_editorial": 15,       # Insight AI alone can't produce
    "template_divergence": 10,   # ≥30% different from recent scripts
    "cross_channel_unique": 10,  # No cross-channel duplication
    "policy_safety": 5,          # COPPA, FTC, misleading
}

# Thresholds
HUB_THRESHOLD = 85
SPOKE_THRESHOLD = 70


class CriticAgent(BaseAgent):
    """Adversarial critic. Scores scripts on 7 dimensions, total 100 points.

    Output is structured CriticFeedback via tool_use.
    """

    def __init__(self, llm: LLMClient) -> None:
        raise NotImplementedError

    @property
    def name(self) -> str:
        return "critic"

    @property
    def system_prompt(self) -> str:
        """Hostile auditor prompt. Include scoring rubric."""
        raise NotImplementedError

    async def execute(
        self,
        draft: ScriptDraft,
        brief: TopicBrief,
        *,
        threshold: int = SPOKE_THRESHOLD,
    ) -> CriticFeedback:
        """
        Review a script draft and produce structured feedback.

        Steps:
        1. Build prompt with draft + rubric + brief context
        2. Call LLM with structured output (CriticFeedback schema)
        3. Validate total_score == sum of dimension scores
        4. Set approved = (total_score >= threshold)
        5. Log score and approval status

        Returns: CriticFeedback
        Raises: AgentError on LLM/parse failure
        """
        raise NotImplementedError

    async def compare_variants(
        self,
        variant_a: ScriptDraft,
        variant_b: ScriptDraft,
        brief: TopicBrief,
    ) -> str:
        """
        Pairwise comparison for tournament. Returns winner variant_id.

        Steps:
        1. Present both variants side-by-side
        2. Ask: "Which variant will have higher YouTube retention?"
        3. Return winning variant_id ("A" or "B")

        Raises: AgentError on failure
        """
        raise NotImplementedError
```

### src/omnicast/agents/evals.py

```python
"""Binary eval functions — code-based, no LLM needed.

Each eval is a pure function: ScriptDraft -> bool
True = pass, False = fail

Based on PROJECT_CONTEXT.md Section 12B.
"""

from __future__ import annotations

from omnicast.models.script import ScriptDraft

# Common AI cliches to detect
AI_CLICHE_LIST = [
    "delve", "tapestry", "realm", "landscape", "paradigm",
    "synergy", "holistic", "leverage", "robust", "seamless",
    "cutting-edge", "game-changer", "unlock", "empower",
    "in today's fast-paced world", "let's dive in",
    "without further ado", "buckle up",
]


def eval_hook_under_15_words(draft: ScriptDraft) -> bool:
    """Hook should be concise — under 15 words."""
    return len(draft.hook.split()) <= 15


def eval_no_ai_cliches(draft: ScriptDraft) -> bool:
    """No AI cliche phrases in the full text."""
    full_text = draft.hook + " " + " ".join(s.content for s in draft.segments)
    text_lower = full_text.lower()
    return not any(cliche.lower() in text_lower for cliche in AI_CLICHE_LIST)


def eval_has_pattern_interrupt(draft: ScriptDraft) -> bool:
    """At least 2 segments have pattern_interrupt = True."""
    count = sum(1 for s in draft.segments if s.has_pattern_interrupt)
    return count >= 2


def eval_intro_under_30s(draft: ScriptDraft) -> bool:
    """First segment (intro) should be ≤ 30 seconds."""
    if not draft.segments:
        return False
    return draft.segments[0].estimated_duration_seconds <= 30


def eval_segment_under_90s(draft: ScriptDraft) -> bool:
    """All segments should be ≤ 90 seconds."""
    return all(s.estimated_duration_seconds <= 90 for s in draft.segments)


def eval_under_target_duration(draft: ScriptDraft, max_seconds: int = 900) -> bool:
    """Total duration within target."""
    return draft.estimated_duration_seconds <= max_seconds


def eval_has_outro(draft: ScriptDraft) -> bool:
    """Script should have an outro."""
    return len(draft.outro.strip()) > 0


def eval_word_count_reasonable(draft: ScriptDraft) -> bool:
    """Word count between 800 and 3000 (5-20 min video)."""
    return 800 <= draft.word_count <= 3000


# Registry of all evals
WRITER_EVALS: dict[str, callable] = {
    "hook_under_15_words": eval_hook_under_15_words,
    "no_ai_cliches": eval_no_ai_cliches,
    "has_pattern_interrupt": eval_has_pattern_interrupt,
    "intro_under_30s": eval_intro_under_30s,
    "segment_under_90s": eval_segment_under_90s,
    "has_outro": eval_has_outro,
    "word_count_reasonable": eval_word_count_reasonable,
}


def run_binary_evals(
    draft: ScriptDraft,
    evals: dict[str, callable] | None = None,
) -> dict[str, bool]:
    """Run all binary evals on a draft. Returns {eval_name: pass/fail}."""
    if evals is None:
        evals = WRITER_EVALS
    results: dict[str, bool] = {}
    for name, fn in evals.items():
        try:
            results[name] = fn(draft)
        except Exception:
            results[name] = False
    return results
```

## DO NOT

- ❌ Do not let Critic see ThinkingAgent's notes — private to Writer
- ❌ Do not hardcode threshold in CriticAgent — pass as parameter
- ❌ Do not use LLM in evals.py — code-only, deterministic
- ❌ Do not return raw text from Critic — always CriticFeedback model
- ❌ Do not skip dimension validation (sum should ≤ 100)

## Pre-Written Tests

### tests/unit/test_critic.py

```python
"""Tests for Critic Agent and Thinking Agent."""

import pytest
from unittest.mock import AsyncMock

from omnicast.agents.critic import (
    CriticAgent, SCORING_RUBRIC, HUB_THRESHOLD, SPOKE_THRESHOLD,
)
from omnicast.agents.thinking import ThinkingAgent
from omnicast.llm.client import LLMClient, LLMResponse
from omnicast.models.script import (
    TopicBrief, ScriptDraft, ScriptSegment, CriticFeedback, CriticDimension,
)
from omnicast.models.enums import Niche, Market, TopicSource
from omnicast.shared.errors import AgentError


@pytest.fixture
def mock_llm() -> AsyncMock:
    return AsyncMock(spec=LLMClient)


@pytest.fixture
def sample_brief() -> TopicBrief:
    return TopicBrief(
        title="Investment Tips",
        niche=Niche.FINANCE,
        market=Market.US,
        source=TopicSource.GOOGLE_TRENDS,
    )


@pytest.fixture
def sample_draft() -> ScriptDraft:
    return ScriptDraft(
        variant_id="A",
        brief_title="Investment Tips",
        hook="90% of traders lose money in their first year.",
        segments=[
            ScriptSegment(index=0, heading="Intro", content="Let me explain...",
                          estimated_duration_seconds=25, has_pattern_interrupt=True),
            ScriptSegment(index=1, heading="Mistake 1", content="Overtrading is...",
                          estimated_duration_seconds=80, has_pattern_interrupt=True),
        ],
        outro="Subscribe for more.",
        word_count=1500,
        estimated_duration_seconds=600,
    )


class TestThinkingAgent:
    async def test_name(self, mock_llm):
        agent = ThinkingAgent(llm=mock_llm)
        assert agent.name == "thinking"

    async def test_execute_returns_notes(self, mock_llm, sample_draft):
        mock_llm.complete.return_value = LLMResponse(
            content="Weak transition between segments 1 and 2.",
            model="claude-haiku-4-5",
            input_tokens=200, output_tokens=50,
            cost_usd=0.0004, stop_reason="end_turn",
        )
        agent = ThinkingAgent(llm=mock_llm)
        notes = await agent.execute(sample_draft)
        assert isinstance(notes, str)
        assert len(notes) > 0

    async def test_execute_error(self, mock_llm, sample_draft):
        mock_llm.complete.side_effect = AgentError("Failed")
        agent = ThinkingAgent(llm=mock_llm)
        with pytest.raises(AgentError):
            await agent.execute(sample_draft)


class TestCriticAgent:
    async def test_name(self, mock_llm):
        critic = CriticAgent(llm=mock_llm)
        assert critic.name == "critic"

    async def test_scoring_rubric_sums_100(self):
        assert sum(SCORING_RUBRIC.values()) == 100

    async def test_execute_approved(self, mock_llm, sample_draft, sample_brief):
        feedback = CriticFeedback(
            variant_id="A",
            total_score=82,
            dimensions=[
                CriticDimension(name="hook_quality", score=22, max_score=25),
                CriticDimension(name="anti_ai_cliche", score=18, max_score=20),
                CriticDimension(name="retention_structure", score=12, max_score=15),
                CriticDimension(name="human_editorial", score=12, max_score=15),
                CriticDimension(name="template_divergence", score=8, max_score=10),
                CriticDimension(name="cross_channel_unique", score=7, max_score=10),
                CriticDimension(name="policy_safety", score=3, max_score=5),
            ],
            approved=True,
        )
        mock_llm.complete_structured.return_value = (
            LLMResponse(
                content="{}", model="claude-sonnet-4-6",
                input_tokens=800, output_tokens=200,
                cost_usd=0.005, stop_reason="end_turn",
            ),
            feedback,
        )
        critic = CriticAgent(llm=mock_llm)
        result = await critic.execute(sample_draft, sample_brief, threshold=SPOKE_THRESHOLD)
        assert isinstance(result, CriticFeedback)
        assert result.approved is True
        assert result.total_score == 82

    async def test_execute_rejected(self, mock_llm, sample_draft, sample_brief):
        feedback = CriticFeedback(
            variant_id="A",
            total_score=55,
            approved=False,
            rejection_reasons=["Generic hook"],
            specific_fixes=["Use a specific statistic"],
        )
        mock_llm.complete_structured.return_value = (
            LLMResponse(
                content="{}", model="claude-sonnet-4-6",
                input_tokens=800, output_tokens=200,
                cost_usd=0.005, stop_reason="end_turn",
            ),
            feedback,
        )
        critic = CriticAgent(llm=mock_llm)
        result = await critic.execute(sample_draft, sample_brief)
        assert result.approved is False
        assert len(result.rejection_reasons) > 0

    async def test_hub_threshold_higher(self):
        assert HUB_THRESHOLD > SPOKE_THRESHOLD
        assert HUB_THRESHOLD == 85
        assert SPOKE_THRESHOLD == 70

    async def test_compare_variants(self, mock_llm, sample_draft, sample_brief):
        draft_b = ScriptDraft(
            variant_id="B", brief_title="Test", hook="Alternative hook.",
            segments=[], word_count=1200, estimated_duration_seconds=500,
        )
        mock_llm.complete.return_value = LLMResponse(
            content="B",
            model="claude-sonnet-4-6",
            input_tokens=1000, output_tokens=10,
            cost_usd=0.003, stop_reason="end_turn",
        )
        critic = CriticAgent(llm=mock_llm)
        winner = await critic.compare_variants(sample_draft, draft_b, sample_brief)
        assert winner in ("A", "B")

    async def test_error_raises_agent_error(self, mock_llm, sample_draft, sample_brief):
        mock_llm.complete_structured.side_effect = AgentError("Parse failed")
        critic = CriticAgent(llm=mock_llm)
        with pytest.raises(AgentError):
            await critic.execute(sample_draft, sample_brief)
```

### tests/unit/test_evals.py

```python
"""Tests for binary eval functions."""

import pytest

from omnicast.agents.evals import (
    eval_hook_under_15_words,
    eval_no_ai_cliches,
    eval_has_pattern_interrupt,
    eval_intro_under_30s,
    eval_segment_under_90s,
    eval_has_outro,
    eval_word_count_reasonable,
    run_binary_evals,
    WRITER_EVALS,
    AI_CLICHE_LIST,
)
from omnicast.models.script import ScriptDraft, ScriptSegment


@pytest.fixture
def good_draft() -> ScriptDraft:
    """Draft that passes all evals."""
    return ScriptDraft(
        variant_id="A",
        brief_title="Test",
        hook="90% of traders lose money.",  # 6 words
        segments=[
            ScriptSegment(
                index=0, heading="Intro", content="Welcome to this video.",
                estimated_duration_seconds=25, has_pattern_interrupt=True,
            ),
            ScriptSegment(
                index=1, heading="Point 1", content="First mistake is overtrading.",
                estimated_duration_seconds=80, has_pattern_interrupt=True,
            ),
            ScriptSegment(
                index=2, heading="Point 2", content="Second mistake is no stop loss.",
                estimated_duration_seconds=70, has_pattern_interrupt=False,
            ),
        ],
        outro="Thanks for watching. Subscribe!",
        word_count=1500,
        estimated_duration_seconds=600,
    )


@pytest.fixture
def bad_draft() -> ScriptDraft:
    """Draft that fails multiple evals."""
    return ScriptDraft(
        variant_id="B",
        brief_title="Test",
        hook="In today's fast-paced world of investing there are many things you need to know about making money",
        segments=[
            ScriptSegment(
                index=0, heading="Intro",
                content="Let's delve into the tapestry of investing.",
                estimated_duration_seconds=45,  # > 30s
                has_pattern_interrupt=False,
            ),
            ScriptSegment(
                index=1, heading="Main",
                content="This is a very long segment with lots of content.",
                estimated_duration_seconds=120,  # > 90s
                has_pattern_interrupt=False,
            ),
        ],
        outro="",  # empty outro
        word_count=5000,  # > 3000
        estimated_duration_seconds=1200,
    )


class TestHookLength:
    def test_short_hook_passes(self, good_draft):
        assert eval_hook_under_15_words(good_draft) is True

    def test_long_hook_fails(self, bad_draft):
        assert eval_hook_under_15_words(bad_draft) is False


class TestAICliches:
    def test_clean_text_passes(self, good_draft):
        assert eval_no_ai_cliches(good_draft) is True

    def test_cliche_text_fails(self, bad_draft):
        assert eval_no_ai_cliches(bad_draft) is False

    def test_cliche_list_not_empty(self):
        assert len(AI_CLICHE_LIST) > 10


class TestPatternInterrupt:
    def test_enough_interrupts(self, good_draft):
        assert eval_has_pattern_interrupt(good_draft) is True

    def test_no_interrupts(self, bad_draft):
        assert eval_has_pattern_interrupt(bad_draft) is False


class TestIntroDuration:
    def test_short_intro(self, good_draft):
        assert eval_intro_under_30s(good_draft) is True

    def test_long_intro(self, bad_draft):
        assert eval_intro_under_30s(bad_draft) is False

    def test_no_segments(self):
        draft = ScriptDraft(variant_id="X", brief_title="T", hook="H")
        assert eval_intro_under_30s(draft) is False


class TestSegmentDuration:
    def test_all_under_90(self, good_draft):
        assert eval_segment_under_90s(good_draft) is True

    def test_segment_over_90(self, bad_draft):
        assert eval_segment_under_90s(bad_draft) is False


class TestOutro:
    def test_has_outro(self, good_draft):
        assert eval_has_outro(good_draft) is True

    def test_empty_outro(self, bad_draft):
        assert eval_has_outro(bad_draft) is False


class TestWordCount:
    def test_reasonable_count(self, good_draft):
        assert eval_word_count_reasonable(good_draft) is True

    def test_too_many_words(self, bad_draft):
        assert eval_word_count_reasonable(bad_draft) is False

    def test_too_few_words(self):
        draft = ScriptDraft(variant_id="X", brief_title="T", hook="H", word_count=100)
        assert eval_word_count_reasonable(draft) is False


class TestRunBinaryEvals:
    def test_all_pass(self, good_draft):
        results = run_binary_evals(good_draft)
        assert all(results.values()), f"Failed evals: {[k for k, v in results.items() if not v]}"

    def test_mixed_results(self, bad_draft):
        results = run_binary_evals(bad_draft)
        assert not all(results.values())  # some should fail
        assert isinstance(results, dict)
        assert set(results.keys()) == set(WRITER_EVALS.keys())

    def test_custom_evals(self, good_draft):
        custom = {"hook_check": eval_hook_under_15_words}
        results = run_binary_evals(good_draft, evals=custom)
        assert "hook_check" in results
        assert len(results) == 1
```

## Verify

```bash
uv run pytest tests/unit/test_critic.py tests/unit/test_evals.py -v
uv run ruff check src/omnicast/agents/critic.py src/omnicast/agents/thinking.py src/omnicast/agents/evals.py
uv run pyright src/omnicast/agents/critic.py src/omnicast/agents/thinking.py src/omnicast/agents/evals.py
```
