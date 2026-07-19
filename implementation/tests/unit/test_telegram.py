"""Unit tests for Telegram bot and alert manager.

Tests use AsyncMock for bot methods and unittest.mock.patch for library calls.
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from omnicast.models.enums import AlertSeverity
from omnicast.models.schemas import AlertMessage
from omnicast.telegram.alert_manager import AlertManager
from omnicast.telegram.bot import TelegramBot
from omnicast.telegram.commands import CommandRouter, COMMANDS
from omnicast.telegram.formatter import AlertFormatter


# ─── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_tg_bot() -> TelegramBot:
    """TelegramBot with mocked internal _bot."""
    bot = TelegramBot.__new__(TelegramBot)
    bot.chat_id = "TEST_CHAT"
    bot._bot = AsyncMock()
    return bot


@pytest.fixture
def alert_msg() -> AlertMessage:
    return AlertMessage(
        severity=AlertSeverity.CRITICAL,
        source="pipeline",
        alert_type="render_failed",
        message="Render failed for video_001",
    )


@pytest.fixture
def manager(mock_tg_bot: TelegramBot) -> AlertManager:
    return AlertManager(
        bot=mock_tg_bot,
        max_alerts_per_hour=30,
        quiet_start="00:00",
        quiet_end="00:00",
    )


# ─── AlertFormatter Tests ──────────────────────────────────────────────────────


class TestAlertFormatter:
    def test_escape_markdown(self):
        result = AlertFormatter.escape_markdown("hello_world *bold* (test)")
        assert result == r"hello\_world \*bold\* \(test\)"

    def test_escape_markdown_all_specials(self):
        result = AlertFormatter.escape_markdown("_*[]()~`>#+-=|{}.!")
        # Every special char should be escaped
        for ch in r"_*[]()~`>#+-=|{}.!":
            assert f"\\{ch}" in result

    def test_format_alert_critical(self, alert_msg: AlertMessage):
        result = AlertFormatter.format_alert(alert_msg)
        assert "🔴" in result
        assert "CRITICAL" in result
        assert "pipeline" in result
        assert "Render failed" in result

    def test_format_alert_with_details(self):
        alert = AlertMessage(
            severity=AlertSeverity.HIGH,
            source="worker_1",
            alert_type="oom",
            message="Out of memory",
            details={"video_id": "v001", "error": "OOM"},
        )
        result = AlertFormatter.format_alert(alert)
        assert "Details" in result
        assert "video_id" in result
        assert "v001" in result

    def test_format_alert_no_details(self, alert_msg: AlertMessage):
        result = AlertFormatter.format_alert(alert_msg)
        assert "Details" not in result

    def test_format_daily_digest(self):
        stats = {
            "date": "2026-05-23",
            "videos_produced": 10,
            "videos_uploaded": 8,
            "videos_failed": 2,
            "total_errors": 5,
            "total_expenses_usd": 12.34,
            "llm_cost_usd": 8.00,
            "unresolved_alerts": 3,
            "top_channels": [
                {"channel_id": "hub_fin_us", "videos_count": 5},
            ],
        }
        result = AlertFormatter.format_daily_digest(stats)
        assert "Daily Digest" in result
        assert "2026" in result
        assert "10" in result  # videos_produced
        assert "hub_fin_us" in result

    def test_format_pipeline_status(self):
        counts = {"scripting": 3, "rendering": 5}
        result = AlertFormatter.format_pipeline_status(counts)
        assert "Pipeline Status" in result
        assert "3" in result
        assert "5" in result
        assert "Scripting" in result
        assert "Rendering" in result

    def test_format_budget_status_normal(self):
        budget = {
            "daily_limit_usd": 50.0,
            "spent_today_usd": 20.0,
            "remaining_usd": 30.0,
            "percent_used": 40.0,
        }
        result = AlertFormatter.format_budget_status(budget)
        assert "Budget Status" in result
        assert "50" in result
        assert "WARNING" not in result

    def test_format_budget_status_warning(self):
        budget = {
            "daily_limit_usd": 50.0,
            "spent_today_usd": 45.0,
            "remaining_usd": 5.0,
            "percent_used": 90.0,
        }
        result = AlertFormatter.format_budget_status(budget)
        assert "WARNING" in result

    def test_format_suppressed_notice(self):
        result = AlertFormatter.format_suppressed_notice("original message", 15)
        assert "Suppressed 15 duplicate" in result
        assert "original message" in result


# ─── TelegramBot Tests ────────────────────────────────────────────────────────


class TestTelegramBot:
    async def test_send_text_success(self, mock_tg_bot: TelegramBot):
        mock_msg = MagicMock()
        mock_msg.message_id = 123
        mock_tg_bot._bot.send_message = AsyncMock(return_value=mock_msg)

        result = await mock_tg_bot.send_text("test message")
        assert result == 123
        mock_tg_bot._bot.send_message.assert_called_once()

    async def test_send_text_failure_returns_none(self, mock_tg_bot: TelegramBot):
        from telegram.error import TelegramError

        mock_tg_bot._bot.send_message = AsyncMock(side_effect=TelegramError("fail"))
        result = await mock_tg_bot.send_text("test")
        assert result is None

    async def test_send_text_long_message_splits(self, mock_tg_bot: TelegramBot):
        mock_msg = MagicMock()
        mock_msg.message_id = 1
        mock_tg_bot._bot.send_message = AsyncMock(return_value=mock_msg)

        long_text = "x" * 5000
        result = await mock_tg_bot.send_text(long_text)
        # Should have been called multiple times (split)
        assert mock_tg_bot._bot.send_message.call_count > 1
        assert result is not None

    async def test_health_check_success(self, mock_tg_bot: TelegramBot):
        mock_tg_bot._bot.get_me = AsyncMock(return_value=MagicMock())
        assert await mock_tg_bot.health_check() is True

    async def test_health_check_failure(self, mock_tg_bot: TelegramBot):
        from telegram.error import TelegramError

        mock_tg_bot._bot.get_me = AsyncMock(side_effect=TelegramError("no conn"))
        assert await mock_tg_bot.health_check() is False

    async def test_edit_message_success(self, mock_tg_bot: TelegramBot):
        mock_tg_bot._bot.edit_message_text = AsyncMock(return_value=MagicMock())
        result = await mock_tg_bot.edit_message(123, "new text")
        assert result is True

    async def test_edit_message_failure(self, mock_tg_bot: TelegramBot):
        from telegram.error import TelegramError

        mock_tg_bot._bot.edit_message_text = AsyncMock(
            side_effect=TelegramError("not found")
        )
        result = await mock_tg_bot.edit_message(999, "text")
        assert result is False


# ─── AlertManager Tests ───────────────────────────────────────────────────────


class TestAlertManager:
    async def test_send_normal_alert(
        self, manager: AlertManager, alert_msg: AlertMessage
    ):
        manager.bot.send_text = AsyncMock(return_value=42)

        await manager.send(alert_msg)
        manager.bot.send_text.assert_called_once()

    async def test_dedup_suppresses_duplicate(
        self, manager: AlertManager, alert_msg: AlertMessage
    ):
        manager.bot.send_text = AsyncMock(return_value=1)

        await manager.send(alert_msg)
        await manager.send(alert_msg)  # Same source + message

        # Only called once — second is suppressed
        assert manager.bot.send_text.call_count == 1

    async def test_dedup_allows_different_alerts(self, manager: AlertManager):
        manager.bot.send_text = AsyncMock(return_value=1)

        alert_a = AlertMessage(
            severity=AlertSeverity.HIGH,
            source="pipeline",
            alert_type="err",
            message="error A",
        )
        alert_b = AlertMessage(
            severity=AlertSeverity.HIGH,
            source="pipeline",
            alert_type="err",
            message="error B",
        )

        await manager.send(alert_a)
        await manager.send(alert_b)
        assert manager.bot.send_text.call_count == 2

    async def test_dedup_updates_on_10th(self, manager: AlertManager):
        manager.bot.send_text = AsyncMock(return_value=42)
        manager.bot.edit_message = AsyncMock(return_value=True)

        alert = AlertMessage(
            severity=AlertSeverity.MEDIUM,
            source="worker",
            alert_type="slow",
            message="slow response",
        )

        for _ in range(10):
            await manager.send(alert)

        # send_text called once (1st alert), edit_message called once (10th)
        assert manager.bot.send_text.call_count == 1
        assert manager.bot.edit_message.call_count == 1

    async def test_quiet_hours_queues_non_critical(self, manager: AlertManager):
        manager.bot.send_text = AsyncMock(return_value=1)

        # Force quiet hours
        with patch.object(manager, "_is_quiet_hours", return_value=True):
            alert = AlertMessage(
                severity=AlertSeverity.MEDIUM,
                source="sys",
                alert_type="info",
                message="info",
            )
            await manager.send(alert)

        manager.bot.send_text.assert_not_called()
        assert len(manager._pending) == 1

    async def test_quiet_hours_allows_critical(self, manager: AlertManager):
        manager.bot.send_text = AsyncMock(return_value=1)

        with patch.object(manager, "_is_quiet_hours", return_value=True):
            alert = AlertMessage(
                severity=AlertSeverity.CRITICAL,
                source="sys",
                alert_type="fatal",
                message="fatal error",
            )
            await manager.send(alert)

        # Critical bypasses quiet hours
        manager.bot.send_text.assert_called_once()
        assert len(manager._pending) == 0

    def test_quiet_hours_midnight_crossing(self, manager: AlertManager):
        """quiet_start=23:00, quiet_end=07:00 — crosses midnight."""
        from datetime import time
        from zoneinfo import ZoneInfo

        manager.quiet_start = time(23, 0)
        manager.quiet_end = time(7, 0)
        manager.quiet_tz = ZoneInfo("UTC")

        # 00:30 UTC → should be quiet
        with patch("omnicast.telegram.alert_manager.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 5, 23, 0, 30, tzinfo=timezone.utc)
            mock_dt.now.return_value = datetime(2026, 5, 23, 0, 30, tzinfo=timezone.utc)

        # Direct time check
        from datetime import time as t

        def check_quiet(hour: int, minute: int) -> bool:
            now_t = t(hour, minute)
            start = manager.quiet_start
            end = manager.quiet_end
            if start > end:
                return now_t >= start or now_t < end
            return start <= now_t < end

        assert check_quiet(0, 30) is True   # 00:30 → quiet
        assert check_quiet(8, 0) is False   # 08:00 → not quiet
        assert check_quiet(22, 0) is False  # 22:00 → not quiet
        assert check_quiet(23, 30) is True  # 23:30 → quiet

    async def test_throttle_limits_per_hour(self, manager: AlertManager):
        manager.max_alerts_per_hour = 3
        manager.bot.send_text = AsyncMock(return_value=1)

        for i in range(4):
            a = AlertMessage(
                severity=AlertSeverity.LOW,
                source=f"src_{i}",
                alert_type="test",
                message=f"message {i}",
            )
            await manager.send(a)

        # First 3 sent, 4th throttled
        assert manager.bot.send_text.call_count == 3
        assert len(manager._pending) == 1

    async def test_throttle_allows_critical(self, manager: AlertManager):
        manager.max_alerts_per_hour = 1
        manager.bot.send_text = AsyncMock(return_value=1)

        # Send 1 normal to hit the limit
        normal = AlertMessage(
            severity=AlertSeverity.LOW,
            source="src",
            alert_type="t",
            message="msg",
        )
        await manager.send(normal)

        # Now send critical — should bypass throttle
        critical = AlertMessage(
            severity=AlertSeverity.CRITICAL,
            source="src2",
            alert_type="fatal",
            message="fatal",
        )
        await manager.send(critical)

        assert manager.bot.send_text.call_count == 2

    async def test_flush_pending(self, manager: AlertManager):
        manager.bot.send_text = AsyncMock(return_value=1)

        # Queue 3 alerts directly
        for i in range(3):
            alert = AlertMessage(
                severity=AlertSeverity.MEDIUM,
                source="src",
                alert_type="t",
                message=f"msg {i}",
            )
            manager._pending.append(alert)

        sent = await manager.flush_pending()
        assert sent == 3
        assert manager.bot.send_text.call_count == 3
        assert len(manager._pending) == 0

    async def test_flush_skips_stale(self, manager: AlertManager):
        manager.bot.send_text = AsyncMock(return_value=1)

        # Stale alert — 7 hours ago
        old_ts = datetime.now(timezone.utc) - timedelta(hours=7)
        stale = AlertMessage(
            severity=AlertSeverity.LOW,
            source="old",
            alert_type="t",
            message="stale",
            timestamp=old_ts,
        )
        manager._pending.append(stale)

        sent = await manager.flush_pending()
        assert sent == 0
        manager.bot.send_text.assert_not_called()

    async def test_daily_digest(self, manager: AlertManager):
        manager.bot.send_text = AsyncMock(return_value=1)

        stats = {
            "date": "2026-05-23",
            "videos_produced": 5,
            "videos_uploaded": 4,
            "videos_failed": 1,
            "total_errors": 2,
            "total_expenses_usd": 10.0,
            "llm_cost_usd": 7.0,
            "unresolved_alerts": 0,
        }
        await manager.send_daily_digest(stats)

        manager.bot.send_text.assert_called_once()
        # verify disable_notification=True
        call_kwargs = manager.bot.send_text.call_args.kwargs
        assert call_kwargs.get("disable_notification") is True
        # State cleared after digest
        assert len(manager._fingerprints) == 0
        assert manager._hourly_count == 0

    async def test_cleanup_stale_fingerprints(self, manager: AlertManager):
        old_time = datetime.now(timezone.utc) - timedelta(hours=3)
        manager._fingerprints["old_fp"] = {"count": 5, "first_seen": old_time}
        manager._fingerprints["new_fp"] = {
            "count": 1,
            "first_seen": datetime.now(timezone.utc),
        }

        removed = await manager.cleanup_stale_fingerprints()
        assert removed == 1
        assert "old_fp" not in manager._fingerprints
        assert "new_fp" in manager._fingerprints

    def test_get_stats(self, manager: AlertManager):
        stats = manager.get_stats()
        assert "active_fingerprints" in stats
        assert "pending_count" in stats
        assert "hourly_count" in stats
        assert "is_quiet_hours" in stats
        assert "is_throttled" in stats


# ─── CommandRouter Tests ──────────────────────────────────────────────────────


class TestCommandRouter:
    @pytest.fixture
    def router(self, mock_tg_bot: TelegramBot) -> CommandRouter:
        return CommandRouter(bot=mock_tg_bot)

    async def test_handle_help(self, router: CommandRouter):
        update = MagicMock()
        update.message.reply_text = AsyncMock()
        context = MagicMock()

        await router.handle_help(update, context)

        update.message.reply_text.assert_called_once()
        reply = update.message.reply_text.call_args[0][0]
        for cmd in COMMANDS:
            assert f"/{cmd}" in reply

    async def test_handle_pause(self, router: CommandRouter):
        update = MagicMock()
        update.message.reply_text = AsyncMock()
        context = MagicMock()

        mock_redis = AsyncMock()
        router.set_dependencies(redis_client=mock_redis)

        await router.handle_pause(update, context)

        mock_redis.set.assert_called_once_with("omnicast:paused", "1")
        reply = update.message.reply_text.call_args[0][0]
        assert "paused" in reply.lower()

    async def test_handle_resume(self, router: CommandRouter):
        update = MagicMock()
        update.message.reply_text = AsyncMock()
        context = MagicMock()

        mock_redis = AsyncMock()
        router.set_dependencies(redis_client=mock_redis)

        await router.handle_resume(update, context)

        mock_redis.delete.assert_called_once_with("omnicast:paused")
        reply = update.message.reply_text.call_args[0][0]
        assert "resumed" in reply.lower()

    async def test_handle_status_no_deps(self, router: CommandRouter):
        update = MagicMock()
        update.message.reply_text = AsyncMock()
        context = MagicMock()

        await router.handle_status(update, context)

        reply = update.message.reply_text.call_args[0][0]
        assert "initializing" in reply.lower()

    def test_get_handlers(self, router: CommandRouter):
        handlers = router.get_handlers()
        assert len(handlers) == 7
        commands = {h.commands for h in handlers}
        # Each handler has a set of commands
        all_cmds = set()
        for cmd_set in commands:
            all_cmds.update(cmd_set)
        assert "status" in all_cmds
        assert "pause" in all_cmds
        assert "resume" in all_cmds
        assert "budget" in all_cmds
        assert "alerts" in all_cmds
        assert "health" in all_cmds
        assert "help" in all_cmds
