"""Behavior tests: analytics collector + vault time series + health renormalization."""

from datetime import date, timedelta
from pathlib import Path

import pytest

from omnicast.analytics.collector import (
    _metrics_to_rows,
    _rows_to_metrics,
    summarize,
)
from omnicast.analytics.health import HealthScorer
from omnicast.analytics.models import ChannelMetrics
from omnicast.vault import db as vault_db


def _mk_metrics(channel_id="ch1", days=14, ctr=0.0, revenue=0.0,
                views=500, avd=45.0) -> list[ChannelMetrics]:
    today = date.today()
    return [ChannelMetrics(
        channel_id=channel_id,
        date=today - timedelta(days=days - 1 - i),
        impressions=0, ctr=ctr, views=views + i * 10,
        avd_seconds=200.0, avd_percent=avd,
        watch_time_hours=20.0, subscriber_change=5,
        revenue=revenue, rpm=0.0,
        top_traffic_sources={"browse": 0.6},
    ) for i in range(days)]


@pytest.fixture
def vault_path(tmp_path: Path) -> Path:
    p = tmp_path / "vault.db"
    vault_db.init_db(p)
    return p


class TestVaultTimeSeries:
    def test_upsert_and_list_roundtrip(self, vault_path):
        metrics = _mk_metrics(days=5)
        n = vault_db.upsert_channel_metrics_daily(
            "ch1", _metrics_to_rows(metrics), vault_path)
        assert n == 5
        rows = vault_db.list_channel_metrics_daily("ch1", 90, vault_path)
        assert len(rows) == 5
        assert rows[0]["date"] < rows[-1]["date"]  # oldest first
        assert rows[0]["traffic_sources"] == {"browse": 0.6}
        back = _rows_to_metrics("ch1", rows)
        assert back[0].views == metrics[0].views
        assert back[-1].watch_time_hours == 20.0

    def test_upsert_is_idempotent(self, vault_path):
        rows = _metrics_to_rows(_mk_metrics(days=3))
        vault_db.upsert_channel_metrics_daily("ch1", rows, vault_path)
        rows[0]["views"] = 9999
        vault_db.upsert_channel_metrics_daily("ch1", rows, vault_path)
        stored = vault_db.list_channel_metrics_daily("ch1", 90, vault_path)
        assert len(stored) == 3  # no duplicates
        assert stored[0]["views"] == 9999  # updated in place


class TestSummarize:
    def test_empty_vault_returns_hint(self, vault_path):
        out = summarize("ch_none", vault_db_path=vault_path)
        assert out["days"] == 0 and "hint" in out

    def test_summary_fields(self, vault_path):
        vault_db.upsert_channel_metrics_daily(
            "ch1", _metrics_to_rows(_mk_metrics(days=14)), vault_path)
        out = summarize("ch1", vault_db_path=vault_path)
        assert out["days"] == 14
        assert out["views_7d"] > 0
        assert out["watch_time_hours_7d"] == pytest.approx(140.0)
        assert out["subscriber_change_7d"] == 35
        assert out["ctr_available"] is False   # API never returns CTR
        assert out["revenue_available"] is False
        assert 0 <= out["health_score"] <= 100
        assert out["severity"] in ("healthy", "warning", "critical", "dead")


class TestHealthRenormalization:
    def test_missing_ctr_and_revenue_do_not_tank_score(self):
        """Same underlying performance, with vs without CTR/revenue data:
        the no-CTR channel must not score drastically lower (old behavior
        gave 0/25 for CTR and 0/15 for revenue that simply weren't available)."""
        good_avd = _mk_metrics(ctr=0.0, revenue=0.0, avd=50.0)
        with_ctr = _mk_metrics(ctr=5.0, revenue=10.0, avd=50.0)
        s_missing = HealthScorer().score(good_avd).health_score
        s_full = HealthScorer().score(with_ctr).health_score
        assert s_missing >= 60  # avd=50% is a 10/10 component — must show
        assert abs(s_full - s_missing) < 25

    def test_zero_metrics_still_bounded(self):
        dead = _mk_metrics(views=0, avd=0.0)
        score = HealthScorer().score(dead).health_score
        assert 0 <= score <= 100
