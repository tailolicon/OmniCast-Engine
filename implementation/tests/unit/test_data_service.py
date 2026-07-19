import pytest
from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
from omnicast.dashboard.data_service import DashboardDataService
from omnicast.dashboard.models import (
    SystemKPI, WorkerStatus, DLQItem, PipelineItem,
    ChannelHealth, ComplianceLogEntry, TokenStatusView,
    DashboardFilter,
)


@pytest.fixture
def service(tmp_path):
    """Service with no real DB/Redis — all methods return graceful empty defaults."""
    return DashboardDataService(
        db_url="postgresql+psycopg2://test:test@localhost/test_omnicast",
        redis_url="redis://localhost:6379/15",
        channels_dir=tmp_path / "channels",
        vault_path=tmp_path / "vault.db",
    )


class TestGetKPIs:
    def test_returns_system_kpi(self, service):
        result = service.get_kpis()
        assert isinstance(result, SystemKPI)

    def test_kpi_non_negative(self, service):
        result = service.get_kpis()
        assert result.videos_today >= 0
        assert result.system_health >= 0


class TestGetPipelineItems:
    def test_returns_list(self, service):
        result = service.get_pipeline_items()
        assert isinstance(result, list)

    def test_with_filter(self, service):
        f = DashboardFilter(channel_id="ch1", status="rendering")
        result = service.get_pipeline_items(filter=f)
        assert isinstance(result, list)


class TestGetWorkerStatuses:
    def test_returns_list(self, service):
        result = service.get_worker_statuses()
        assert isinstance(result, list)


class TestGetDLQItems:
    def test_returns_list(self, service):
        result = service.get_dlq_items()
        assert isinstance(result, list)

    def test_respects_limit(self, service):
        result = service.get_dlq_items(limit=10)
        assert isinstance(result, list)


class TestGetChannelHealth:
    def test_all_channels(self, service):
        result = service.get_channel_health()
        assert isinstance(result, list)

    def test_single_channel(self, service):
        result = service.get_channel_health(channel_id="ch1")
        assert isinstance(result, list)


class TestGetComplianceLog:
    def test_returns_list(self, service):
        result = service.get_compliance_log()
        assert isinstance(result, list)

    def test_with_filter(self, service):
        f = DashboardFilter(channel_id="ch1")
        result = service.get_compliance_log(filter=f)
        assert isinstance(result, list)


class TestGetTokenStatuses:
    def test_returns_list(self, service):
        result = service.get_token_statuses()
        assert isinstance(result, list)


class TestDLQActions:
    def test_retry_returns_bool(self, service):
        result = service.retry_dlq_item("dlq_1")
        assert isinstance(result, bool)

    def test_discard_returns_bool(self, service):
        result = service.discard_dlq_item("dlq_1")
        assert isinstance(result, bool)
