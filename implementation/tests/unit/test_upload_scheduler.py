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
        # UK (offset=0): UTC = local, 23:30 local → quiet → push to 07:00 local = 07:00 UTC
        late = datetime(2025, 6, 1, 23, 30, tzinfo=timezone.utc)
        result = scheduler._avoid_quiet_hours_utc(late, "UK")
        assert result.hour == 7

    def test_early_morning_pushed_to_7am(self, scheduler):
        # UK (offset=0): 03:00 local → quiet → push to 07:00 UTC
        early = datetime(2025, 6, 1, 3, 0, tzinfo=timezone.utc)
        result = scheduler._avoid_quiet_hours_utc(early, "UK")
        assert result.hour == 7

    def test_daytime_unchanged(self, scheduler):
        # UK (offset=0): 12:00 local → not quiet → unchanged
        noon = datetime(2025, 6, 1, 12, 0, tzinfo=timezone.utc)
        result = scheduler._avoid_quiet_hours_utc(noon, "UK")
        assert result.hour == 12


class TestPrimeTime:
    def test_us_prime_time(self, scheduler):
        # US prime 14-16 EST = 19-21 UTC; Tuesday 19:00 UTC = 14:00 EST → prime
        dt = datetime(2025, 6, 3, 19, 0, tzinfo=timezone.utc)  # Tuesday
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
