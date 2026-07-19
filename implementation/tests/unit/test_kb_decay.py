import pytest
from datetime import datetime, timezone, timedelta
from omnicast.analytics.kb_decay import KBDecayManager


@pytest.fixture
def manager():
    return KBDecayManager(default_ttl_days=30)


class TestShouldExpire:
    def test_fresh_trend_not_expired(self, manager):
        created = datetime.now(timezone.utc) - timedelta(days=5)
        assert not manager.should_expire(created, is_trend=True)

    def test_old_trend_expired(self, manager):
        created = datetime.now(timezone.utc) - timedelta(days=35)
        assert manager.should_expire(created, is_trend=True)

    def test_evergreen_longer_ttl(self, manager):
        created = datetime.now(timezone.utc) - timedelta(days=35)
        assert not manager.should_expire(created, is_trend=False)

    def test_evergreen_expired(self, manager):
        created = datetime.now(timezone.utc) - timedelta(days=95)
        assert manager.should_expire(created, is_trend=False)

    def test_recently_used_extends_ttl(self, manager):
        created = datetime.now(timezone.utc) - timedelta(days=35)
        last_used = datetime.now(timezone.utc) - timedelta(days=2)
        assert not manager.should_expire(created, is_trend=True, last_used=last_used)


class TestGetExpiredPatterns:
    def test_returns_expired_ids(self, manager):
        now = datetime.now(timezone.utc)
        patterns = [
            {"id": "p1", "created": now - timedelta(days=5), "is_trend": True},
            {"id": "p2", "created": now - timedelta(days=40), "is_trend": True},
            {"id": "p3", "created": now - timedelta(days=100), "is_trend": False},
        ]
        expired = manager.get_expired_patterns(patterns)
        assert "p2" in expired
        assert "p3" in expired
        assert "p1" not in expired


class TestGetDecayStats:
    def test_returns_counts(self, manager):
        now = datetime.now(timezone.utc)
        patterns = [
            {"id": "p1", "created": now - timedelta(days=5), "is_trend": True},
            {"id": "p2", "created": now - timedelta(days=40), "is_trend": True},
        ]
        stats = manager.get_decay_stats(patterns)
        assert "total" in stats
        assert "expired" in stats
        assert "active" in stats
        assert stats["total"] == 2
