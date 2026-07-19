"""Channel Guard — velocity limiter + strike kill-switch.

TWO SAFETY MECHANISMS:

[A] Upload Velocity Limiter
  YouTube spam signal = many uploads in short time from a new channel.
  Rules (Gemini / YouTube Creator guidelines):
    Channel age < 90 days  → max 3 videos / 7 days
    Channel age >= 90 days → max 1 video / day (hub) OR 3 / day (spoke)

  Implementation:
    - Reads `scripts` table in vault.db → count WHERE status='uploaded' AND updated_at >= window
    - Channel age from `channel_created_at` in channel JSON (or defaults to 0 = young)

[D] Strike Kill-Switch
  YouTube strikes accumulate: Strike 1 → Strike 2 → Strike 3 → Terminated.
  Rule: Strike detected → freeze ALL uploads for that channel for 14 days.

  Implementation:
    - Strike state stored in channels/{channel_id}.json:
        "strike_count": 1,
        "frozen_until": "2026-06-09T00:00:00+00:00",
        "freeze_reason": "Copyright strike on video abc123"
    - `ChannelGuard.check()` reads JSON → raises ChannelFrozenError if frozen
    - `ChannelGuard.record_strike()` writes strike to JSON + sets frozen_until
    - Auto-unfreeze: if frozen_until < now → ignore (don't clear automatically,
      let operator clear with --unfreeze command)

USAGE (from UploadScheduler):
    guard = ChannelGuard(channels_dir=CHANNELS_DIR, vault_db_path=VAULT_DB)
    guard.check(channel_id, channel_type, market)  # raises on violation
"""

from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from dataclasses import dataclass

import structlog

from omnicast.shared.errors import UploadPipelineError

logger = structlog.get_logger()

# ── Config ────────────────────────────────────────────────────────────────────

YOUNG_CHANNEL_DAYS = 90          # channels < 90 days old are "young"
YOUNG_CHANNEL_WEEKLY_MAX = 3     # max uploads per 7-day window for young channels
DAILY_LIMIT_HUB = 1              # max per day: hub channels
DAILY_LIMIT_SPOKE = 3            # max per day: spoke channels
STRIKE_FREEZE_DAYS = 14          # freeze duration after a strike


class ChannelFrozenError(UploadPipelineError):
    """Raised when channel is frozen due to strike."""

    def __init__(self, channel_id: str, frozen_until: datetime, reason: str) -> None:
        days_left = max(0, (frozen_until - datetime.now(timezone.utc)).days)
        super().__init__(
            f"Channel {channel_id} frozen for {days_left}d more: {reason}",
            details={
                "channel_id": channel_id,
                "frozen_until": frozen_until.isoformat(),
                "days_remaining": days_left,
            },
        )
        self.channel_id = channel_id
        self.frozen_until = frozen_until
        self.reason = reason


class VelocityError(UploadPipelineError):
    """Raised when upload velocity limit is exceeded."""

    def __init__(self, channel_id: str, uploads: int, limit: int, window: str) -> None:
        super().__init__(
            f"Channel {channel_id} velocity limit: {uploads}/{limit} uploads in {window}",
            details={
                "channel_id": channel_id,
                "uploads_in_window": uploads,
                "limit": limit,
                "window": window,
            },
        )
        self.channel_id = channel_id
        self.uploads = uploads
        self.limit = limit
        self.window = window


@dataclass
class GuardResult:
    allowed: bool
    channel_age_days: int
    daily_uploads: int
    weekly_uploads: int
    is_young: bool
    frozen: bool = False
    frozen_until: datetime | None = None
    freeze_reason: str = ""


class ChannelGuard:
    """Enforces velocity limits and strike freeze per channel."""

    def __init__(
        self,
        channels_dir: Path,
        vault_db_path: Path | None = None,
    ) -> None:
        self.channels_dir = channels_dir
        self.vault_db_path = vault_db_path

    # ── Public API ────────────────────────────────────────────────────────────

    def check(
        self,
        channel_id: str,
        channel_type: str = "hub",   # "hub" | "spoke"
    ) -> GuardResult:
        """Run all guard checks. Raises ChannelFrozenError or VelocityError on violation.

        Args:
            channel_id:   Channel identifier (must have channels/{channel_id}.json)
            channel_type: "hub" or "spoke" — determines daily limit

        Returns:
            GuardResult with stats (only returned if all checks pass)

        Raises:
            ChannelFrozenError: Channel has active strike freeze
            VelocityError: Upload velocity limit exceeded
        """
        cfg = self._load_channel_cfg(channel_id)
        now = datetime.now(timezone.utc)

        # [D] Strike freeze check
        frozen_until = self._parse_frozen_until(cfg)
        if frozen_until and now < frozen_until:
            raise ChannelFrozenError(
                channel_id=channel_id,
                frozen_until=frozen_until,
                reason=cfg.get("freeze_reason", "YouTube strike"),
            )

        # Channel age
        channel_age_days = self._channel_age_days(cfg, now)
        is_young = channel_age_days < YOUNG_CHANNEL_DAYS

        # Upload counts from vault.db
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        week_start = now - timedelta(days=7)
        daily_uploads = self._count_uploads(channel_id, today_start.isoformat())
        weekly_uploads = self._count_uploads(channel_id, week_start.isoformat())

        # [A] Young channel weekly limit
        if is_young and weekly_uploads >= YOUNG_CHANNEL_WEEKLY_MAX:
            raise VelocityError(
                channel_id=channel_id,
                uploads=weekly_uploads,
                limit=YOUNG_CHANNEL_WEEKLY_MAX,
                window=f"7 days (channel age: {channel_age_days}d < {YOUNG_CHANNEL_DAYS}d)",
            )

        # [A] Daily limit by channel type
        daily_limit = DAILY_LIMIT_SPOKE if channel_type == "spoke" else DAILY_LIMIT_HUB
        if daily_uploads >= daily_limit:
            raise VelocityError(
                channel_id=channel_id,
                uploads=daily_uploads,
                limit=daily_limit,
                window="today",
            )

        result = GuardResult(
            allowed=True,
            channel_age_days=channel_age_days,
            daily_uploads=daily_uploads,
            weekly_uploads=weekly_uploads,
            is_young=is_young,
            frozen=False,
        )

        logger.info(
            "Channel guard passed",
            channel_id=channel_id,
            channel_type=channel_type,
            age_days=channel_age_days,
            is_young=is_young,
            daily=daily_uploads,
            weekly=weekly_uploads,
        )

        return result

    def record_strike(
        self,
        channel_id: str,
        reason: str = "YouTube copyright strike",
    ) -> datetime:
        """Record a YouTube strike. Freezes channel for STRIKE_FREEZE_DAYS days.

        Updates channels/{channel_id}.json in-place:
            strike_count  += 1
            frozen_until   = now + 14 days
            freeze_reason  = reason

        Returns:
            frozen_until datetime
        """
        cfg = self._load_channel_cfg(channel_id)
        now = datetime.now(timezone.utc)
        frozen_until = now + timedelta(days=STRIKE_FREEZE_DAYS)

        cfg["strike_count"] = cfg.get("strike_count", 0) + 1
        cfg["frozen_until"] = frozen_until.isoformat()
        cfg["freeze_reason"] = reason

        self._save_channel_cfg(channel_id, cfg)

        logger.warning(
            "Channel strike recorded — FROZEN",
            channel_id=channel_id,
            strike_count=cfg["strike_count"],
            frozen_until=frozen_until.isoformat(),
            reason=reason,
        )

        return frozen_until

    def unfreeze(self, channel_id: str) -> None:
        """Manually unfreeze a channel (operator action after strike resolved).

        Clears frozen_until. Does NOT reset strike_count (history is kept).
        """
        cfg = self._load_channel_cfg(channel_id)
        cfg["frozen_until"] = None
        cfg["freeze_reason"] = ""
        self._save_channel_cfg(channel_id, cfg)
        logger.info("Channel unfrozen", channel_id=channel_id,
                    strike_count=cfg.get("strike_count", 0))

    def status(self, channel_id: str) -> dict:
        """Return current guard status dict for display/logging."""
        cfg = self._load_channel_cfg(channel_id)
        now = datetime.now(timezone.utc)
        frozen_until = self._parse_frozen_until(cfg)
        age = self._channel_age_days(cfg, now)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        week_start = now - timedelta(days=7)
        return {
            "channel_id":     channel_id,
            "strike_count":   cfg.get("strike_count", 0),
            "frozen":         bool(frozen_until and now < frozen_until),
            "frozen_until":   frozen_until.isoformat() if frozen_until else None,
            "freeze_reason":  cfg.get("freeze_reason", ""),
            "channel_age_days": age,
            "is_young":       age < YOUNG_CHANNEL_DAYS,
            "uploads_today":  self._count_uploads(channel_id, today_start.isoformat()),
            "uploads_7d":     self._count_uploads(channel_id, week_start.isoformat()),
            "weekly_limit":   YOUNG_CHANNEL_WEEKLY_MAX if age < YOUNG_CHANNEL_DAYS else None,
            "daily_limit":    DAILY_LIMIT_HUB,
        }

    # ── Internals ─────────────────────────────────────────────────────────────

    def _load_channel_cfg(self, channel_id: str) -> dict:
        path = self.channels_dir / f"{channel_id}.json"
        if not path.exists():
            # Unknown channel → treat as young, no freeze
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _save_channel_cfg(self, channel_id: str, cfg: dict) -> None:
        path = self.channels_dir / f"{channel_id}.json"
        if not path.exists():
            logger.warning("Channel JSON not found, skip save", channel_id=channel_id)
            return
        path.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")

    def _parse_frozen_until(self, cfg: dict) -> datetime | None:
        raw = cfg.get("frozen_until")
        if not raw:
            return None
        try:
            dt = datetime.fromisoformat(raw)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except (ValueError, TypeError):
            return None

    def _channel_age_days(self, cfg: dict, now: datetime) -> int:
        """Compute channel age in days from 'channel_created_at' field in JSON."""
        raw = cfg.get("channel_created_at") or cfg.get("created_at")
        if not raw:
            return 0  # unknown age → treat as young (safe default)
        try:
            dt = datetime.fromisoformat(raw)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return max(0, (now - dt).days)
        except (ValueError, TypeError):
            return 0

    def _count_uploads(self, channel_id: str, since_iso: str) -> int:
        """Count uploads from vault.db scripts table since since_iso."""
        if self.vault_db_path is None:
            return 0  # no vault → can't count → fail safe (allow)
        try:
            from omnicast.vault.db import count_recent_uploads
            return count_recent_uploads(channel_id, since_iso, self.vault_db_path)
        except Exception as exc:
            logger.warning("Upload count failed", channel_id=channel_id, error=str(exc))
            return 0  # fail safe: allow upload if DB unreachable
