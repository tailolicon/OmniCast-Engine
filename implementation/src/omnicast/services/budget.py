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
        if daily_budget_usd is None:
            self._daily_budget = get_settings().daily_llm_budget_usd
        else:
            self._daily_budget = daily_budget_usd

        self._daily_spent: float = 0.0
        self._by_model: dict[str, float] = {}
        self._by_agent: dict[str, float] = {}
        self._last_reset_day = self._current_day()

    def can_spend(self, amount_usd: float) -> bool:
        """Check if spending amount would stay within budget."""
        self._maybe_reset()
        return (self._daily_spent + amount_usd) <= self._daily_budget

    def record_spend(
        self,
        amount_usd: float,
        *,
        model: str = "",
        agent: str = "",
        video_id: int | None = None,
    ) -> None:
        """Record a spend event."""
        self._maybe_reset()
        self._daily_spent += amount_usd

        if model:
            self._by_model[model] = self._by_model.get(model, 0.0) + amount_usd

        if agent:
            self._by_agent[agent] = self._by_agent.get(agent, 0.0) + amount_usd

        logger.info(
            "LLM spend recorded",
            amount_usd=amount_usd,
            model=model,
            agent=agent,
            video_id=video_id,
            daily_total=self._daily_spent,
        )

    @property
    def daily_spent(self) -> float:
        """Total spent today (UTC)."""
        self._maybe_reset()
        return self._daily_spent

    @property
    def daily_remaining(self) -> float:
        """Remaining budget today."""
        self._maybe_reset()
        return max(0.0, self._daily_budget - self._daily_spent)

    @property
    def daily_budget(self) -> float:
        """Configured daily budget."""
        return self._daily_budget

    def summary(self) -> dict:
        """Return spending summary: {total, remaining, by_model, by_agent}."""
        self._maybe_reset()
        return {
            "daily_spent": self._daily_spent,
            "daily_remaining": self.daily_remaining,
            "daily_budget": self._daily_budget,
            "by_model": self._by_model.copy(),
            "by_agent": self._by_agent.copy(),
        }

    def _current_day(self) -> date:
        """Return current UTC date."""
        return datetime.now(timezone.utc).date()

    def _maybe_reset(self) -> None:
        """Reset counters if day changed."""
        current_day = self._current_day()
        if current_day != self._last_reset_day:
            self._daily_spent = 0.0
            self._by_model.clear()
            self._by_agent.clear()
            self._last_reset_day = current_day
            logger.info("Budget counters reset for new day", date=current_day.isoformat())
