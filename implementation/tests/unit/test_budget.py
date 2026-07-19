"""Tests for Budget Manager."""

import pytest
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
        assert "daily_spent" in summary
        assert summary["daily_spent"] == pytest.approx(1.6, abs=1e-2)

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
        assert bm.daily_remaining >= 0.0
