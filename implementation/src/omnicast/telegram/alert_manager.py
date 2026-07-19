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

from __future__ import annotations

import hashlib
from datetime import datetime, time, timezone
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

import structlog

from omnicast.models.schemas import AlertMessage
from omnicast.telegram.formatter import AlertFormatter

if TYPE_CHECKING:
    from omnicast.telegram.bot import TelegramBot

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
        bot: TelegramBot,
        quiet_start: str = "23:00",
        quiet_end: str = "07:00",
        quiet_tz: str = "Asia/Ho_Chi_Minh",
        max_alerts_per_hour: int = 30,
        escalation_interval_minutes: int = 30,
    ) -> None:
        self.bot = bot
        self.quiet_start = time.fromisoformat(quiet_start)
        self.quiet_end = time.fromisoformat(quiet_end)
        self.quiet_tz = ZoneInfo(quiet_tz)
        self.max_alerts_per_hour = max_alerts_per_hour
        self.escalation_interval = escalation_interval_minutes

        # Dedup state: fingerprint → {"count": int, "first_seen": datetime, "last_message_id": int|None}
        self._fingerprints: dict[str, dict] = {}

        # Throttle state
        self._hourly_count: int = 0
        self._hour_start: datetime | None = None

        # Pending alerts (queued during quiet hours or throttle)
        self._pending: list[AlertMessage] = []

    def _compute_fingerprint(self, alert: AlertMessage) -> str:
        """Compute dedup fingerprint from alert source + message.

        fingerprint = md5(f"{alert.source}:{alert.message}").hexdigest()[:12]
        """
        raw = f"{alert.source}:{alert.message}"
        return hashlib.md5(raw.encode()).hexdigest()[:12]

    def _is_quiet_hours(self) -> bool:
        """Check if current time is within quiet hours.

        Handle midnight crossing (e.g. 23:00-07:00).
        """
        now = datetime.now(self.quiet_tz).time()
        if self.quiet_start > self.quiet_end:
            # Crosses midnight (e.g. 23:00-07:00)
            return now >= self.quiet_start or now < self.quiet_end
        # Same-day range (e.g. 01:00-06:00)
        return self.quiet_start <= now < self.quiet_end

    def _is_throttled(self) -> bool:
        """Check if hourly alert limit reached.

        Resets counter when hour window expires.
        """
        now = datetime.now(timezone.utc)
        if self._hour_start is None or (now - self._hour_start).total_seconds() > 3600:
            self._hourly_count = 0
            self._hour_start = now
        return self._hourly_count >= self.max_alerts_per_hour

    async def send(self, alert: AlertMessage) -> None:
        """Main alert pipeline entry point.

        Flow: dedup → quiet hours → throttle → send
        """
        fingerprint = self._compute_fingerprint(alert)
        now = datetime.now(timezone.utc)

        # DEDUP CHECK
        if fingerprint in self._fingerprints:
            entry = self._fingerprints[fingerprint]
            age = (now - entry["first_seen"]).total_seconds()
            if age < 3600:
                entry["count"] += 1
                if entry["count"] % 10 == 0 and entry.get("last_message_id"):
                    # Update original message with suppression notice
                    original_fmt = AlertFormatter.format_alert(alert)
                    updated = AlertFormatter.format_suppressed_notice(
                        original_fmt, entry["count"]
                    )
                    await self.bot.edit_message(entry["last_message_id"], updated)
                logger.info(
                    "Suppressed duplicate alert",
                    fingerprint=fingerprint,
                    count=entry["count"],
                )
                return

        # Record fingerprint (reset or new)
        self._fingerprints[fingerprint] = {
            "count": 1,
            "first_seen": now,
            "last_message_id": None,
        }

        severity_str = str(alert.severity).lower()
        is_critical = severity_str in ("critical", "emergency")

        # QUIET HOURS CHECK
        if self._is_quiet_hours() and not is_critical:
            self._pending.append(alert)
            logger.info(
                "Alert queued (quiet hours)",
                source=alert.source,
                severity=severity_str,
            )
            return

        # THROTTLE CHECK
        if self._is_throttled() and not is_critical:
            self._pending.append(alert)
            logger.info(
                "Alert throttled", source=alert.source, severity=severity_str
            )
            return

        # SEND
        formatted = AlertFormatter.format_alert(alert)
        message_id = await self.bot.send_text(formatted)
        self._fingerprints[fingerprint]["last_message_id"] = message_id
        self._hourly_count += 1
        logger.info("Alert sent", severity=severity_str, source=alert.source)

    async def flush_pending(self) -> int:
        """Send all pending alerts (called when quiet hours end).

        Skips alerts older than 6 hours.
        Returns count of actually sent alerts.
        """
        pending = list(self._pending)
        self._pending.clear()

        now = datetime.now(timezone.utc)
        sent = 0

        for alert in pending:
            age = (now - alert.timestamp).total_seconds()
            if age > 6 * 3600:
                logger.info("Skipping stale pending alert", age_hours=round(age / 3600, 1))
                continue
            formatted = AlertFormatter.format_alert(alert)
            delayed_text = f"🕐 _\\[delayed\\]_\n{formatted}"
            await self.bot.send_text(delayed_text)
            sent += 1

        logger.info("Flushed pending alerts", count=sent)
        return sent

    async def check_escalations(self) -> None:
        """Re-alert unresolved critical alerts.

        Called periodically (every 5 min).
        In production, caller should pass AlertRepository.get_unresolved(severity="critical").
        This implementation tracks escalations via fingerprint state.
        """
        now = datetime.now(timezone.utc)
        escalated = 0

        for fingerprint, entry in self._fingerprints.items():
            if entry.get("severity") != "critical":
                continue
            age_minutes = (now - entry["first_seen"]).total_seconds() / 60
            last_escalation: datetime | None = entry.get("last_escalation")
            minutes_since_escalation = (
                (now - last_escalation).total_seconds() / 60
                if last_escalation
                else float("inf")
            )
            if age_minutes > self.escalation_interval and minutes_since_escalation > self.escalation_interval:
                msg = AlertFormatter.escape_markdown(
                    f"🔴 ESCALATION — unresolved for {int(age_minutes)}m"
                )
                await self.bot.send_text(msg)
                entry["last_escalation"] = now
                escalated += 1

        logger.info("Escalation check complete", alerts_escalated=escalated)

    async def send_daily_digest(self, stats: dict) -> None:
        """Send end-of-day digest.

        Args:
            stats: dict matching AlertFormatter.format_daily_digest() expected format
        """
        formatted = AlertFormatter.format_daily_digest(stats)
        await self.bot.send_text(formatted, disable_notification=True)
        # Clear state for fresh start next day
        self._fingerprints.clear()
        self._hourly_count = 0
        self._hour_start = None
        logger.info("Daily digest sent")

    async def cleanup_stale_fingerprints(self) -> int:
        """Remove fingerprints older than 2 hours.

        Called periodically to prevent memory growth.
        Returns count of removed entries.
        """
        now = datetime.now(timezone.utc)
        stale = [
            fp
            for fp, entry in self._fingerprints.items()
            if (now - entry["first_seen"]).total_seconds() > 2 * 3600
        ]
        for fp in stale:
            del self._fingerprints[fp]
        return len(stale)

    def get_stats(self) -> dict:
        """Return alert manager stats for monitoring."""
        return {
            "active_fingerprints": len(self._fingerprints),
            "pending_count": len(self._pending),
            "hourly_count": self._hourly_count,
            "is_quiet_hours": self._is_quiet_hours(),
            "is_throttled": self._is_throttled(),
        }
