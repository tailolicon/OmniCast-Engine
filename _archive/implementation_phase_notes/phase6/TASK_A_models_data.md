# TASK_A: Dashboard Models + Data Service

## Model: sonnet | Dependencies: Phase 1-5 complete

Dashboard-specific models + read-only data service over existing repos.

## Interface

### src/omnicast/dashboard/models.py

```python
class SystemKPI(OmnicastSchema):
    """Top-level KPIs for dashboard home."""
    videos_today: int
    active_channels: int
    system_health: float  # 0-100
    queue_depth: int
    dlq_count: int

class WorkerStatus(OmnicastSchema):
    """Single worker health snapshot."""
    worker_id: str
    hostname: str
    cpu_percent: float
    ram_percent: float
    gpu_temp: float | None
    last_heartbeat: datetime
    status: str  # "healthy" | "degraded" | "offline"
    current_task: str | None

class DLQItem(OmnicastSchema):
    """Dead letter queue item for viewer."""
    item_id: str
    queue_name: str
    error_message: str
    payload_summary: str  # truncated, not full payload
    failed_at: datetime
    retry_count: int

class PipelineItem(OmnicastSchema):
    """Single video in production pipeline."""
    video_id: str
    channel_id: str
    niche: str
    status: str  # "researching" | "debating" | "rendering" | "uploading" | "published"
    started_at: datetime
    updated_at: datetime
    progress_pct: float  # 0-100

class ChannelHealth(OmnicastSchema):
    """Channel health summary for dashboard."""
    channel_id: str
    channel_name: str
    channel_type: str
    health_score: float  # 0-100
    videos_published: int
    last_upload: datetime | None
    ctr_avg: float | None
    retention_avg: float | None

class ComplianceLogEntry(OmnicastSchema):
    """Compliance check result for audit trail."""
    video_id: str
    channel_id: str
    checked_at: datetime
    passed: bool
    violations: list[str]
    checks: dict[str, bool]

class TokenStatusView(OmnicastSchema):
    """OAuth token status for dashboard display."""
    channel_id: str
    channel_name: str
    status: str  # "healthy" | "warning" | "expired"
    expires_at: datetime | None
    last_refresh: datetime | None
    scopes: list[str]

class DashboardFilter(OmnicastSchema):
    """Common filter for dashboard queries."""
    model_config = {"frozen": False}
    channel_id: str | None = None
    date_from: datetime | None = None
    date_to: datetime | None = None
    status: str | None = None
    limit: int = 50
```

### src/omnicast/dashboard/data_service.py

```python
class DashboardDataService:
    """Read-only data service. All dashboard tabs query through this."""
    def __init__(self, db_session_factory, redis_client=None)
    def get_kpis(self) -> SystemKPI
    def get_pipeline_items(self, filter: DashboardFilter | None = None) -> list[PipelineItem]
    def get_worker_statuses(self) -> list[WorkerStatus]
    def get_dlq_items(self, limit: int = 50) -> list[DLQItem]
    def get_channel_health(self, channel_id: str | None = None) -> list[ChannelHealth]
    def get_compliance_log(self, filter: DashboardFilter | None = None) -> list[ComplianceLogEntry]
    def get_token_statuses(self) -> list[TokenStatusView]
    def retry_dlq_item(self, item_id: str) -> bool
    def discard_dlq_item(self, item_id: str) -> bool
```

## DO NOT

- No Streamlit code — data layer only
- All methods return Pydantic models, not raw dicts
- retry/discard_dlq are the ONLY write operations

## Tests

### tests/unit/test_dashboard_models.py

```python
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
```

### tests/unit/test_data_service.py

```python
import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
from omnicast.dashboard.data_service import DashboardDataService
from omnicast.dashboard.models import (
    SystemKPI, WorkerStatus, DLQItem, PipelineItem,
    ChannelHealth, ComplianceLogEntry, TokenStatusView,
    DashboardFilter,
)


@pytest.fixture
def mock_db_session():
    session = MagicMock()
    session.__enter__ = MagicMock(return_value=session)
    session.__exit__ = MagicMock(return_value=False)
    return session


@pytest.fixture
def mock_session_factory(mock_db_session):
    factory = MagicMock(return_value=mock_db_session)
    return factory


@pytest.fixture
def service(mock_session_factory):
    return DashboardDataService(db_session_factory=mock_session_factory)


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
```
