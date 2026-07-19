"""Tests for UploadScheduler (timezone), ChannelGuard (velocity + strike)."""

import json
import tempfile
import pytest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock

from omnicast.upload.scheduler import (
    UploadScheduler, PRIME_TIMES, PRIME_DAYS, MARKET_UTC_OFFSETS,
)
from omnicast.upload.channel_guard import (
    ChannelGuard, ChannelFrozenError, VelocityError,
    YOUNG_CHANNEL_DAYS, YOUNG_CHANNEL_WEEKLY_MAX,
    DAILY_LIMIT_HUB, DAILY_LIMIT_SPOKE, STRIKE_FREEZE_DAYS,
)
from omnicast.upload.models import ScheduleSlot
from omnicast.models.enums import ChannelType
from omnicast.shared.errors import UploadPipelineError


# ─── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def channels_dir(tmp_path):
    """Temp directory acting as channels/."""
    return tmp_path


def _make_channel_json(
    channels_dir: Path,
    channel_id: str,
    age_days: int = 180,
    strike_count: int = 0,
    frozen_until: str | None = None,
    freeze_reason: str = "",
) -> Path:
    now = datetime.now(timezone.utc)
    created_at = (now - timedelta(days=age_days)).isoformat()
    cfg = {
        "channel_id": channel_id,
        "channel_created_at": created_at,
        "strike_count": strike_count,
        "frozen_until": frozen_until,
        "freeze_reason": freeze_reason,
    }
    path = channels_dir / f"{channel_id}.json"
    path.write_text(json.dumps(cfg), encoding="utf-8")
    return path


@pytest.fixture
def guard(channels_dir):
    return ChannelGuard(channels_dir=channels_dir, vault_db_path=None)


# ─── ChannelGuard: Strike Kill-Switch ────────────────────────────────────────

class TestStrikeKillSwitch:
    def test_frozen_channel_raises(self, guard, channels_dir):
        future = (datetime.now(timezone.utc) + timedelta(days=10)).isoformat()
        _make_channel_json(channels_dir, "ch1", frozen_until=future, freeze_reason="Copyright")
        with pytest.raises(ChannelFrozenError) as exc:
            guard.check("ch1", "hub")
        assert "ch1" in str(exc.value)
        assert exc.value.channel_id == "ch1"

    def test_freeze_expired_allows_upload(self, guard, channels_dir):
        past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        _make_channel_json(channels_dir, "ch2", frozen_until=past)
        # Should not raise
        result = guard.check("ch2", "hub")
        assert result.allowed is True
        assert result.frozen is False

    def test_no_freeze_allows_upload(self, guard, channels_dir):
        _make_channel_json(channels_dir, "ch3")
        result = guard.check("ch3", "hub")
        assert result.allowed is True

    def test_record_strike_sets_freeze(self, guard, channels_dir):
        _make_channel_json(channels_dir, "ch4")
        frozen_until = guard.record_strike("ch4", reason="Test strike")

        # Re-check → should be frozen now
        with pytest.raises(ChannelFrozenError):
            guard.check("ch4", "hub")

        assert (frozen_until - datetime.now(timezone.utc)).days >= STRIKE_FREEZE_DAYS - 1

    def test_record_strike_increments_count(self, guard, channels_dir):
        _make_channel_json(channels_dir, "ch5", strike_count=1)
        guard.record_strike("ch5", "Another strike")

        cfg = json.loads((channels_dir / "ch5.json").read_text())
        assert cfg["strike_count"] == 2

    def test_unfreeze_clears_freeze(self, guard, channels_dir):
        future = (datetime.now(timezone.utc) + timedelta(days=10)).isoformat()
        _make_channel_json(channels_dir, "ch6", frozen_until=future, freeze_reason="test")

        guard.unfreeze("ch6")

        # Should pass now
        result = guard.check("ch6", "hub")
        assert result.allowed is True

    def test_unfreeze_preserves_strike_count(self, guard, channels_dir):
        future = (datetime.now(timezone.utc) + timedelta(days=5)).isoformat()
        _make_channel_json(channels_dir, "ch7", strike_count=2, frozen_until=future)
        guard.unfreeze("ch7")

        cfg = json.loads((channels_dir / "ch7.json").read_text())
        assert cfg["strike_count"] == 2   # history preserved
        assert cfg["frozen_until"] is None

    def test_unknown_channel_not_frozen(self, guard):
        """Channel with no JSON → no freeze (fail safe)."""
        result = guard.check("nonexistent_ch", "hub")
        assert result.allowed is True
        assert result.frozen is False


# ─── ChannelGuard: Velocity Limiter ──────────────────────────────────────────

class TestVelocityLimiter:
    def test_young_channel_under_limit_passes(self, guard, channels_dir):
        _make_channel_json(channels_dir, "young1", age_days=30)
        # daily=0, weekly=2 → under weekly limit (3), under daily limit (1)
        with patch.object(guard, "_count_uploads", side_effect=[0, 2]):
            result = guard.check("young1", "hub")
        assert result.is_young is True
        assert result.weekly_uploads == 2

    def test_young_channel_at_weekly_limit_blocked(self, guard, channels_dir):
        _make_channel_json(channels_dir, "young2", age_days=30)
        with patch.object(guard, "_count_uploads", side_effect=[0, YOUNG_CHANNEL_WEEKLY_MAX]):
            with pytest.raises(VelocityError) as exc:
                guard.check("young2", "hub")
        assert exc.value.limit == YOUNG_CHANNEL_WEEKLY_MAX
        assert "7 days" in exc.value.window

    def test_mature_channel_ignores_weekly_limit(self, guard, channels_dir):
        _make_channel_json(channels_dir, "mature1", age_days=200)
        # 5 uploads this week, 0 today → mature channel shouldn't care about weekly
        with patch.object(guard, "_count_uploads", side_effect=[0, 5]):
            result = guard.check("mature1", "hub")
        assert result.allowed is True
        assert result.is_young is False

    def test_hub_daily_limit_one(self, guard, channels_dir):
        _make_channel_json(channels_dir, "hub1", age_days=200)
        with patch.object(guard, "_count_uploads", side_effect=[DAILY_LIMIT_HUB, 0]):
            with pytest.raises(VelocityError) as exc:
                guard.check("hub1", "hub")
        assert exc.value.limit == DAILY_LIMIT_HUB
        assert "today" in exc.value.window

    def test_spoke_daily_limit_three(self, guard, channels_dir):
        _make_channel_json(channels_dir, "spoke1", age_days=200)
        with patch.object(guard, "_count_uploads", side_effect=[DAILY_LIMIT_SPOKE, 0]):
            with pytest.raises(VelocityError) as exc:
                guard.check("spoke1", "spoke")
        assert exc.value.limit == DAILY_LIMIT_SPOKE

    def test_spoke_under_limit_passes(self, guard, channels_dir):
        _make_channel_json(channels_dir, "spoke2", age_days=200)
        with patch.object(guard, "_count_uploads", side_effect=[2, 5]):
            result = guard.check("spoke2", "spoke")
        assert result.allowed is True

    def test_channel_age_exactly_90_not_young(self, guard, channels_dir):
        _make_channel_json(channels_dir, "ch_edge", age_days=YOUNG_CHANNEL_DAYS)
        with patch.object(guard, "_count_uploads", return_value=0):
            result = guard.check("ch_edge", "hub")
        assert result.is_young is False

    def test_channel_age_89_is_young(self, guard, channels_dir):
        _make_channel_json(channels_dir, "ch_young", age_days=YOUNG_CHANNEL_DAYS - 1)
        with patch.object(guard, "_count_uploads", return_value=0):
            result = guard.check("ch_young", "hub")
        assert result.is_young is True

    def test_freeze_checked_before_velocity(self, guard, channels_dir):
        """Frozen channel → ChannelFrozenError, not VelocityError."""
        future = (datetime.now(timezone.utc) + timedelta(days=5)).isoformat()
        _make_channel_json(channels_dir, "ch_prio", frozen_until=future)
        with pytest.raises(ChannelFrozenError):  # NOT VelocityError
            guard.check("ch_prio", "hub")


# ─── ScheduleSlot: Timezone (F) ───────────────────────────────────────────────

class TestTimezoneScheduler:
    def _make_utc(self, year=2026, month=6, day=3, hour=0, minute=0) -> datetime:
        """Tuesday 2026-06-03 (weekday=1) as base."""
        return datetime(year, month, day, hour, minute, 0, tzinfo=timezone.utc)

    def test_us_prime_slot_is_correct_utc(self):
        """US prime = 14:00-16:00 EST (offset=-5) → 19:00-21:00 UTC."""
        scheduler = UploadScheduler()
        # now = Tuesday 2026-06-03 15:00 UTC (before US prime, which is 19:00 UTC)
        now = self._make_utc(hour=15)  # Tuesday
        slot = scheduler._next_prime_time("US", now)
        # Expected: Tuesday 19:00 UTC (same day, prime start)
        assert slot.hour == 19
        assert (slot + timedelta(hours=MARKET_UTC_OFFSETS["US"])).weekday() in PRIME_DAYS["US"]

    def test_us_prime_already_passed_goes_next_prime_day(self):
        """If US prime (19:00 UTC) already passed today → next prime day."""
        scheduler = UploadScheduler()
        # Now = Tuesday 20:00 UTC (past 19:00 prime start) → should find next prime day
        now = self._make_utc(hour=20)  # Tuesday 20:00
        slot = scheduler._next_prime_time("US", now)
        # Prime days are Tue/Wed/Thu (1,2,3). Tuesday passed → Wednesday 19:00 UTC
        local_slot = slot + timedelta(hours=MARKET_UTC_OFFSETS["US"])
        assert local_slot.weekday() in PRIME_DAYS["US"]
        assert slot.hour == 19

    def test_au_prime_slot_utc(self):
        """AU prime = 19:00-21:00 AEST (offset=+10) → 09:00-11:00 UTC."""
        scheduler = UploadScheduler()
        now = self._make_utc(hour=5)  # Tuesday 05:00 UTC (before AU prime 09:00 UTC)
        slot = scheduler._next_prime_time("AU", now)
        assert slot.hour == 9
        local_slot = slot + timedelta(hours=MARKET_UTC_OFFSETS["AU"])
        assert local_slot.weekday() in PRIME_DAYS["AU"]

    def test_jp_prime_slot_utc(self):
        """JP prime = 20:00-22:00 JST (offset=+9) → 11:00-13:00 UTC."""
        scheduler = UploadScheduler()
        now = self._make_utc(hour=5)  # before JP prime (11:00 UTC)
        slot = scheduler._next_prime_time("JP", now)
        assert slot.hour == 11
        local_slot = slot + timedelta(hours=MARKET_UTC_OFFSETS["JP"])
        assert local_slot.weekday() in PRIME_DAYS["JP"]

    def test_uk_prime_slot_utc(self):
        """UK prime = 12:00-14:00 GMT (offset=0) → 12:00-14:00 UTC."""
        scheduler = UploadScheduler()
        now = self._make_utc(hour=8)  # Monday before UK prime
        slot = scheduler._next_prime_time("UK", now)
        assert slot.hour == 12
        local_slot = slot + timedelta(hours=MARKET_UTC_OFFSETS["UK"])
        assert local_slot.weekday() in PRIME_DAYS["UK"]

    def test_unknown_market_falls_back(self):
        """Unknown market → uses default offset/prime_days, slot within 8 days."""
        scheduler = UploadScheduler()
        now = datetime.now(timezone.utc)
        slot = scheduler._next_prime_time("XX", now)
        assert slot > now
        assert (slot - now).total_seconds() < 8 * 24 * 3600  # within 8 days

    def test_is_prime_time_true_for_correct_utc(self):
        """US 19:00 UTC Wednesday → local 14:00 EST Wed → prime."""
        scheduler = UploadScheduler()
        # Wednesday 2026-06-03 → weekday=2, 19:00 UTC → 14:00 EST
        dt = datetime(2026, 6, 3, 19, 0, tzinfo=timezone.utc)  # Wednesday
        assert scheduler._is_prime_time(dt, "US") is True

    def test_is_prime_time_false_outside_window(self):
        """US 23:00 UTC Wednesday → local 18:00 EST → not prime (14-16 only)."""
        scheduler = UploadScheduler()
        dt = datetime(2026, 6, 3, 23, 0, tzinfo=timezone.utc)  # Wednesday 23:00 UTC
        assert scheduler._is_prime_time(dt, "US") is False

    def test_is_prime_time_false_wrong_day(self):
        """US prime day Mon=0 not in [1,2,3] → not prime."""
        scheduler = UploadScheduler()
        # Monday 2026-06-01 19:00 UTC → local 14:00 EST Mon → NOT prime day
        dt = datetime(2026, 6, 1, 19, 0, tzinfo=timezone.utc)  # Monday
        assert scheduler._is_prime_time(dt, "US") is False

    def test_avoid_quiet_hours_pushes_to_morning(self):
        """Slot at US 02:00 UTC → local 21:00 EST → quiet → push to next 07:00 local."""
        scheduler = UploadScheduler()
        # 02:00 UTC → 02 + (-5) = -3 → 21:00 local → quiet (23:00..06:00 wraps)
        # Actually 21:00 < 23:00 quiet_start, so NOT quiet... Let me recalculate.
        # quiet_start=23, quiet_end=6. local_hour=21 → 21 >= 23? No. 21 < 6? No. → NOT quiet.
        # Let's use a slot that IS quiet: 04:00 UTC → 04+(-5)=-1 → 23:00 local → quiet!
        dt = datetime(2026, 6, 3, 4, 0, tzinfo=timezone.utc)
        result = scheduler._avoid_quiet_hours_utc(dt, "US")
        # 23:00 local → push to 07:00 local next day → 07+5=12:00 UTC
        assert result.hour == 12  # 07:00 EST = 12:00 UTC

    def test_schedule_returns_slot_with_no_guard(self):
        """Scheduler without guard should still return a slot (legacy mode)."""
        scheduler = UploadScheduler(guard=None)
        slot = scheduler.schedule("ch_test", ChannelType.HUB, market="US")
        assert isinstance(slot, ScheduleSlot)
        assert slot.channel_id == "ch_test"

    def test_schedule_with_guard_frozen_raises(self, channels_dir):
        future = (datetime.now(timezone.utc) + timedelta(days=5)).isoformat()
        _make_channel_json(channels_dir, "frozen_ch", frozen_until=future)
        guard = ChannelGuard(channels_dir=channels_dir, vault_db_path=None)
        scheduler = UploadScheduler(guard=guard)
        with pytest.raises(ChannelFrozenError):
            scheduler.schedule("frozen_ch", ChannelType.HUB, market="US")

    def test_schedule_with_guard_velocity_exceeded_raises(self, channels_dir):
        _make_channel_json(channels_dir, "busy_ch", age_days=200)
        guard = ChannelGuard(channels_dir=channels_dir, vault_db_path=None)
        with patch.object(guard, "_count_uploads", side_effect=[DAILY_LIMIT_HUB, 0]):
            scheduler = UploadScheduler(guard=guard)
            with pytest.raises(VelocityError):
                scheduler.schedule("busy_ch", ChannelType.HUB, market="US")


# ─── GuardResult status ───────────────────────────────────────────────────────

class TestGuardStatus:
    def test_status_returns_correct_fields(self, guard, channels_dir):
        _make_channel_json(channels_dir, "stat_ch", age_days=30, strike_count=1)
        with patch.object(guard, "_count_uploads", return_value=1):
            s = guard.status("stat_ch")
        assert s["channel_id"] == "stat_ch"
        assert s["strike_count"] == 1
        assert s["is_young"] is True
        assert s["frozen"] is False

    def test_status_frozen_channel(self, guard, channels_dir):
        future = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
        _make_channel_json(channels_dir, "frozen_stat", frozen_until=future, freeze_reason="test")
        with patch.object(guard, "_count_uploads", return_value=0):
            s = guard.status("frozen_stat")
        assert s["frozen"] is True
        assert s["freeze_reason"] == "test"


# ─── Constants sanity ────────────────────────────────────────────────────────

class TestConstants:
    def test_all_markets_have_utc_offset(self):
        for market in PRIME_TIMES:
            assert market in MARKET_UTC_OFFSETS, f"Missing UTC offset for {market}"

    def test_all_prime_days_valid(self):
        for market, days in PRIME_DAYS.items():
            assert all(0 <= d <= 6 for d in days), f"Invalid weekday in {market}"

    def test_young_channel_config(self):
        assert YOUNG_CHANNEL_DAYS == 90
        assert YOUNG_CHANNEL_WEEKLY_MAX == 3
        assert STRIKE_FREEZE_DAYS == 14
        assert DAILY_LIMIT_HUB == 1
        assert DAILY_LIMIT_SPOKE == 3
