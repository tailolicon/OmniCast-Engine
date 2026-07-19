# TASK G: Telegram Bot + Alert Manager

> **Depends on:** TASK_A hoàn thành (models/schemas.py có AlertMessage, AlertCreate; shared/errors.py có error hierarchy)
> **Output:** src/omnicast/telegram/, tests/unit/test_telegram.py
> **Parallel với:** TASK_B, C, D, E, F

## Context

Telegram là alert channel chính. Bot gửi:
1. **Alerts** — system errors, pipeline failures, budget warnings
2. **Daily Digest** — tổng hợp cuối ngày: videos produced, errors, expenses
3. **Commands** — operator gửi commands qua Telegram: `/status`, `/pause`, `/budget`

Alert Manager xử lý:
- **Deduplication** — cùng lỗi 10 lần → 1 alert + count
- **Quiet Hours** — 23:00-07:00 chỉ gửi emergency
- **Throttle** — max 30 alerts/hour (tránh spam)
- **Escalation** — unresolved critical → re-alert after 30 min

## Files cần tạo

```
src/omnicast/telegram/
├── __init__.py
├── bot.py              # Telegram bot client
├── formatter.py        # Message formatting (Markdown)
├── commands.py         # Command handlers
└── alert_manager.py    # Dedup, throttle, quiet hours
```

## 1. bot.py

```python
"""Telegram bot client for sending messages.

Uses python-telegram-bot library (async).
Singleton pattern — init once, reuse.

Usage:
    bot = TelegramBot(token="BOT_TOKEN", chat_id="CHAT_ID")
    await bot.send_alert(alert_message)
    await bot.send_text("Pipeline paused by operator")
"""

from telegram import Bot
from telegram.constants import ParseMode
import structlog

logger = structlog.get_logger()

class TelegramBot:
    """Async Telegram bot client.
    
    Args:
        token: Bot API token from BotFather
        chat_id: Default chat ID for alerts (group or personal)
    """
    
    def __init__(self, token: str, chat_id: str):
        self.chat_id = chat_id
        self._bot = Bot(token=token)
    
    async def send_text(
        self,
        text: str,
        chat_id: str | None = None,
        parse_mode: str = ParseMode.MARKDOWN_V2,
        disable_notification: bool = False,
    ) -> int | None:
        """Send text message. Return message_id on success, None on failure.
        
        Implementation:
        1. Use chat_id param or fall back to self.chat_id
        2. Truncate text to 4096 chars (Telegram limit)
        3. If text > 4096 → split into multiple messages
        4. await self._bot.send_message(...)
        5. Log: "Telegram sent" with chat_id, length
        6. Return message.message_id
        
        Error handling:
        - Catch telegram.error.TelegramError
        - Log error with details
        - Return None (don't crash pipeline for alert failure)
        - NEVER raise — alerts are best-effort
        """
    
    async def send_document(
        self,
        file_path: str,
        caption: str = "",
        chat_id: str | None = None,
    ) -> int | None:
        """Send file as document. For daily digest CSV/PDF.
        
        Same error handling as send_text.
        """
    
    async def send_photo(
        self,
        photo_path: str,
        caption: str = "",
        chat_id: str | None = None,
    ) -> int | None:
        """Send image. For thumbnail previews or charts."""
    
    async def edit_message(
        self,
        message_id: int,
        text: str,
        chat_id: str | None = None,
    ) -> bool:
        """Edit existing message. Used to update alert status.
        
        Return True if edited, False on error.
        """
    
    async def health_check(self) -> bool:
        """Verify bot connectivity.
        
        - Call getMe() API
        - Return True if responds, False otherwise
        """
```

## 2. formatter.py

```python
"""Format alert messages for Telegram (MarkdownV2).

Telegram MarkdownV2 requires escaping: _ * [ ] ( ) ~ ` > # + - = | { } . !

Usage:
    msg = AlertFormatter.format_alert(alert_message)
    msg = AlertFormatter.format_daily_digest(stats)
    msg = AlertFormatter.format_pipeline_status(pipeline_counts)
"""

from omnicast.models.schemas import AlertMessage
from datetime import datetime

# Severity → emoji mapping
SEVERITY_EMOJI = {
    "critical": "🔴",
    "high": "🟠",
    "medium": "🟡",
    "low": "🟢",
    "info": "ℹ️",
}

class AlertFormatter:
    """Static methods for formatting Telegram messages."""
    
    @staticmethod
    def escape_markdown(text: str) -> str:
        """Escape special chars for MarkdownV2.
        
        Must escape: _ * [ ] ( ) ~ ` > # + - = | { } . !
        """
        special = r'_*[]()~`>#+-=|{}.!'
        result = ""
        for char in text:
            if char in special:
                result += f"\\{char}"
            else:
                result += char
        return result
    
    @staticmethod
    def format_alert(alert: AlertMessage) -> str:
        """Format AlertMessage for Telegram.
        
        Template:
        ```
        {severity_emoji} *{SEVERITY}* — {source}
        
        {message}
        
        📋 Details:
        {key: value for each detail}
        
        🕐 {timestamp}
        ```
        
        Rules:
        - Escape all dynamic text with escape_markdown()
        - Severity header is bold
        - Details section only if alert.details is not empty
        - Timestamp in Asia/Ho_Chi_Minh timezone
        """
    
    @staticmethod
    def format_daily_digest(stats: dict) -> str:
        """Format daily digest message.
        
        Expected stats dict:
        {
            "date": str,
            "videos_produced": int,
            "videos_uploaded": int,
            "videos_failed": int,
            "total_errors": int,
            "total_expenses_usd": float,
            "llm_cost_usd": float,
            "top_channels": list[dict],  # [{channel_id, videos_count}]
            "unresolved_alerts": int,
        }
        
        Template:
        ```
        📊 *Daily Digest — {date}*
        
        🎬 Videos: {produced} produced, {uploaded} uploaded, {failed} failed
        💰 Cost: ${total} (LLM: ${llm})
        ⚠️ Errors: {errors} total, {unresolved} unresolved
        
        🏆 Top Channels:
        1. {channel_id} — {count} videos
        2. ...
        ```
        """
    
    @staticmethod
    def format_pipeline_status(counts: dict[str, int]) -> str:
        """Format pipeline status response.
        
        Expected counts: {"scripting": 3, "rendering": 5, "uploading": 1, ...}
        
        Template:
        ```
        📊 *Pipeline Status*
        
        ✍️ Scripting: {n}
        🎨 Rendering: {n}
        📤 Uploading: {n}
        ✅ Quality Check: {n}
        ❌ Failed: {n}
        
        Total in pipeline: {sum}
        ```
        """
    
    @staticmethod
    def format_budget_status(budget: dict) -> str:
        """Format budget status.
        
        Expected budget:
        {
            "daily_limit_usd": float,
            "spent_today_usd": float,
            "remaining_usd": float,
            "percent_used": float,
        }
        
        Template:
        ```
        💰 *Budget Status*
        
        Daily limit: ${limit}
        Spent today: ${spent} ({percent}%)
        Remaining: ${remaining}
        
        {warning if > 80%}
        ```
        """
    
    @staticmethod
    def format_suppressed_notice(
        original_message: str,
        suppressed_count: int,
    ) -> str:
        """Format dedup suppression notice.
        
        Appends to original alert:
        "\\n\\n🔇 _Suppressed {count} duplicate alerts_"
        """
```

## 3. commands.py

```python
"""Telegram command handlers.

Commands available to operator:
  /status     — pipeline status (how many videos in each stage)
  /pause      — pause all workers (set PAUSED flag)
  /resume     — resume workers
  /budget     — show today's LLM budget usage
  /alerts     — show unresolved alerts summary
  /health     — system health (DB, Redis, RabbitMQ, NAS)
  /help       — list available commands

Usage:
    handler = CommandHandler(bot=telegram_bot)
    handler.register_all(application)  # Register with telegram Application
"""

from telegram import Update
from telegram.ext import ContextTypes, CommandHandler as TGCommandHandler
import structlog

logger = structlog.get_logger()

# Command definitions — for /help display
COMMANDS = {
    "status": "Pipeline status — videos in each stage",
    "pause": "Pause all workers",
    "resume": "Resume all workers",
    "budget": "Today's LLM budget usage",
    "alerts": "Show unresolved alerts",
    "health": "System health check",
    "help": "Show this help message",
}

class CommandRouter:
    """Route Telegram commands to handler functions.
    
    Args:
        bot: TelegramBot instance for sending responses
        
    Dependencies injected via set_dependencies():
        - db_session_factory: for querying pipeline counts, alerts
        - redis_client: for checking health
        - settings: for budget info
    """
    
    def __init__(self, bot: "TelegramBot"):
        self.bot = bot
        self._db_factory = None
        self._redis = None
        self._settings = None
        self._paused = False  # Global pause flag
    
    def set_dependencies(
        self,
        db_session_factory=None,
        redis_client=None,
        settings=None,
    ) -> None:
        """Inject dependencies. Called after all services initialized."""
        self._db_factory = db_session_factory
        self._redis = redis_client
        self._settings = settings
    
    async def handle_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /status command.
        
        Steps:
        1. Query VideoRepository.get_pipeline_counts()
        2. Format with AlertFormatter.format_pipeline_status()
        3. Reply to user
        
        If dependencies not set → reply "System initializing..."
        """
    
    async def handle_pause(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /pause command.
        
        Steps:
        1. Set self._paused = True
        2. Set Redis key "omnicast:paused" = "1"
        3. Reply: "⏸ All workers paused"
        4. Log: "System paused by operator"
        """
    
    async def handle_resume(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /resume command.
        
        Steps:
        1. Set self._paused = False
        2. Delete Redis key "omnicast:paused"
        3. Reply: "▶️ Workers resumed"
        4. Log: "System resumed by operator"
        """
    
    async def handle_budget(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /budget command.
        
        Steps:
        1. Query ExpenseRepository.sum_by_category(today, today)
        2. Calculate remaining from settings.daily_llm_budget_usd
        3. Format with AlertFormatter.format_budget_status()
        4. Reply
        """
    
    async def handle_alerts(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /alerts command.
        
        Steps:
        1. Query AlertRepository.get_unresolved(limit=10)
        2. Format summary: count by severity
        3. Reply with summary + most recent 5 alerts
        """
    
    async def handle_health(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /health command.
        
        Check each service and report:
        - PostgreSQL: try get_engine().connect()
        - Redis: try ping()
        - RabbitMQ: check connection status
        - NAS: check NASHealthChecker.is_healthy
        
        Format:
        ```
        🏥 System Health
        
        ✅ PostgreSQL — connected
        ✅ Redis — connected
        ⚠️ RabbitMQ — reconnecting
        ❌ NAS — unavailable (using local fallback)
        ```
        """
    
    async def handle_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /help command.
        
        List all available commands from COMMANDS dict.
        """
    
    def get_handlers(self) -> list[TGCommandHandler]:
        """Return list of telegram CommandHandler objects.
        
        Map each command string to its handler method.
        Used by Application.add_handlers().
        """
        return [
            TGCommandHandler("status", self.handle_status),
            TGCommandHandler("pause", self.handle_pause),
            TGCommandHandler("resume", self.handle_resume),
            TGCommandHandler("budget", self.handle_budget),
            TGCommandHandler("alerts", self.handle_alerts),
            TGCommandHandler("health", self.handle_health),
            TGCommandHandler("help", self.handle_help),
        ]
```

## 4. alert_manager.py

```python
"""Alert Manager — dedup, throttle, quiet hours, escalation.

Central alert pipeline:
  Event → AlertManager.send() → dedup → quiet hours → throttle → send

Usage:
    manager = AlertManager(
        bot=telegram_bot,
        settings=settings,
    )
    await manager.send(alert_message)
    
    # Periodic tasks:
    await manager.check_escalations()  # Call every 5 min
    await manager.send_daily_digest()  # Call at end of day
"""

from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo
from collections import defaultdict
import hashlib
from omnicast.models.schemas import AlertMessage
import structlog

logger = structlog.get_logger()

class AlertManager:
    """Centralized alert management with dedup and throttle.
    
    Args:
        bot: TelegramBot instance
        quiet_start: quiet hours start (default "23:00")
        quiet_end: quiet hours end (default "07:00")
        quiet_tz: timezone for quiet hours (default "Asia/Ho_Chi_Minh")
        max_alerts_per_hour: throttle limit (default 30)
        escalation_interval_minutes: re-alert unresolved criticals (default 30)
    """
    
    def __init__(
        self,
        bot: "TelegramBot",
        quiet_start: str = "23:00",
        quiet_end: str = "07:00",
        quiet_tz: str = "Asia/Ho_Chi_Minh",
        max_alerts_per_hour: int = 30,
        escalation_interval_minutes: int = 30,
    ):
        self.bot = bot
        self.quiet_start = time.fromisoformat(quiet_start)
        self.quiet_end = time.fromisoformat(quiet_end)
        self.quiet_tz = ZoneInfo(quiet_tz)
        self.max_alerts_per_hour = max_alerts_per_hour
        self.escalation_interval = escalation_interval_minutes
        
        # Dedup state
        self._fingerprints: dict[str, dict] = {}
        # {fingerprint: {"count": int, "first_seen": datetime, "last_message_id": int}}
        
        # Throttle state
        self._hourly_count: int = 0
        self._hour_start: datetime | None = None
        
        # Pending alerts (queued during quiet hours)
        self._pending: list[AlertMessage] = []
    
    def _compute_fingerprint(self, alert: AlertMessage) -> str:
        """Compute dedup fingerprint from alert source + message.
        
        fingerprint = md5(f"{alert.source}:{alert.message}").hexdigest()[:12]
        
        Same source + same message = same fingerprint = deduplicated.
        Different details are OK (e.g. different video_id with same error).
        """
    
    def _is_quiet_hours(self) -> bool:
        """Check if current time is within quiet hours.
        
        Handle midnight crossing:
        - If quiet_start > quiet_end (e.g. 23:00-07:00):
          → quiet if now >= start OR now < end
        - If quiet_start < quiet_end (e.g. 01:00-06:00):
          → quiet if start <= now < end
        
        Use self.quiet_tz for timezone conversion.
        """
    
    def _is_throttled(self) -> bool:
        """Check if hourly alert limit reached.
        
        Steps:
        1. If _hour_start is None or > 1 hour ago:
           - Reset _hourly_count = 0
           - Set _hour_start = now
        2. Return _hourly_count >= max_alerts_per_hour
        """
    
    async def send(self, alert: AlertMessage) -> None:
        """Main alert pipeline entry point.
        
        Flow:
        1. Compute fingerprint
        2. DEDUP CHECK:
           - If fingerprint seen in last 1 hour:
             - Increment count
             - If count % 10 == 0: update original message with suppression notice
             - Log: "Suppressed duplicate alert" with count
             - Return (don't send)
           - Else: record fingerprint
        
        3. QUIET HOURS CHECK:
           - If quiet hours AND severity != "critical" AND severity != "emergency":
             - Add to _pending list
             - Log: "Alert queued (quiet hours)"
             - Return
        
        4. THROTTLE CHECK:
           - If throttled AND severity != "critical":
             - Add to _pending list
             - Log: "Alert throttled"
             - Return
        
        5. SEND:
           - Format with AlertFormatter.format_alert()
           - message_id = await bot.send_text(formatted)
           - Store message_id in fingerprint entry (for dedup updates)
           - Increment _hourly_count
           - Log: "Alert sent" with severity, source
        """
    
    async def flush_pending(self) -> int:
        """Send all pending alerts (called when quiet hours end).
        
        Steps:
        1. Copy _pending, clear original
        2. For each pending alert:
           - Skip if stale (> 6 hours old)
           - Send via bot (with "(delayed)" tag)
        3. Return count of sent alerts
        4. Log: "Flushed {count} pending alerts"
        """
    
    async def check_escalations(self) -> None:
        """Re-alert unresolved critical alerts.
        
        Called periodically (every 5 min).
        
        Steps:
        1. Query AlertRepository.get_unresolved(severity="critical")
        2. For each unresolved alert:
           - If age > escalation_interval and not recently re-alerted:
             - Send escalation: "🔴 ESCALATION — unresolved for {minutes}m: {message}"
             - Update last_escalation timestamp
        3. Log: "Escalation check: {count} alerts escalated"
        """
    
    async def send_daily_digest(self, stats: dict) -> None:
        """Send end-of-day digest.
        
        Args:
            stats: dict matching AlertFormatter.format_daily_digest() expected format
        
        Steps:
        1. Format with AlertFormatter.format_daily_digest()
        2. Send via bot with disable_notification=True (don't ping at EOD)
        3. Clear fingerprint cache (fresh start next day)
        4. Reset hourly throttle
        5. Log: "Daily digest sent"
        """
    
    async def cleanup_stale_fingerprints(self) -> int:
        """Remove fingerprints older than 2 hours.
        
        Called periodically to prevent memory growth.
        Return count of removed entries.
        """
    
    def get_stats(self) -> dict:
        """Return alert manager stats for monitoring.
        
        Return:
            {
                "active_fingerprints": int,
                "pending_count": int,
                "hourly_count": int,
                "is_quiet_hours": bool,
                "is_throttled": bool,
            }
        """
```

## 5. __init__.py

```python
"""Telegram bot and alert management.

Usage:
    from omnicast.telegram import TelegramBot, AlertManager, CommandRouter
    
    bot = TelegramBot(token=settings.telegram_bot_token, chat_id=settings.telegram_chat_id)
    manager = AlertManager(bot=bot)
    commands = CommandRouter(bot=bot)
"""

from omnicast.telegram.bot import TelegramBot
from omnicast.telegram.formatter import AlertFormatter
from omnicast.telegram.commands import CommandRouter
from omnicast.telegram.alert_manager import AlertManager

__all__ = [
    "TelegramBot",
    "AlertFormatter",
    "CommandRouter",
    "AlertManager",
]
```

## 6. Tests

### tests/unit/test_telegram.py

```python
"""Test Telegram bot and alert manager.

=== AlertFormatter Tests ===

test_escape_markdown():
    - Input: "hello_world *bold* (test)"
    - Output: "hello\\_world \\*bold\\* \\(test\\)"

test_format_alert_critical():
    - AlertMessage(severity="critical", source="pipeline", message="Render failed")
    - Result contains "🔴", "CRITICAL", "pipeline", "Render failed"
    - Result is valid MarkdownV2 (no unescaped special chars in dynamic text)

test_format_alert_with_details():
    - AlertMessage with details={"video_id": "v001", "error": "OOM"}
    - Result contains "Details:" section with key-value pairs

test_format_daily_digest():
    - stats dict with all fields
    - Result contains "Daily Digest", video counts, cost

test_format_pipeline_status():
    - counts = {"scripting": 3, "rendering": 5}
    - Result contains "Scripting: 3", "Rendering: 5"

test_format_budget_status():
    - budget with 80% used
    - Result contains warning indicator

test_format_suppressed_notice():
    - original + count=15
    - Result contains "Suppressed 15 duplicate"

=== TelegramBot Tests (mocked) ===

test_send_text_success(mocker):
    - Mock Bot.send_message → return message with id=123
    - result = await bot.send_text("test")
    - assert result == 123

test_send_text_failure_returns_none(mocker):
    - Mock Bot.send_message → raise TelegramError
    - result = await bot.send_text("test")
    - assert result is None (don't crash)

test_send_text_truncates_long_message(mocker):
    - Send 5000 char message
    - Verify send_message called (possibly multiple times for split)

test_health_check_success(mocker):
    - Mock Bot.get_me → return User
    - assert await bot.health_check() is True

test_health_check_failure(mocker):
    - Mock Bot.get_me → raise TelegramError
    - assert await bot.health_check() is False

=== AlertManager Tests ===

test_send_normal_alert(mocker):
    - Mock bot.send_text
    - await manager.send(alert_message)
    - bot.send_text called once

test_dedup_suppresses_duplicate():
    - Send same alert (same source + message) twice
    - bot.send_text called only once
    - Second call suppressed

test_dedup_allows_different_alerts():
    - Send alert with source="pipeline", message="error A"
    - Send alert with source="pipeline", message="error B"
    - bot.send_text called twice (different fingerprints)

test_dedup_updates_on_10th():
    - Send same alert 10 times
    - bot.send_text called once (initial)
    - bot.edit_message called once (10th occurrence update)

test_quiet_hours_queues_non_critical():
    - Set time to 23:30 (quiet hours)
    - Send severity="medium" alert
    - bot.send_text NOT called
    - manager._pending has 1 entry

test_quiet_hours_allows_critical():
    - Set time to 23:30 (quiet hours)
    - Send severity="critical" alert
    - bot.send_text called (bypasses quiet hours)

test_quiet_hours_midnight_crossing():
    - quiet_start=23:00, quiet_end=07:00
    - Test at 00:30 → is quiet
    - Test at 08:00 → not quiet
    - Test at 22:00 → not quiet

test_throttle_limits_per_hour():
    - Set max_alerts_per_hour=5
    - Send 6 different alerts
    - First 5 sent, 6th queued

test_throttle_allows_critical():
    - At throttle limit
    - Send severity="critical"
    - Still sent (bypasses throttle)

test_flush_pending():
    - Queue 3 alerts in pending
    - await manager.flush_pending()
    - bot.send_text called 3 times
    - _pending is empty

test_flush_skips_stale():
    - Queue alert with timestamp > 6 hours ago
    - await manager.flush_pending()
    - bot.send_text NOT called for stale alert

test_daily_digest(mocker):
    - Mock bot.send_text
    - await manager.send_daily_digest(stats)
    - bot.send_text called with disable_notification=True

test_cleanup_stale_fingerprints():
    - Add fingerprint with first_seen > 2 hours ago
    - count = await manager.cleanup_stale_fingerprints()
    - assert count == 1
    - Old fingerprint removed

test_get_stats():
    - stats = manager.get_stats()
    - assert "active_fingerprints" in stats
    - assert "is_quiet_hours" in stats

=== CommandRouter Tests ===

test_handle_help(mocker):
    - Mock Update with reply_text
    - await router.handle_help(update, context)
    - reply contains all command names

test_handle_pause(mocker):
    - Mock Redis
    - await router.handle_pause(update, context)
    - Redis key "omnicast:paused" set to "1"
    - reply contains "paused"

test_handle_resume(mocker):
    - await router.handle_resume(update, context)
    - Redis key deleted
    - reply contains "resumed"

test_handle_status_no_deps():
    - Don't call set_dependencies()
    - await router.handle_status(update, context)
    - Reply: "System initializing..."

test_get_handlers():
    - handlers = router.get_handlers()
    - assert len(handlers) == 7
    - All commands have corresponding handlers
"""
```

## 7. DO NOT

- ❌ Đừng raise exceptions trong bot.send_* — alert failures phải silent (log only)
- ❌ Đừng gửi alerts không qua AlertManager — tất cả phải qua dedup pipeline
- ❌ Đừng ignore quiet hours cho non-critical alerts
- ❌ Đừng store dedup state trong Redis (Phase 1) — in-memory dict đủ cho single Master
- ❌ Đừng dùng HTML parse_mode — dùng MarkdownV2 (consistent)
- ❌ Đừng gửi unescaped text — dynamic content phải escape_markdown()
- ❌ Đừng block pipeline nếu Telegram API down — best-effort delivery

## 8. Acceptance Criteria

```bash
uv run pytest tests/unit/test_telegram.py -v
uv run pyright src/omnicast/telegram/

# Manual test (requires real bot token):
uv run python -c "
import asyncio
from omnicast.telegram.bot import TelegramBot
bot = TelegramBot(token='TEST_TOKEN', chat_id='TEST_CHAT')
asyncio.run(bot.health_check())
"
```
