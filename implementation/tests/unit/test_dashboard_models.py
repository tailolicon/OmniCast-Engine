import pytest
from datetime import datetime, timezone
from omnicast.dashboard.models import (
    SystemKPI, WorkerStatus, DLQItem, PipelineItem,
    ChannelHealth, ComplianceLogEntry, TokenStatusView,
    DashboardFilter,
)


class TestSystemKPI:
    def test_create(self):
        kpi = SystemKPI(
            videos_today=5, active_channels=3,
            system_health=95.5, queue_depth=12, dlq_count=2,
        )
        assert kpi.videos_today == 5
        assert kpi.system_health == 95.5

    def test_frozen(self):
        kpi = SystemKPI(
            videos_today=5, active_channels=3,
            system_health=95.5, queue_depth=0, dlq_count=0,
        )
        with pytest.raises(Exception):
            kpi.videos_today = 10


class TestWorkerStatus:
    def test_healthy(self):
        w = WorkerStatus(
            worker_id="w1", hostname="gpu-01",
            cpu_percent=45.0, ram_percent=60.0,
            gpu_temp=72.0, last_heartbeat=datetime.now(timezone.utc),
            status="healthy", current_task="render_v123",
        )
        assert w.status == "healthy"
        assert w.gpu_temp == 72.0

    def test_no_gpu(self):
        w = WorkerStatus(
            worker_id="w2", hostname="cpu-01",
            cpu_percent=30.0, ram_percent=40.0,
            gpu_temp=None, last_heartbeat=datetime.now(timezone.utc),
            status="healthy", current_task=None,
        )
        assert w.gpu_temp is None


class TestDLQItem:
    def test_create(self):
        item = DLQItem(
            item_id="dlq_1", queue_name="render",
            error_message="GPU OOM", payload_summary='{"video_id": "v1"}',
            failed_at=datetime.now(timezone.utc), retry_count=3,
        )
        assert item.retry_count == 3
        assert item.queue_name == "render"


class TestPipelineItem:
    def test_create(self):
        p = PipelineItem(
            video_id="v1", channel_id="ch1", niche="mythology",
            status="rendering", started_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc), progress_pct=65.0,
        )
        assert p.status == "rendering"
        assert p.progress_pct == 65.0


class TestChannelHealth:
    def test_create(self):
        ch = ChannelHealth(
            channel_id="ch1", channel_name="MythTales",
            channel_type="hub", health_score=85.0,
            videos_published=42, last_upload=datetime.now(timezone.utc),
            ctr_avg=5.2, retention_avg=45.0,
        )
        assert ch.health_score == 85.0

    def test_no_metrics(self):
        ch = ChannelHealth(
            channel_id="ch2", channel_name="NewChannel",
            channel_type="spoke", health_score=50.0,
            videos_published=0, last_upload=None,
            ctr_avg=None, retention_avg=None,
        )
        assert ch.ctr_avg is None


class TestComplianceLogEntry:
    def test_passed(self):
        entry = ComplianceLogEntry(
            video_id="v1", channel_id="ch1",
            checked_at=datetime.now(timezone.utc),
            passed=True, violations=[],
            checks={"ai_disclosure": True, "not_targeting_children": True},
        )
        assert entry.passed
        assert len(entry.violations) == 0

    def test_failed(self):
        entry = ComplianceLogEntry(
            video_id="v2", channel_id="ch1",
            checked_at=datetime.now(timezone.utc),
            passed=False, violations=["Missing AI disclosure"],
            checks={"ai_disclosure": False},
        )
        assert not entry.passed


class TestTokenStatusView:
    def test_healthy(self):
        t = TokenStatusView(
            channel_id="ch1", channel_name="MythTales",
            status="healthy", expires_at=datetime.now(timezone.utc),
            last_refresh=datetime.now(timezone.utc),
            scopes=["youtube.upload"],
        )
        assert t.status == "healthy"

    def test_expired(self):
        t = TokenStatusView(
            channel_id="ch2", channel_name="OldChannel",
            status="expired", expires_at=None,
            last_refresh=None, scopes=[],
        )
        assert t.status == "expired"


class TestDashboardFilter:
    def test_defaults(self):
        f = DashboardFilter()
        assert f.limit == 50
        assert f.channel_id is None

    def test_mutable(self):
        f = DashboardFilter()
        f.channel_id = "ch1"
        assert f.channel_id == "ch1"

    def test_with_dates(self):
        now = datetime.now(timezone.utc)
        f = DashboardFilter(date_from=now, date_to=now, status="published")
        assert f.status == "published"
