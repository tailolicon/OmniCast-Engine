import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from omnicast.media.thumbnail import ThumbnailModule
from omnicast.media.models import ThumbnailRequest, ThumbnailResult, MediaStatus


@pytest.fixture
def mock_settings():
    s = MagicMock()
    s.is_dry_run = False
    return s


@pytest.fixture
def dry_settings():
    s = MagicMock()
    s.is_dry_run = True
    return s


@pytest.fixture
def thumb(mock_settings):
    with patch("omnicast.media.base.get_settings", return_value=mock_settings):
        return ThumbnailModule()


@pytest.fixture
def thumb_dry(dry_settings):
    with patch("omnicast.media.base.get_settings", return_value=dry_settings):
        return ThumbnailModule()


class TestThumbnailDryRun:
    @pytest.mark.asyncio
    async def test_dry_run_3_variants(self, thumb_dry):
        req = ThumbnailRequest(title="Top 10 Tips")
        result = await thumb_dry.process(req)
        assert result.status == MediaStatus.DONE
        assert len(result.paths) == 3
        assert result.selected_variant == result.paths[0]

    @pytest.mark.asyncio
    async def test_dry_run_custom_variants(self, thumb_dry):
        req = ThumbnailRequest(title="X", variants=2)
        result = await thumb_dry.process(req)
        assert len(result.paths) == 2

    @pytest.mark.asyncio
    async def test_dry_run_variant_names(self, thumb_dry):
        req = ThumbnailRequest(title="X", variants=3)
        result = await thumb_dry.process(req)
        assert "A" in result.paths[0]
        assert "B" in result.paths[1]
        assert "C" in result.paths[2]


class TestThumbnailModule:
    def test_name(self, thumb):
        assert thumb.name == "thumbnail"

    def test_custom_comfyui_url(self, mock_settings):
        with patch("omnicast.media.base.get_settings", return_value=mock_settings):
            t = ThumbnailModule(comfyui_url="http://gpu:8188")
            assert t.comfyui_url == "http://gpu:8188"
