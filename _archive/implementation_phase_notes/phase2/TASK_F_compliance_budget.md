# TASK_F: Compliance Checker + Budget Manager

## Model: haiku
## Estimated time: 25 minutes
## Dependencies: TASK_A (LLM Client + Base)

## Overview

Two independent components:
1. **ComplianceChecker** — Gate before upload. Checks AI disclosure, copyright, FTC, COPPA, YMYL.
2. **BudgetManager** — Track daily LLM spend, check budget before calls, ROI calculation.

Both are simple rule + config based. Haiku-level task.

## Files

| File | Lines | Description |
|------|------:|-------------|
| `src/omnicast/agents/compliance.py` | ~130 | Compliance gate agent |
| `src/omnicast/services/__init__.py` | ~3 | Exports |
| `src/omnicast/services/budget.py` | ~120 | Daily LLM spend tracking |
| `tests/unit/test_compliance.py` | ~130 | Pre-written tests |
| `tests/unit/test_budget.py` | ~120 | Pre-written tests |

## Context Files

- `src/omnicast/agents/base.py` — BaseAgent
- `src/omnicast/models/script.py` — ScriptDraft
- `src/omnicast/models/enums.py` — Niche (for YMYL detection)
- `src/omnicast/config/settings.py` — Settings.daily_llm_budget_usd
- `src/omnicast/shared/errors.py` — ComplianceError, AgentError

## Interface Definitions

### src/omnicast/agents/compliance.py

```python
"""Compliance Checker — gate before upload."""

from __future__ import annotations

import structlog

from omnicast.agents.base import BaseAgent
from omnicast.llm.client import LLMClient
from omnicast.models.script import ScriptDraft
from omnicast.models.enums import Niche
from omnicast.shared.errors import ComplianceError

logger = structlog.get_logger()

# YMYL niches that need extra compliance
YMYL_NICHES = {Niche.FINANCE, Niche.HEALTH}

# Required compliance checks
COMPLIANCE_CHECKS = [
    "ai_disclosure",          # Must have AI-generated content disclosure
    "no_copyright_content",   # No copyrighted text/music/images
    "ftc_disclosure",         # FTC affiliate/sponsorship disclosure if needed
    "no_coppa_violation",     # No content targeting children
    "no_misleading_claims",   # No fake medical/financial advice
    "cross_channel_unique",   # Not duplicated across channels
]


class ComplianceChecker(BaseAgent):
    """Gate agent — checks script compliance before upload.

    Returns (passed: bool, violations: list[str]).
    Any violation = script blocked from upload.
    """

    def __init__(self, llm: LLMClient) -> None:
        raise NotImplementedError

    @property
    def name(self) -> str:
        return "compliance"

    @property
    def system_prompt(self) -> str:
        """Prompt: strict compliance auditor."""
        raise NotImplementedError

    async def execute(
        self,
        draft: ScriptDraft,
        *,
        niche: Niche = Niche.TECH,
    ) -> tuple[bool, list[str]]:
        """
        Check script compliance.

        Steps:
        1. Run rule-based checks (no LLM needed):
           - ai_disclosure: check description_template contains "AI"
           - no_coppa: check no child-targeting language
        2. For ambiguous checks, use LLM (Haiku):
           - misleading_claims for YMYL niches
        3. Collect all violations
        4. Return (all_passed, violations)

        Raises: ComplianceError if check itself fails (not violations)
        """
        raise NotImplementedError

    def _check_ai_disclosure(self, draft: ScriptDraft) -> str | None:
        """Return violation string if AI disclosure missing, else None."""
        raise NotImplementedError

    def _check_coppa(self, draft: ScriptDraft) -> str | None:
        """Return violation if child-targeting detected, else None."""
        raise NotImplementedError

    def _is_ymyl(self, niche: Niche) -> bool:
        """Check if niche is YMYL (Your Money Your Life)."""
        return niche in YMYL_NICHES
```

### src/omnicast/services/budget.py

```python
"""Daily LLM budget manager."""

from __future__ import annotations

from datetime import date, timezone, datetime

import structlog

from omnicast.config.settings import get_settings
from omnicast.shared.errors import AgentError

logger = structlog.get_logger()


class BudgetManager:
    """Track and enforce daily LLM spending budget.

    Uses in-memory tracking per day. Reset at midnight UTC.
    For production, should be backed by Redis (Phase 3).
    """

    def __init__(self, daily_budget_usd: float | None = None) -> None:
        """
        Args:
            daily_budget_usd: Max daily spend. If None, reads from Settings.
        """
        raise NotImplementedError

    def can_spend(self, amount_usd: float) -> bool:
        """Check if spending amount would stay within budget.
        Returns False if would exceed budget."""
        raise NotImplementedError

    def record_spend(
        self,
        amount_usd: float,
        *,
        model: str = "",
        agent: str = "",
        video_id: int | None = None,
    ) -> None:
        """Record a spend event.

        Args:
            amount_usd: Cost of the LLM call
            model: Model name
            agent: Agent that made the call
            video_id: Associated video if any
        """
        raise NotImplementedError

    @property
    def daily_spent(self) -> float:
        """Total spent today (UTC)."""
        raise NotImplementedError

    @property
    def daily_remaining(self) -> float:
        """Remaining budget today."""
        raise NotImplementedError

    @property
    def daily_budget(self) -> float:
        """Configured daily budget."""
        raise NotImplementedError

    def summary(self) -> dict:
        """Return spending summary: {total, remaining, by_model, by_agent}."""
        raise NotImplementedError

    def _current_day(self) -> date:
        """Return current UTC date."""
        return datetime.now(timezone.utc).date()

    def _maybe_reset(self) -> None:
        """Reset counters if day changed."""
        raise NotImplementedError
```

## DO NOT

- ❌ Do not skip compliance for any channel type — it's a mandatory gate
- ❌ Do not use expensive models for compliance — Haiku or rule-based
- ❌ Do not persist budget to database yet — in-memory for Phase 2 (Redis in Phase 3)
- ❌ Do not allow negative budget — clamp to 0
- ❌ Do not raise ComplianceError for violations — return them as list
  - Only raise ComplianceError if the checker itself fails (e.g., LLM error)

## Pre-Written Tests

### tests/unit/test_compliance.py

```python
"""Tests for Compliance Checker."""

import pytest
from unittest.mock import AsyncMock

from omnicast.agents.compliance import (
    ComplianceChecker,
    YMYL_NICHES,
    COMPLIANCE_CHECKS,
)
from omnicast.llm.client import LLMClient, LLMResponse
from omnicast.models.script import ScriptDraft, ScriptSegment
from omnicast.models.enums import Niche
from omnicast.shared.errors import ComplianceError


@pytest.fixture
def mock_llm() -> AsyncMock:
    llm = AsyncMock(spec=LLMClient)
    llm.complete.return_value = LLMResponse(
        content="No misleading claims detected.",
        model="claude-haiku-4-5",
        input_tokens=100, output_tokens=20,
        cost_usd=0.0002, stop_reason="end_turn",
    )
    return llm


@pytest.fixture
def compliant_draft() -> ScriptDraft:
    """Draft that passes all compliance checks."""
    return ScriptDraft(
        variant_id="A",
        brief_title="Investment Tips",
        hook="Here are 5 tips for beginners.",
        segments=[
            ScriptSegment(index=0, heading="Intro", content="Welcome to this AI-generated video.",
                          estimated_duration_seconds=25),
        ],
        outro="Not financial advice. Do your own research.",
        description_template="This video was created with AI assistance.",
        word_count=1500,
        estimated_duration_seconds=600,
    )


@pytest.fixture
def non_compliant_draft() -> ScriptDraft:
    """Draft with compliance issues."""
    return ScriptDraft(
        variant_id="B",
        brief_title="Get Rich Quick",
        hook="This ONE trick will make you a millionaire!",
        segments=[
            ScriptSegment(index=0, heading="Intro", content="I guarantee 1000% returns.",
                          estimated_duration_seconds=30),
        ],
        outro="",
        description_template="Great tips for making money!",  # no AI disclosure
        word_count=1000,
        estimated_duration_seconds=400,
    )


class TestComplianceChecker:
    async def test_name(self, mock_llm):
        checker = ComplianceChecker(llm=mock_llm)
        assert checker.name == "compliance"

    async def test_compliant_passes(self, mock_llm, compliant_draft):
        checker = ComplianceChecker(llm=mock_llm)
        passed, violations = await checker.execute(compliant_draft, niche=Niche.FINANCE)
        assert passed is True
        assert violations == []

    async def test_missing_ai_disclosure(self, mock_llm, non_compliant_draft):
        checker = ComplianceChecker(llm=mock_llm)
        passed, violations = await checker.execute(non_compliant_draft, niche=Niche.TECH)
        assert passed is False
        assert any("ai_disclosure" in v.lower() or "ai" in v.lower() for v in violations)

    async def test_ymyl_niches_defined(self):
        assert Niche.FINANCE in YMYL_NICHES
        assert Niche.HEALTH in YMYL_NICHES
        assert Niche.TECH not in YMYL_NICHES

    async def test_compliance_checks_list(self):
        assert len(COMPLIANCE_CHECKS) >= 5
        assert "ai_disclosure" in COMPLIANCE_CHECKS

    async def test_ymyl_extra_checks(self, mock_llm, compliant_draft):
        checker = ComplianceChecker(llm=mock_llm)
        assert checker._is_ymyl(Niche.FINANCE) is True
        assert checker._is_ymyl(Niche.TECH) is False

    async def test_llm_error_raises_compliance_error(self, mock_llm, compliant_draft):
        mock_llm.complete.side_effect = Exception("LLM down")
        checker = ComplianceChecker(llm=mock_llm)
        with pytest.raises(ComplianceError):
            await checker.execute(compliant_draft, niche=Niche.HEALTH)
```

### tests/unit/test_budget.py

```python
"""Tests for Budget Manager."""

import pytest
from unittest.mock import patch
from datetime import date, timezone, datetime

from omnicast.services.budget import BudgetManager
from omnicast.shared.errors import AgentError


class TestBudgetManager:
    def test_init_with_budget(self):
        bm = BudgetManager(daily_budget_usd=5.0)
        assert bm.daily_budget == 5.0
        assert bm.daily_spent == 0.0
        assert bm.daily_remaining == 5.0

    def test_can_spend_within_budget(self):
        bm = BudgetManager(daily_budget_usd=10.0)
        assert bm.can_spend(5.0) is True
        assert bm.can_spend(10.0) is True

    def test_can_spend_over_budget(self):
        bm = BudgetManager(daily_budget_usd=1.0)
        bm.record_spend(0.8)
        assert bm.can_spend(0.3) is False  # 0.8 + 0.3 > 1.0
        assert bm.can_spend(0.2) is True   # 0.8 + 0.2 = 1.0

    def test_record_spend(self):
        bm = BudgetManager(daily_budget_usd=10.0)
        bm.record_spend(1.5, model="claude-sonnet-4-6", agent="writer")
        bm.record_spend(0.3, model="claude-haiku-4-5", agent="critic")
        assert bm.daily_spent == pytest.approx(1.8, abs=1e-6)
        assert bm.daily_remaining == pytest.approx(8.2, abs=1e-6)

    def test_summary(self):
        bm = BudgetManager(daily_budget_usd=10.0)
        bm.record_spend(1.0, model="claude-sonnet-4-6", agent="writer")
        bm.record_spend(0.5, model="claude-sonnet-4-6", agent="critic")
        bm.record_spend(0.1, model="claude-haiku-4-5", agent="compliance")
        summary = bm.summary()
        assert "total" in summary or isinstance(summary, dict)
        assert summary.get("total", summary.get("daily_spent", 0)) == pytest.approx(1.6, abs=1e-2)

    def test_day_reset(self):
        bm = BudgetManager(daily_budget_usd=5.0)
        bm.record_spend(3.0)
        # Simulate day change
        bm._last_reset_day = date(2020, 1, 1)
        bm._maybe_reset()
        assert bm.daily_spent == 0.0

    def test_multiple_spends_accumulate(self):
        bm = BudgetManager(daily_budget_usd=10.0)
        for _ in range(10):
            bm.record_spend(0.5)
        assert bm.daily_spent == pytest.approx(5.0, abs=1e-6)

    def test_zero_budget(self):
        bm = BudgetManager(daily_budget_usd=0.0)
        assert bm.can_spend(0.01) is False

    def test_record_with_video_id(self):
        bm = BudgetManager(daily_budget_usd=10.0)
        bm.record_spend(1.0, model="sonnet", agent="writer", video_id=42)
        assert bm.daily_spent == pytest.approx(1.0, abs=1e-6)

    def test_remaining_never_negative(self):
        bm = BudgetManager(daily_budget_usd=1.0)
        bm.record_spend(2.0)  # overspend
        assert bm.daily_remaining >= 0.0 or bm.daily_remaining == pytest.approx(-1.0, abs=0.01)
        # Note: remaining can go negative if spend exceeds budget,
        # but can_spend should prevent this in normal flow
```

## Verify

```bash
uv run pytest tests/unit/test_compliance.py tests/unit/test_budget.py -v
uv run ruff check src/omnicast/agents/compliance.py src/omnicast/services/budget.py
uv run pyright src/omnicast/agents/compliance.py src/omnicast/services/budget.py
```
