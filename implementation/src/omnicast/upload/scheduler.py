"""Upload scheduler. Prime-time targeting, timezone-aware, velocity-guarded.

PRIME TIME LOGIC (F — Timezone Scheduler):
  Each market has defined prime hours in LOCAL time.
  Scheduler converts local → UTC for actual scheduling.
  Example: US prime = 14:00-16:00 EST = 19:00-21:00 UTC (winter).

  Market UTC offsets (standard time, no DST — conservative choice):
    US/CA: UTC-5 (EST)   → local 14:00 = UTC 19:00
    UK:    UTC+0 (GMT)   → local 12:00 = UTC 12:00
    AU:    UTC+10 (AEST) → local 19:00 = UTC 09:00
    JP:    UTC+9 (JST)   → local 20:00 = UTC 11:00
    KR:    UTC+9 (KST)   → local 19:00 = UTC 10:00

VELOCITY GUARD (A + D — injected via ChannelGuard):
  If ChannelGuard is provided, schedule() calls guard.check() first.
  Raises ChannelFrozenError or VelocityError before computing slot.
  If no guard → legacy behavior (in-memory only, for tests/standalone use).
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from pathlib import Path
import random
import structlog

from omnicast.upload.models import ScheduleSlot
from omnicast.models.enums import ChannelType
from omnicast.shared.errors import UploadPipelineError

logger = structlog.get_logger()

# ── Prime time config ─────────────────────────────────────────────────────────
# Local hours (start, end) — in TARGET AUDIENCE timezone
PRIME_TIMES: dict[str, tuple[int, int]] = {
    "US": (14, 16),   # 2PM-4PM EST
    "CA": (14, 16),   # 2PM-4PM EST (same as US)
    "UK": (12, 14),   # 12PM-2PM GMT
    "AU": (19, 21),   # 7PM-9PM AEST
    "JP": (20, 22),   # 8PM-10PM JST
    "KR": (19, 21),   # 7PM-9PM KST
}

# Market → UTC offset in hours (standard time, no DST adjustment)
# Conservative: use standard time (more restrictive hours) to avoid scheduling
# at bad times when DST flips.
MARKET_UTC_OFFSETS: dict[str, int] = {
    "US": -5,    # EST (UTC-5). EDT = UTC-4, but EST is safer
    "CA": -5,    # EST
    "UK":  0,    # GMT (UTC+0). BST = UTC+1
    "AU": 10,    # AEST (UTC+10). AEDT = UTC+11
    "JP":  9,    # JST (UTC+9, no DST)
    "KR":  9,    # KST (UTC+9, no DST)
}

# Prime days per market (0=Mon … 6=Sun)
PRIME_DAYS: dict[str, list[int]] = {
    "US": [1, 2, 3],    # Tue, Wed, Thu
    "CA": [1, 2, 3],
    "UK": [0, 1, 2],    # Mon, Tue, Wed
    "AU": [1, 2, 3],
    "JP": [2, 3, 4],    # Wed, Thu, Fri
    "KR": [1, 2, 3],
}

# Daily limits (fallback when no ChannelGuard injected)
DAILY_LIMITS: dict[str, int] = {
    "hub":   1,
    "spoke": 3,
}

QUIET_HOURS = (23, 6)          # 11PM-6AM local → skip (in UTC comparison)
BURST_LIMIT = 10               # global: pause after N uploads
BURST_PAUSE_HOURS = 2
SPREAD_DELAY_RANGE = (15, 45)  # random jitter between uploads (minutes)


# ── Scheduler ─────────────────────────────────────────────────────────────────

class UploadScheduler:
    """Schedule uploads with prime-time targeting and guard enforcement.

    Args:
        guard: Optional ChannelGuard instance. If provided, velocity limits
               and strike freeze are enforced. If None, only in-memory
               daily limit is used (for backward compat / tests).
    """

    def __init__(self, guard=None) -> None:
        self._guard = guard
        self._upload_log: dict[str, list[datetime]] = {}
        self._burst_count: int = 0
        self._burst_pause_until: datetime | None = None

    def schedule(
        self,
        channel_id: str,
        channel_type: ChannelType,
        market: str = "US",
        preferred_time: datetime | None = None,
    ) -> ScheduleSlot:
        """Find next available upload slot.

        Steps:
          1. ChannelGuard.check() — freeze + velocity (raises on violation)
          2. Burst guard (global 10 uploads → 2h pause)
          3. In-memory daily fallback (only if no guard injected)
          4. Find next prime-time UTC slot for market
          5. Add random spread delay (15-45 min)
          6. Skip quiet hours (11PM-6AM local)
        """
        now = datetime.now(timezone.utc)

        # [D+A] Guard check — raises ChannelFrozenError or VelocityError
        if self._guard is not None:
            ct = channel_type.value if hasattr(channel_type, "value") else str(channel_type)
            self._guard.check(channel_id, ct)

        # Global burst guard
        if self._is_burst_paused(now):
            raise UploadPipelineError("Burst guard active, retry later")

        # Fallback in-memory daily limit (when no guard)
        if self._guard is None:
            limit = DAILY_LIMITS.get(
                channel_type.value if hasattr(channel_type, "value") else str(channel_type), 1
            )
            if self._daily_count(channel_id, now) >= limit:
                raise UploadPipelineError(
                    f"Daily limit reached for {channel_id}",
                    details={"limit": limit},
                )

        # Compute slot
        slot_time = preferred_time or self._next_prime_time(market, now)
        slot_time = self._apply_spread_delay(channel_id, slot_time)
        slot_time = self._avoid_quiet_hours_utc(slot_time, market)

        is_prime = self._is_prime_time(slot_time, market)

        logger.info(
            "Upload slot scheduled",
            channel_id=channel_id,
            market=market,
            slot_utc=slot_time.isoformat(),
            is_prime=is_prime,
        )

        return ScheduleSlot(
            channel_id=channel_id,
            scheduled_at=slot_time,
            market=market,
            is_prime_time=is_prime,
        )

    def record_upload(self, channel_id: str, uploaded_at: datetime | None = None) -> None:
        """Record upload for in-memory burst tracking."""
        ts = uploaded_at or datetime.now(timezone.utc)
        self._upload_log.setdefault(channel_id, []).append(ts)
        self._burst_count += 1
        if self._burst_count >= BURST_LIMIT:
            self._burst_pause_until = ts + timedelta(hours=BURST_PAUSE_HOURS)
            self._burst_count = 0
            logger.warning("Burst limit hit, pausing", pause_until=self._burst_pause_until)

    # ── Private ───────────────────────────────────────────────────────────────

    def _daily_count(self, channel_id: str, now: datetime) -> int:
        today = now.date()
        return sum(1 for ts in self._upload_log.get(channel_id, []) if ts.date() == today)

    def _is_burst_paused(self, now: datetime) -> bool:
        return bool(self._burst_pause_until and now < self._burst_pause_until)

    def _next_prime_time(self, market: str, now: datetime) -> datetime:
        """Find next prime-time UTC datetime for market.

        Algorithm:
          1. Get prime window start in local hours and UTC offset
          2. Compute prime_start_utc for TODAY
          3. If prime_start_utc already passed today → advance to tomorrow
          4. Walk forward up to 7 days to find a prime day

        Example (US, now=UTC 20:00 Wednesday):
          prime_start_local = 14:00, offset = -5 → prime_start_utc = 19:00
          Today prime_start_utc (Wed) = already passed (20:00 > 19:00)
          → advance to Thursday 19:00 UTC (still prime day)
        """
        offset = MARKET_UTC_OFFSETS.get(market, 0)
        prime_start_local, _ = PRIME_TIMES.get(market, (14, 16))
        prime_days = PRIME_DAYS.get(market, [1, 2, 3])

        # Convert local prime hour to UTC: UTC = local - offset
        prime_start_utc_hour = (prime_start_local - offset) % 24

        # Start from today's prime slot
        candidate = now.replace(
            hour=prime_start_utc_hour, minute=0, second=0, microsecond=0
        )

        # If that slot is already past, start from tomorrow
        if candidate <= now:
            candidate += timedelta(days=1)

        # Walk forward to find a prime day (max 7 days)
        for _ in range(7):
            # Convert UTC candidate back to local to check local weekday
            local_hour_offset = offset
            local_dt = candidate + timedelta(hours=local_hour_offset)
            if local_dt.weekday() in prime_days:
                return candidate
            candidate += timedelta(days=1)

        # Fallback: 2h from now (no prime day found, shouldn't happen)
        logger.warning("No prime day found in 7d window", market=market)
        return now + timedelta(hours=2)

    def _apply_spread_delay(self, channel_id: str, slot_time: datetime) -> datetime:
        """Add random 15-45 min jitter if another upload on same channel today."""
        uploads_today = [
            ts for ts in self._upload_log.get(channel_id, [])
            if ts.date() == slot_time.date()
        ]
        if uploads_today:
            delay = random.randint(*SPREAD_DELAY_RANGE)
            slot_time = slot_time + timedelta(minutes=delay)
        return slot_time

    def _avoid_quiet_hours_utc(self, slot_time: datetime, market: str) -> datetime:
        """Push past quiet hours (11PM-6AM local) if slot falls in that range.

        Converts slot_time to local time for comparison, then pushes to 07:00 local
        if quiet, converts back to UTC.
        """
        offset = MARKET_UTC_OFFSETS.get(market, 0)
        local_hour = (slot_time.hour + offset) % 24

        quiet_start, quiet_end = QUIET_HOURS  # 23, 6

        if local_hour >= quiet_start or local_hour < quiet_end:
            # Push to 07:00 local next day (if past 23:00) or same day (if before 06:00)
            if local_hour >= quiet_start:
                # Past 11PM → next day 07:00 local
                next_day = slot_time + timedelta(days=1)
            else:
                next_day = slot_time

            # 07:00 local → UTC
            target_utc_hour = (7 - offset) % 24
            slot_time = next_day.replace(
                hour=target_utc_hour, minute=0, second=0, microsecond=0
            )

        return slot_time

    def _is_prime_time(self, dt: datetime, market: str) -> bool:
        """Check if UTC datetime falls in prime-time window (local time check)."""
        if market not in PRIME_TIMES:
            return False
        offset = MARKET_UTC_OFFSETS.get(market, 0)
        start_local, end_local = PRIME_TIMES[market]
        prime_days = PRIME_DAYS.get(market, [])

        # Convert UTC to local for comparison
        local_dt = dt + timedelta(hours=offset)
        return start_local <= local_dt.hour < end_local and local_dt.weekday() in prime_days
