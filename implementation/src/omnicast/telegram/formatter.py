"""Format alert messages for Telegram (MarkdownV2).

Telegram MarkdownV2 requires escaping: _ * [ ] ( ) ~ ` > # + - = | { } . !

Usage:
    msg = AlertFormatter.format_alert(alert_message)
    msg = AlertFormatter.format_daily_digest(stats)
    msg = AlertFormatter.format_pipeline_status(pipeline_counts)
"""

from __future__ import annotations

from zoneinfo import ZoneInfo

from omnicast.models.schemas import AlertMessage

# Severity → emoji mapping
SEVERITY_EMOJI: dict[str, str] = {
    "critical": "🔴",
    "high": "🟠",
    "medium": "🟡",
    "low": "🟢",
    "info": "ℹ️",
}

_VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")

# MarkdownV2 special chars that must be escaped
_MD_SPECIAL = r"_*[]()~`>#+-=|{}.!"


class AlertFormatter:
    """Static methods for formatting Telegram messages."""

    @staticmethod
    def escape_markdown(text: str) -> str:
        """Escape special chars for MarkdownV2.

        Must escape: _ * [ ] ( ) ~ ` > # + - = | { } . !
        """
        result = []
        for char in text:
            if char in _MD_SPECIAL:
                result.append(f"\\{char}")
            else:
                result.append(char)
        return "".join(result)

    @staticmethod
    def format_alert(alert: AlertMessage) -> str:
        """Format AlertMessage for Telegram MarkdownV2.

        Template:
            {emoji} *{SEVERITY}* — {source}

            {message}

            📋 Details:
            {key: value for each detail}

            🕐 {timestamp}
        """
        severity_str = str(alert.severity).lower()
        emoji = SEVERITY_EMOJI.get(severity_str, "📢")
        severity_upper = AlertFormatter.escape_markdown(str(alert.severity).upper())
        source = AlertFormatter.escape_markdown(str(alert.source))
        message = AlertFormatter.escape_markdown(str(alert.message))

        ts = alert.timestamp.astimezone(_VN_TZ)
        ts_str = AlertFormatter.escape_markdown(ts.strftime("%Y-%m-%d %H:%M:%S %Z"))

        lines = [f"{emoji} *{severity_upper}* — {source}", "", message]

        if alert.details:
            lines.append("")
            lines.append("📋 Details:")
            for k, v in alert.details.items():
                key = str(k)  # keys are clean identifiers, no escaping needed
                val = AlertFormatter.escape_markdown(str(v))
                lines.append(f"  {key}: {val}")

        lines.append("")
        lines.append(f"🕐 {ts_str}")

        return "\n".join(lines)

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
        """
        date_str = AlertFormatter.escape_markdown(str(stats.get("date", "N/A")))
        produced = stats.get("videos_produced", 0)
        uploaded = stats.get("videos_uploaded", 0)
        failed = stats.get("videos_failed", 0)
        errors = stats.get("total_errors", 0)
        expenses = stats.get("total_expenses_usd", 0.0)
        llm_cost = stats.get("llm_cost_usd", 0.0)
        unresolved = stats.get("unresolved_alerts", 0)
        top_channels: list[dict] = stats.get("top_channels", [])

        expenses_str = AlertFormatter.escape_markdown(f"{expenses:.2f}")
        llm_str = AlertFormatter.escape_markdown(f"{llm_cost:.2f}")

        lines = [
            f"📊 *Daily Digest — {date_str}*",
            "",
            f"🎬 Videos: {produced} produced, {uploaded} uploaded, {failed} failed",
            f"💰 Cost: \\${expenses_str} \\(LLM: \\${llm_str}\\)",
            f"⚠️ Errors: {errors} total, {unresolved} unresolved",
        ]

        if top_channels:
            lines.append("")
            lines.append("🏆 Top Channels:")
            for i, ch in enumerate(top_channels[:5], 1):
                ch_id = str(ch.get("channel_id", ""))
                count = ch.get("videos_count", 0)
                lines.append(f"{i}\\. {ch_id} — {count} videos")

        return "\n".join(lines)

    @staticmethod
    def format_pipeline_status(counts: dict[str, int]) -> str:
        """Format pipeline status response.

        Expected counts: {"scripting": 3, "rendering": 5, "uploading": 1, ...}
        """
        _STAGE_LABELS = {
            "scripting": "✍️ Scripting",
            "rendering": "🎨 Rendering",
            "uploading": "📤 Uploading",
            "quality_check": "✅ Quality Check",
            "failed": "❌ Failed",
        }

        lines = ["📊 *Pipeline Status*", ""]
        total = 0

        for key, label in _STAGE_LABELS.items():
            n = counts.get(key, 0)
            total += n
            lines.append(f"{label}: {n}")

        # Extra keys not in standard map
        for key, n in counts.items():
            if key not in _STAGE_LABELS:
                label = AlertFormatter.escape_markdown(key.replace("_", " ").title())
                lines.append(f"{label}: {n}")
                total += n

        lines.append("")
        lines.append(f"Total in pipeline: {total}")
        return "\n".join(lines)

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
        """
        limit = budget.get("daily_limit_usd", 0.0)
        spent = budget.get("spent_today_usd", 0.0)
        remaining = budget.get("remaining_usd", 0.0)
        percent = budget.get("percent_used", 0.0)

        limit_str = AlertFormatter.escape_markdown(f"{limit:.2f}")
        spent_str = AlertFormatter.escape_markdown(f"{spent:.2f}")
        remaining_str = AlertFormatter.escape_markdown(f"{remaining:.2f}")
        percent_str = AlertFormatter.escape_markdown(f"{percent:.1f}")

        lines = [
            "💰 *Budget Status*",
            "",
            f"Daily limit: \\${limit_str}",
            f"Spent today: \\${spent_str} \\({percent_str}%\\)",
            f"Remaining: \\${remaining_str}",
        ]

        if percent > 80:
            lines.append("")
            lines.append("⚠️ *WARNING: Budget 80% consumed\\!*")

        return "\n".join(lines)

    @staticmethod
    def format_suppressed_notice(
        original_message: str,
        suppressed_count: int,
    ) -> str:
        """Append suppression notice to original alert message."""
        return f"{original_message}\n\n🔇 _Suppressed {suppressed_count} duplicate alerts_"
