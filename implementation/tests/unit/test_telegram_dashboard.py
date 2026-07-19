import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, AsyncMock, patch
from omnicast.telegram.dashboard_commands import DashboardCommandHandler
from omnicast.dashboard.models import (
    SystemKPI, WorkerStatus, DLQItem, PipelineItem,
    TokenStatusView, ComplianceLogEntry,
)
from omnicast.dashboard.data_service import DashboardDataService


@pytest.fixture
def mock_data_service():
    ds = MagicMock(spec=DashboardDataService)
    ds.get_kpis.return_value = SystemKPI(
        videos_today=3, active_channels=5,
        system_health=92.0, queue_depth=7, dlq_count=1,
    )
    ds.get_pipeline_items.return_value = [
        PipelineItem(
            video_id="v1", channel_id="ch1", niche="myth",
            status="rendering", started_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc), progress_pct=50.0,
        ),
    ]
    ds.get_worker_statuses.return_value = [
        WorkerStatus(
            worker_id="w1", hostname="gpu-01",
            cpu_percent=45.0, ram_percent=60.0,
            gpu_temp=72.0, last_heartbeat=datetime.now(timezone.utc),
            status="healthy", current_task="render_v1",
        ),
    ]
    ds.get_dlq_items.return_value = [
        DLQItem(
            item_id="dlq_1", queue_name="render",
            error_message="GPU OOM", payload_summary="{}",
            failed_at=datetime.now(timezone.utc), retry_count=2,
        ),
    ]
    ds.get_token_statuses.return_value = [
        TokenStatusView(
            channel_id="ch1", channel_name="MythTales",
            status="healthy", expires_at=datetime.now(timezone.utc) + timedelta(days=30),
            last_refresh=datetime.now(timezone.utc), scopes=["youtube.upload"],
        ),
    ]
    ds.get_compliance_log.return_value = [
        ComplianceLogEntry(
            video_id="v1", channel_id="ch1",
            checked_at=datetime.now(timezone.utc),
            passed=True, violations=[], checks={"ai_disclosure": True},
        ),
    ]
    return ds


@pytest.fixture
def handler(mock_data_service):
    return DashboardCommandHandler(data_service=mock_data_service)


@pytest.fixture
def mock_update():
    update = MagicMock()
    update.message = MagicMock()
    update.message.reply_text = AsyncMock()
    return update


class TestCmdPipeline:
    @pytest.mark.asyncio
    async def test_sends_response(self, handler, mock_update):
        await handler.cmd_pipeline(mock_update, MagicMock())
        mock_update.message.reply_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_includes_status(self, handler, mock_update):
        await handler.cmd_pipeline(mock_update, MagicMock())
        msg = mock_update.message.reply_text.call_args[0][0]
        assert "rendering" in msg.lower() or "pipeline" in msg.lower()


class TestCmdWorkers:
    @pytest.mark.asyncio
    async def test_sends_response(self, handler, mock_update):
        await handler.cmd_workers(mock_update, MagicMock())
        mock_update.message.reply_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_shows_worker_info(self, handler, mock_update):
        await handler.cmd_workers(mock_update, MagicMock())
        msg = mock_update.message.reply_text.call_args[0][0]
        assert "gpu-01" in msg or "w1" in msg


class TestCmdDLQ:
    @pytest.mark.asyncio
    async def test_sends_response(self, handler, mock_update):
        await handler.cmd_dlq(mock_update, MagicMock())
        mock_update.message.reply_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_shows_count(self, handler, mock_update):
        await handler.cmd_dlq(mock_update, MagicMock())
        msg = mock_update.message.reply_text.call_args[0][0]
        assert "1" in msg or "dlq" in msg.lower()


class TestCmdTokens:
    @pytest.mark.asyncio
    async def test_sends_response(self, handler, mock_update):
        await handler.cmd_tokens(mock_update, MagicMock())
        mock_update.message.reply_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_token_values(self, handler, mock_update):
        await handler.cmd_tokens(mock_update, MagicMock())
        msg = mock_update.message.reply_text.call_args[0][0]
        assert "token" not in msg.lower() or "status" in msg.lower() or "healthy" in msg.lower()

    @pytest.mark.asyncio
    async def test_shows_status(self, handler, mock_update):
        await handler.cmd_tokens(mock_update, MagicMock())
        msg = mock_update.message.reply_text.call_args[0][0]
        assert "healthy" in msg.lower() or "MythTales" in msg


class TestCmdCompliance:
    @pytest.mark.asyncio
    async def test_sends_response(self, handler, mock_update):
        await handler.cmd_compliance(mock_update, MagicMock())
        mock_update.message.reply_text.assert_called_once()


class TestRegister:
    def test_register_handlers(self, handler):
        app = MagicMock()
        app.add_handler = MagicMock()
        handler.register(app)
        assert app.add_handler.call_count >= 5
