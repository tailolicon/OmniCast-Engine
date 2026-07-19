# TASK_D: Infrastructure + DLQ + Token Management Tabs

## Model: sonnet | Dependencies: TASK_A complete

Three tabs: worker health cards, DLQ viewer with retry/discard, OAuth token status.

## Interface

### src/omnicast/dashboard/tabs/infra.py

```python
def render_infra(data_service: DashboardDataService) -> None:
    """Worker status cards: CPU/RAM/GPU, heartbeat, current task. Color = health."""
```

### src/omnicast/dashboard/tabs/dlq.py

```python
def render_dlq(data_service: DashboardDataService) -> None:
    """DLQ table with Retry/Discard buttons per item."""
```

### src/omnicast/dashboard/tabs/tokens.py

```python
def render_tokens(data_service: DashboardDataService) -> None:
    """Token status table: channel, status badge, expiry countdown, re-auth link."""
```

## DO NOT

- DLQ retry/discard must confirm before action (st.button + st.warning)
- Token tab must NEVER display actual token values — show status only
- Worker "offline" = last_heartbeat > 5 minutes ago

## Tests

### tests/unit/test_dashboard_infra.py

```python
import pytest
from datetime import datetime, timezone, timedelta
from omnicast.dashboard.models import WorkerStatus, DLQItem, TokenStatusView


class TestWorkerStatusDisplay:
    def test_healthy_worker(self):
        w = WorkerStatus(
            worker_id="w1", hostname="gpu-01",
            cpu_percent=45.0, ram_percent=60.0,
            gpu_temp=72.0, last_heartbeat=datetime.now(timezone.utc),
            status="healthy", current_task="render_v1",
        )
        assert w.status == "healthy"

    def test_offline_detection(self):
        old = datetime.now(timezone.utc) - timedelta(minutes=10)
        w = WorkerStatus(
            worker_id="w2", hostname="gpu-02",
            cpu_percent=0, ram_percent=0,
            gpu_temp=None, last_heartbeat=old,
            status="offline", current_task=None,
        )
        assert w.status == "offline"
        assert (datetime.now(timezone.utc) - w.last_heartbeat).total_seconds() > 300

    def test_degraded_high_temp(self):
        w = WorkerStatus(
            worker_id="w3", hostname="gpu-03",
            cpu_percent=95.0, ram_percent=90.0,
            gpu_temp=89.0, last_heartbeat=datetime.now(timezone.utc),
            status="degraded", current_task="render_v5",
        )
        assert w.status == "degraded"


class TestDLQItemDisplay:
    def test_item_fields(self):
        item = DLQItem(
            item_id="dlq_1", queue_name="render",
            error_message="CUDA OOM on batch 42",
            payload_summary='{"video_id": "v1", "channel": "ch1"}',
            failed_at=datetime.now(timezone.utc), retry_count=2,
        )
        assert item.item_id == "dlq_1"
        assert item.retry_count == 2

    def test_payload_truncated(self):
        long_payload = '{"data": "' + "x" * 1000 + '"}'
        item = DLQItem(
            item_id="dlq_2", queue_name="upload",
            error_message="Quota exceeded",
            payload_summary=long_payload[:200],
            failed_at=datetime.now(timezone.utc), retry_count=0,
        )
        assert len(item.payload_summary) <= 200


class TestTokenStatusDisplay:
    def test_healthy_token(self):
        t = TokenStatusView(
            channel_id="ch1", channel_name="MythTales",
            status="healthy",
            expires_at=datetime.now(timezone.utc) + timedelta(days=30),
            last_refresh=datetime.now(timezone.utc),
            scopes=["youtube.upload", "youtube.readonly"],
        )
        assert t.status == "healthy"
        assert len(t.scopes) == 2

    def test_warning_token(self):
        t = TokenStatusView(
            channel_id="ch2", channel_name="TechBits",
            status="warning",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=2),
            last_refresh=datetime.now(timezone.utc) - timedelta(hours=22),
            scopes=["youtube.upload"],
        )
        assert t.status == "warning"

    def test_expired_token(self):
        t = TokenStatusView(
            channel_id="ch3", channel_name="OldChannel",
            status="expired", expires_at=None,
            last_refresh=None, scopes=[],
        )
        assert t.status == "expired"
        assert t.expires_at is None
```
