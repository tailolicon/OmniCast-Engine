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
    handler = CommandRouter(bot=telegram_bot)
    handlers = handler.get_handlers()  # Register with telegram Application
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

import structlog
from telegram import Update
from telegram.ext import CommandHandler as TGCommandHandler
from telegram.ext import ContextTypes

from omnicast.telegram.formatter import AlertFormatter

if TYPE_CHECKING:
    from omnicast.telegram.bot import TelegramBot

logger = structlog.get_logger()

# Command definitions — for /help display
COMMANDS: dict[str, str] = {
    "status": "Pipeline status — videos in each stage",
    "pause": "Pause all workers",
    "resume": "Resume all workers",
    "budget": "Today's LLM budget usage",
    "alerts": "Show unresolved alerts",
    "health": "System health check",
    "help": "Show this help message",
}

_NOT_INIT = "System initializing\\.\\.\\."


class CommandRouter:
    """Route Telegram commands to handler functions.

    Args:
        bot: TelegramBot instance for sending responses

    Dependencies injected via set_dependencies():
        - db_session_factory: for querying pipeline counts, alerts
        - redis_client: for checking health
        - settings: for budget info
    """

    def __init__(self, bot: TelegramBot) -> None:
        self.bot = bot
        self._db_factory = None
        self._redis = None
        self._settings = None
        self._paused: bool = False

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

    async def handle_status(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle /status command."""
        if not self._db_factory:
            await update.message.reply_text("System initializing...")
            return
        try:
            from omnicast.db.repositories import VideoRepository

            async with self._db_factory() as session:
                repo = VideoRepository(session)
                counts = await repo.get_pipeline_counts()
            text = AlertFormatter.format_pipeline_status(counts)
            await update.message.reply_text(text, parse_mode="MarkdownV2")
        except Exception as exc:
            logger.error("handle_status failed", error=str(exc))
            await update.message.reply_text("Failed to get status")

    async def handle_pause(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle /pause command."""
        self._paused = True
        if self._redis:
            await self._redis.set("omnicast:paused", "1")
        logger.info("System paused by operator")
        await update.message.reply_text("⏸ All workers paused")

    async def handle_resume(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle /resume command."""
        self._paused = False
        if self._redis:
            await self._redis.delete("omnicast:paused")
        logger.info("System resumed by operator")
        await update.message.reply_text("▶️ Workers resumed")

    async def handle_budget(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle /budget command."""
        if not self._db_factory:
            await update.message.reply_text("System initializing...")
            return
        try:
            from omnicast.db.repositories import ExpenseRepository

            today = date.today()
            async with self._db_factory() as session:
                repo = ExpenseRepository(session)
                sums = await repo.sum_by_category(today, today)

            total = sum(sums.values())
            daily_limit: float = (
                getattr(self._settings, "daily_llm_budget_usd", 50.0)
                if self._settings
                else 50.0
            )
            remaining = daily_limit - total
            percent = (total / daily_limit * 100) if daily_limit > 0 else 0.0

            budget = {
                "daily_limit_usd": daily_limit,
                "spent_today_usd": total,
                "remaining_usd": remaining,
                "percent_used": percent,
            }
            text = AlertFormatter.format_budget_status(budget)
            await update.message.reply_text(text, parse_mode="MarkdownV2")
        except Exception as exc:
            logger.error("handle_budget failed", error=str(exc))
            await update.message.reply_text("Failed to get budget")

    async def handle_alerts(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle /alerts command."""
        if not self._db_factory:
            await update.message.reply_text("System initializing...")
            return
        try:
            from omnicast.db.repositories import AlertRepository

            async with self._db_factory() as session:
                repo = AlertRepository(session)
                alerts = await repo.get_unresolved(limit=10)

            if not alerts:
                await update.message.reply_text("✅ No unresolved alerts")
                return

            by_severity: dict[str, int] = {}
            for a in alerts:
                sev = str(a.severity)
                by_severity[sev] = by_severity.get(sev, 0) + 1

            lines = [f"Total unresolved: {len(alerts)}\n"]
            for sev, cnt in sorted(by_severity.items()):
                lines.append(f"  {sev}: {cnt}")
            lines.append("")
            lines.append("Latest 5:")
            for a in alerts[:5]:
                lines.append(f"  [{a.severity}] {a.source}: {a.message[:60]}")

            await update.message.reply_text("\n".join(lines))
        except Exception as exc:
            logger.error("handle_alerts failed", error=str(exc))
            await update.message.reply_text("Failed to get alerts")

    async def handle_health(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle /health command."""
        lines = ["🏥 System Health", ""]

        # PostgreSQL
        try:
            if self._db_factory:
                from omnicast.db.engine import get_engine

                engine = get_engine()
                async with engine.connect() as conn:
                    await conn.close()
                lines.append("✅ PostgreSQL — connected")
            else:
                lines.append("⚠️ PostgreSQL — not initialized")
        except Exception:
            lines.append("❌ PostgreSQL — error")

        # Redis
        try:
            if self._redis:
                await self._redis.ping()
                lines.append("✅ Redis — connected")
            else:
                lines.append("⚠️ Redis — not initialized")
        except Exception:
            lines.append("❌ Redis — error")

        lines.append("ℹ️ RabbitMQ — status unknown")
        lines.append("ℹ️ NAS — status unknown")

        await update.message.reply_text("\n".join(lines))

    async def handle_help(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle /help command."""
        lines = ["Available commands:", ""]
        for cmd, desc in COMMANDS.items():
            lines.append(f"/{cmd} — {desc}")
        await update.message.reply_text("\n".join(lines))

    def get_handlers(self) -> list[TGCommandHandler]:
        """Return list of telegram CommandHandler objects."""
        return [
            TGCommandHandler("status", self.handle_status),
            TGCommandHandler("pause", self.handle_pause),
            TGCommandHandler("resume", self.handle_resume),
            TGCommandHandler("budget", self.handle_budget),
            TGCommandHandler("alerts", self.handle_alerts),
            TGCommandHandler("health", self.handle_health),
            TGCommandHandler("help", self.handle_help),
        ]
