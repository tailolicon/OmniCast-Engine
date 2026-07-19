# TASK_C: Upload Scheduler

## Model: sonnet | Dependencies: TASK_A complete

Rate limiting + prime time scheduling. Prevents burst uploads, mimics human patterns.

## Interface

### src/omnicast/upload/scheduler.py

```python
"""Upload scheduler. Rate limiting per channel, prime time targeting, burst prevention."""

from __future__ import annotations
from datetime import datetime, timezone, timedelta
import random
import structlog
from omnicast.upload.models import ScheduleSlot
from omnicast.models.enums import ChannelType
from omnicast.shared.errors import UploadPipelineError

logger = structlog.get_logger()

PRIME_TIMES: dict[str, tuple[int, int]] = {
    "US": (14, 16),   # 2PM-4PM EST, Tue-Thu
    "UK": (12, 14),   # 12PM-2PM GMT, Mon-Wed
    "AU": (19, 21),   # 7PM-9PM AEST, Tue-Thu
    "JP": (20, 22),   # 8PM-10PM JST, Wed-Fri
    "KR": (19, 21),   # 7PM-9PM KST, Tue-Thu
}

PRIME_DAYS: dict[str, list[int]] = {
    "US": [1, 2, 3],   # Tue, Wed, Thu (0=Mon)
    "UK": [0, 1, 2],   # Mon, Tue, Wed
    "AU": [1, 2, 3],   # Tue, Wed, Thu
    "JP": [2, 3, 4],   # Wed, Thu, Fri
    "KR": [1, 2, 3],   # Tue, Wed, Thu
}

DAILY_LIMITS: dict[str, int] = {
    "hub": 1,
    "spoke": 3,
}

QUIET_HOURS = (23, 6)  # 11PM-6AM local time, no uploads
BURST_LIMIT = 10       # uploads before mandatory pause
BURST_PAUSE_HOURS = 2
SPREAD_DELAY_RANGE = (15, 45)  # minutes between uploads on same channel


class UploadScheduler:
    """Schedule uploads respecting rate limits and prime time."""

    def __init__(self) -> None:
        self._upload_log: dict[str, list[datetime]] = {}  # channel_id → upload timestamps
        self._burst_count: int = 0
        self._burst_pause_until: datetime | None = None

    def schedule(
        self,
        channel_id: str,
        channel_type: ChannelType,
        market: str = "US",
        preferred_time: datetime | None = None,
    ) -> ScheduleSlot:
        """Find next available upload slot. Steps:
        1. Check burst guard (global 10 uploads → 2h pause)
        2. Check daily limit per channel (hub=1, spoke=3)
        3. Check quiet hours (11PM-6AM)
        4. Find next prime time slot for market
        5. Add random spread delay (15-45 min)
        """
        now = datetime.now(timezone.utc)

        if self._is_burst_paused(now):
            raise UploadPipelineError("Burst guard active, retry later")

        if self._daily_count(channel_id, now) >= DAILY_LIMITS.get(channel_type.value, 1):
            raise UploadPipelineError(
                f"Daily limit reached for {channel_id}",
                details={"limit": DAILY_LIMITS.get(channel_type.value, 1)}
            )

        slot_time = preferred_time or self._next_prime_time(market, now)
        slot_time = self._apply_spread_delay(channel_id, slot_time)
        slot_time = self._avoid_quiet_hours(slot_time)

        is_prime = self._is_prime_time(slot_time, market)

        return ScheduleSlot(
            channel_id=channel_id,
            scheduled_at=slot_time,
            market=market,
            is_prime_time=is_prime,
        )

    def record_upload(self, channel_id: str, uploaded_at: datetime | None = None) -> None:
        """Record an upload for rate tracking."""
        ts = uploaded_at or datetime.now(timezone.utc)
        self._upload_log.setdefault(channel_id, []).append(ts)
        self._burst_count += 1
        if self._burst_count >= BURST_LIMIT:
            self._burst_pause_until = ts + timedelta(hours=BURST_PAUSE_HOURS)
            self._burst_count = 0
            logger.warning("Burst limit hit, pausing", pause_until=self._burst_pause_until)

    def _daily_count(self, channel_id: str, now: datetime) -> int:
        """Count uploads today for channel."""
        today = now.date()
        return sum(1 for ts in self._upload_log.get(channel_id, []) if ts.date() == today)

    def _is_burst_paused(self, now: datetime) -> bool:
        if self._burst_pause_until and now < self._burst_pause_until:
            return True
        return False

    def _next_prime_time(self, market: str, now: datetime) -> datetime:
        """Find next prime time slot for market."""
        ...

    def _apply_spread_delay(self, channel_id: str, slot_time: datetime) -> datetime:
        """Add random 15-45 min delay if another upload on same channel today."""
        uploads_today = [ts for ts in self._upload_log.get(channel_id, [])
                         if ts.date() == slot_time.date()]
        if uploads_today:
            delay = random.randint(*SPREAD_DELAY_RANGE)
            slot_time = slot_time + timedelta(minutes=delay)
        return slot_time

    def _avoid_quiet_hours(self, slot_time: datetime) -> datetime:
        """Push to 7AM if slot falls in quiet hours (11PM-6AM)."""
        hour = slot_time.hour
        if hour >= QUIET_HOURS[0] or hour < QUIET_HOURS[1]:
            next_day = slot_time.date() + timedelta(days=1) if hour >= QUIET_HOURS[0] else slot_time.date()
            slot_time = slot_time.replace(year=next_day.year, month=next_day.month,
                                          day=next_day.day, hour=7, minute=0, second=0)
        return slot_time

    def _is_prime_time(self, dt: datetime, market: str) -> bool:
        """Check if datetime falls in prime time window for market."""
        if market not in PRIME_TIMES:
            return False
        start_h, end_h = PRIME_TIMES[market]
        days = PRIME_DAYS.get(market, [])
        return start_h <= dt.hour < end_h and dt.weekday() in days
```

## DO NOT

- No YouTube API calls — scheduler is pure logic
- No modifying models.py or oauth.py
- Spread delay must be random within range, not fixed
- Quiet hours check must handle midnight crossing (23:00 → 06:00)
- _upload_log is in-memory — persistent storage is Phase 6+ concern

## Tests

### tests/unit/test_upload_scheduler.py

```python
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch
from omnicast.upload.scheduler import (
    UploadScheduler, PRIME_TIMES, DAILY_LIMITS, BURST_LIMIT,
    QUIET_HOURS, SPREAD_DELAY_RANGE,
)
from omnicast.upload.models import ScheduleSlot
from omnicast.models.enums import ChannelType
from omnicast.shared.errors import UploadPipelineError


@pytest.fixture
def scheduler():
    return UploadScheduler()


class TestScheduleBasic:
    def test_schedule_returns_slot(self, scheduler):
        slot = scheduler.schedule("ch1", ChannelType.HUB, market="US")
        assert isinstance(slot, ScheduleSlot)
        assert slot.channel_id == "ch1"

    def test_schedule_market(self, scheduler):
        slot = scheduler.schedule("ch1", ChannelType.HUB, market="JP")
        assert slot.market == "JP"


class TestDailyLimits:
    def test_hub_limit_1(self, scheduler):
        now = datetime.now(timezone.utc)
        scheduler.record_upload("ch1", now)
        with pytest.raises(UploadPipelineError, match="Daily limit"):
            scheduler.schedule("ch1", ChannelType.HUB)

    def test_spoke_limit_3(self, scheduler):
        now = datetime.now(timezone.utc)
        for i in range(3):
            scheduler.record_upload("ch2", now + timedelta(minutes=i))
        with pytest.raises(UploadPipelineError, match="Daily limit"):
            scheduler.schedule("ch2", ChannelType.SPOKE)

    def test_spoke_under_limit(self, scheduler):
        now = datetime.now(timezone.utc)
        scheduler.record_upload("ch2", now)
        scheduler.record_upload("ch2", now + timedelta(minutes=1))
        slot = scheduler.schedule("ch2", ChannelType.SPOKE)
        assert isinstance(slot, ScheduleSlot)


class TestBurstGuard:
    def test_burst_triggers_pause(self, scheduler):
        now = datetime.now(timezone.utc)
        for i in range(BURST_LIMIT):
            scheduler.record_upload(f"ch_{i}", now + timedelta(minutes=i))
        assert scheduler._burst_pause_until is not None

    def test_burst_pause_blocks_schedule(self, scheduler):
        now = datetime.now(timezone.utc)
        for i in range(BURST_LIMIT):
            scheduler.record_upload(f"ch_{i}", now)
        with pytest.raises(UploadPipelineError, match="Burst guard"):
            scheduler.schedule("ch_new", ChannelType.SPOKE)


class TestQuietHours:
    def test_late_night_pushed_to_morning(self, scheduler):
        late = datetime(2025, 6, 1, 23, 30, tzinfo=timezone.utc)
        result = scheduler._avoid_quiet_hours(late)
        assert result.hour == 7

    def test_early_morning_pushed_to_7am(self, scheduler):
        early = datetime(2025, 6, 1, 3, 0, tzinfo=timezone.utc)
        result = scheduler._avoid_quiet_hours(early)
        assert result.hour == 7

    def test_daytime_unchanged(self, scheduler):
        noon = datetime(2025, 6, 1, 12, 0, tzinfo=timezone.utc)
        result = scheduler._avoid_quiet_hours(noon)
        assert result.hour == 12


class TestPrimeTime:
    def test_us_prime_time(self, scheduler):
        # Tuesday 3PM UTC (matches US Tue 2-4PM)
        dt = datetime(2025, 6, 3, 15, 0, tzinfo=timezone.utc)  # Tuesday
        assert scheduler._is_prime_time(dt, "US")

    def test_us_non_prime_time(self, scheduler):
        dt = datetime(2025, 6, 3, 10, 0, tzinfo=timezone.utc)  # Tuesday 10AM
        assert not scheduler._is_prime_time(dt, "US")

    def test_unknown_market(self, scheduler):
        dt = datetime(2025, 6, 3, 15, 0, tzinfo=timezone.utc)
        assert not scheduler._is_prime_time(dt, "XX")


class TestSpreadDelay:
    def test_no_spread_for_first_upload(self, scheduler):
        slot = datetime(2025, 6, 1, 14, 0, tzinfo=timezone.utc)
        result = scheduler._apply_spread_delay("ch1", slot)
        assert result == slot

    def test_spread_adds_delay(self, scheduler):
        slot = datetime(2025, 6, 1, 14, 0, tzinfo=timezone.utc)
        scheduler.record_upload("ch1", slot - timedelta(hours=1))
        result = scheduler._apply_spread_delay("ch1", slot)
        delay_minutes = (result - slot).total_seconds() / 60
        assert SPREAD_DELAY_RANGE[0] <= delay_minutes <= SPREAD_DELAY_RANGE[1]


class TestRecordUpload:
    def test_records_timestamp(self, scheduler):
        now = datetime.now(timezone.utc)
        scheduler.record_upload("ch1", now)
        assert len(scheduler._upload_log["ch1"]) == 1

    def test_daily_count(self, scheduler):
        now = datetime.now(timezone.utc)
        scheduler.record_upload("ch1", now)
        scheduler.record_upload("ch1", now + timedelta(minutes=30))
        assert scheduler._daily_count("ch1", now) == 2

    def test_daily_count_ignores_yesterday(self, scheduler):
        now = datetime.now(timezone.utc)
        yesterday = now - timedelta(days=1)
        scheduler.record_upload("ch1", yesterday)
        assert scheduler._daily_count("ch1", now) == 0
```
