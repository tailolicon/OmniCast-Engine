import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, AsyncMock, MagicMock
from omnicast.upload.thumbnail import (
    ThumbnailManager, ThumbnailState, ThumbnailVariant,
    CTR_THRESHOLD, EVALUATION_HOURS, MAX_SWAPS,
)
from omnicast.upload.youtube_api import YouTubeUploader


@pytest.fixture
def mock_uploader():
    u = MagicMock(spec=YouTubeUploader)
    u.oauth = MagicMock()
    u.oauth.get_credentials = AsyncMock(return_value=MagicMock())
    u._build_service = MagicMock(return_value=MagicMock())
    u._set_thumbnail = AsyncMock(return_value=True)
    return u


@pytest.fixture
def manager(mock_uploader):
    return ThumbnailManager(uploader=mock_uploader)


class TestThumbnailVariant:
    def test_create(self):
        v = ThumbnailVariant(variant_id="A", path="/tmp/a.jpg")
        assert not v.is_active
        assert v.ctr is None

    def test_active(self):
        v = ThumbnailVariant(variant_id="A", path="/tmp/a.jpg", is_active=True)
        assert v.is_active


class TestThumbnailState:
    def test_active_variant(self):
        variants = [
            ThumbnailVariant(variant_id="A", path="/a.jpg", is_active=True),
            ThumbnailVariant(variant_id="B", path="/b.jpg"),
        ]
        s = ThumbnailState(youtube_video_id="yt1", channel_id="ch1", variants=variants)
        assert s.active_variant.variant_id == "A"

    def test_can_swap(self):
        s = ThumbnailState(youtube_video_id="yt1", channel_id="ch1", swap_count=0)
        assert s.can_swap

    def test_cannot_swap_max(self):
        s = ThumbnailState(youtube_video_id="yt1", channel_id="ch1", swap_count=MAX_SWAPS)
        assert not s.can_swap

    def test_needs_evaluation(self):
        past = datetime.now(timezone.utc) - timedelta(hours=EVALUATION_HOURS + 1)
        s = ThumbnailState(youtube_video_id="yt1", channel_id="ch1", last_swap_at=past)
        assert s.needs_evaluation

    def test_no_evaluation_too_early(self):
        recent = datetime.now(timezone.utc) - timedelta(hours=1)
        s = ThumbnailState(youtube_video_id="yt1", channel_id="ch1", last_swap_at=recent)
        assert not s.needs_evaluation


class TestRegisterVariants:
    def test_register_3_variants(self, manager):
        state = manager.register_variants("yt1", "ch1", ["/a.jpg", "/b.jpg", "/c.jpg"])
        assert len(state.variants) == 3
        assert state.variants[0].is_active
        assert state.variants[0].variant_id == "A"
        assert not state.variants[1].is_active

    def test_register_stored(self, manager):
        manager.register_variants("yt1", "ch1", ["/a.jpg"])
        assert manager.get_state("yt1") is not None


class TestEvaluateAndSwap:
    @pytest.mark.asyncio
    async def test_no_swap_high_ctr(self, manager):
        manager.register_variants("yt1", "ch1", ["/a.jpg", "/b.jpg"])
        # Force evaluation period passed
        state = manager._states["yt1"]
        manager._states["yt1"] = state.model_copy(update={
            "last_swap_at": datetime.now(timezone.utc) - timedelta(hours=EVALUATION_HOURS + 1)
        })
        result = await manager.evaluate_and_swap("yt1", current_ctr=5.0, current_impressions=1000)
        assert result is None  # no swap needed

    @pytest.mark.asyncio
    async def test_swap_low_ctr(self, manager):
        manager.register_variants("yt1", "ch1", ["/a.jpg", "/b.jpg"])
        state = manager._states["yt1"]
        manager._states["yt1"] = state.model_copy(update={
            "last_swap_at": datetime.now(timezone.utc) - timedelta(hours=EVALUATION_HOURS + 1)
        })
        result = await manager.evaluate_and_swap("yt1", current_ctr=2.0, current_impressions=500)
        assert result is not None
        assert result.swap_count == 1
        active = result.active_variant
        assert active.variant_id == "B"

    @pytest.mark.asyncio
    async def test_no_swap_too_early(self, manager):
        manager.register_variants("yt1", "ch1", ["/a.jpg", "/b.jpg"])
        # last_swap_at is recent (just registered)
        result = await manager.evaluate_and_swap("yt1", current_ctr=1.0, current_impressions=100)
        assert result is None

    @pytest.mark.asyncio
    async def test_no_swap_max_reached(self, manager):
        manager.register_variants("yt1", "ch1", ["/a.jpg", "/b.jpg"])
        state = manager._states["yt1"]
        manager._states["yt1"] = state.model_copy(update={
            "swap_count": MAX_SWAPS,
            "last_swap_at": datetime.now(timezone.utc) - timedelta(hours=EVALUATION_HOURS + 1),
        })
        result = await manager.evaluate_and_swap("yt1", current_ctr=1.0, current_impressions=100)
        assert result is None

    @pytest.mark.asyncio
    async def test_unknown_video(self, manager):
        result = await manager.evaluate_and_swap("unknown", current_ctr=1.0, current_impressions=0)
        assert result is None


class TestNextVariant:
    def test_picks_untried(self, manager):
        variants = [
            ThumbnailVariant(variant_id="A", path="/a.jpg", is_active=True, ctr=3.0),
            ThumbnailVariant(variant_id="B", path="/b.jpg"),
        ]
        state = ThumbnailState(youtube_video_id="yt1", channel_id="ch1", variants=variants)
        nxt = manager._next_variant(state)
        assert nxt.variant_id == "B"

    def test_none_if_all_tried(self, manager):
        variants = [
            ThumbnailVariant(variant_id="A", path="/a.jpg", is_active=True, ctr=3.0),
            ThumbnailVariant(variant_id="B", path="/b.jpg", ctr=2.5),
        ]
        state = ThumbnailState(youtube_video_id="yt1", channel_id="ch1", variants=variants)
        assert manager._next_variant(state) is None
