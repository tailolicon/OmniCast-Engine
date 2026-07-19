"""Extended Telegram commands for dashboard data access.
Adds to Phase 1 bot: /pipeline, /workers, /dlq, /tokens, /compliance."""

from __future__ import annotations
import structlog
from telegram import Update
from telegram.ext import ContextTypes
from omnicast.dashboard.data_service import DashboardDataService

logger = structlog.get_logger()


class DashboardCommandHandler:
    """Telegram command handlers that query DashboardDataService."""

    def __init__(self, data_service: DashboardDataService) -> None:
        self.data_service = data_service

    async def cmd_pipeline(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Show pipeline status summary."""
        kpis = self.data_service.get_kpis()
        items = self.data_service.get_pipeline_items()

        msg = f"""📊 *Pipeline Status*

*KPIs:*
• Videos Today: {kpis.videos_today}
• Queue Depth: {kpis.queue_depth}
• System Health: {kpis.system_health:.1f}%

*Active Items:* {len(items)}
"""
        for item in items[:5]:  # Show top 5
            msg += f"• {item.video_id}: {item.status} ({item.progress_pct:.0f}%)\n"

        await update.message.reply_text(msg, parse_mode="Markdown")

    async def cmd_workers(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Show worker health status."""
        workers = self.data_service.get_worker_statuses()

        msg = "🖥️ *Worker Status*\n\n"
        for w in workers:
            status_emoji = "🟢" if w.status == "healthy" else "🟡" if w.status == "degraded" else "🔴"
            msg += f"{status_emoji} *{w.hostname}*\n"
            msg += f"  CPU: {w.cpu_percent:.1f}% | RAM: {w.ram_percent:.1f}%\n"
            if w.gpu_temp:
                msg += f"  GPU: {w.gpu_temp:.1f}°C\n"
            msg += f"  Task: {w.current_task or 'Idle'}\n\n"

        await update.message.reply_text(msg, parse_mode="Markdown")

    async def cmd_dlq(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Show DLQ count and top items."""
        items = self.data_service.get_dlq_items(limit=3)

        msg = f"🚨 *Dead Letter Queue*\n\n"
        msg += f"Total Items: {len(items)}\n\n"

        for item in items:
            msg += f"• *{item.item_id}* ({item.queue_name})\n"
            msg += f"  Error: {item.error_message}\n"
            msg += f"  Retries: {item.retry_count}\n\n"

        await update.message.reply_text(msg, parse_mode="Markdown")

    async def cmd_tokens(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Show OAuth token status (never token values)."""
        tokens = self.data_service.get_token_statuses()

        msg = "🔑 *OAuth Token Status*\n\n"
        for t in tokens:
            status_emoji = "🟢" if t.status == "healthy" else "🟡" if t.status == "warning" else "🔴"
            msg += f"{status_emoji} *{t.channel_name}*\n"
            msg += f"  Status: {t.status}\n"
            msg += f"  Scopes: {len(t.scopes)} permissions\n\n"

        await update.message.reply_text(msg, parse_mode="Markdown")

    async def cmd_compliance(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Show recent compliance checks."""
        log = self.data_service.get_compliance_log()

        msg = "✅ *Compliance Audit*\n\n"
        for entry in log[:5]:  # Show top 5
            status_emoji = "✅" if entry.passed else "❌"
            msg += f"{status_emoji} *{entry.video_id}*\n"
            msg += f"  Channel: {entry.channel_id}\n"
            msg += f"  Violations: {len(entry.violations)}\n\n"

        await update.message.reply_text(msg, parse_mode="Markdown")

    def register(self, application) -> None:
        """Register all dashboard command handlers."""
        from telegram.ext import CommandHandler

        application.add_handler(CommandHandler("pipeline", self.cmd_pipeline))
        application.add_handler(CommandHandler("workers", self.cmd_workers))
        application.add_handler(CommandHandler("dlq", self.cmd_dlq))
        application.add_handler(CommandHandler("tokens", self.cmd_tokens))
        application.add_handler(CommandHandler("compliance", self.cmd_compliance))
