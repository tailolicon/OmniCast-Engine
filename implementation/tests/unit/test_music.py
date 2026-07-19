import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from omnicast.media.music import MusicModule
from omnicast.media.models import MusicRequest, MusicResult, MusicSource, MediaStatus
from omnicast.shared.errors import MediaError


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
def music(mock_settings):
    with patch("omnicast.media.base.get_settings", return_value=mock_settings):
        return MusicModule()


@pytest.fixture
def music_dry(dry_settings):
    with patch("omnicast.media.base.get_settings", return_value=dry_settings):
        return MusicModule()


class TestMusicDryRun:
    @pytest.mark.asyncio
    async def test_dry_run_result(self, music_dry):
        req = MusicRequest(mood="epic", duration_seconds=120.0)
        result = await music_dry.process(req)
        assert isinstance(result, MusicResult)
        assert result.status == MediaStatus.DONE
        assert result.duration_seconds == 120.0

    @pytest.mark.asyncio
    async def test_dry_run_uses_first_priority(self, music_dry):
        req = MusicRequest(source_priority=[MusicSource.ROYALTY_FREE, MusicSource.ACE_STEP])
        result = await music_dry.process(req)
        assert result.source_used == MusicSource.ROYALTY_FREE

    @pytest.mark.asyncio
    async def test_dry_run_bpm(self, music_dry):
        req = MusicRequest(bpm_range=(100, 120))
        result = await music_dry.process(req)
        assert result.bpm == 100


class TestMusicPriorityChain:
    @pytest.mark.asyncio
    async def test_first_source_succeeds(self, music):
        yt_result = MusicResult(
            audio_path="/nas/music/track.wav", source_used=MusicSource.YT_AUDIO_LIB,
            duration_seconds=60.0, status=MediaStatus.DONE,
        )
        with patch.object(music, "_search_yt_library", new_callable=AsyncMock, return_value=yt_result):
            result = await music._process(MusicRequest())
            assert result.source_used == MusicSource.YT_AUDIO_LIB

    @pytest.mark.asyncio
    async def test_fallback_to_second(self, music):
        rf_result = MusicResult(
            audio_path="/nas/music/rf.wav", source_used=MusicSource.ROYALTY_FREE,
            duration_seconds=60.0, attribution="Artist - CC BY", status=MediaStatus.DONE,
        )
        with patch.object(music, "_search_yt_library", new_callable=AsyncMock, return_value=None), \
             patch.object(music, "_search_royalty_free", new_callable=AsyncMock, return_value=rf_result):
            result = await music._process(MusicRequest())
            assert result.source_used == MusicSource.ROYALTY_FREE

    @pytest.mark.asyncio
    async def test_fallback_to_ai(self, music):
        ace_result = MusicResult(
            audio_path="/tmp/gen.wav", source_used=MusicSource.ACE_STEP,
            duration_seconds=60.0, status=MediaStatus.DONE,
        )
        with patch.object(music, "_search_yt_library", new_callable=AsyncMock, return_value=None), \
             patch.object(music, "_search_royalty_free", new_callable=AsyncMock, return_value=None), \
             patch.object(music, "_generate_ace_step", new_callable=AsyncMock, return_value=ace_result):
            result = await music._process(MusicRequest())
            assert result.source_used == MusicSource.ACE_STEP

    @pytest.mark.asyncio
    async def test_all_fail_raises(self, music):
        with patch.object(music, "_try_source", new_callable=AsyncMock, return_value=None):
            with pytest.raises(MediaError, match="exhausted"):
                await music._process(MusicRequest())

    @pytest.mark.asyncio
    async def test_source_error_continues(self, music):
        ace_result = MusicResult(
            audio_path="/tmp/gen.wav", source_used=MusicSource.ACE_STEP,
            duration_seconds=60.0, status=MediaStatus.DONE,
        )
        with patch.object(music, "_search_yt_library", new_callable=AsyncMock, side_effect=RuntimeError("disk")), \
             patch.object(music, "_search_royalty_free", new_callable=AsyncMock, side_effect=RuntimeError("net")), \
             patch.object(music, "_generate_ace_step", new_callable=AsyncMock, return_value=ace_result):
            result = await music._process(MusicRequest())
            assert result.source_used == MusicSource.ACE_STEP


class TestMusicModule:
    def test_name(self, music):
        assert music.name == "music"

    @pytest.mark.asyncio
    async def test_try_source_dispatch(self, music):
        with patch.object(music, "_search_yt_library", new_callable=AsyncMock, return_value=None) as mock_yt:
            await music._try_source(MusicSource.YT_AUDIO_LIB, MusicRequest())
            mock_yt.assert_called_once()

        with patch.object(music, "_generate_ace_step", new_callable=AsyncMock, return_value=None) as mock_ace:
            await music._try_source(MusicSource.ACE_STEP, MusicRequest())
            mock_ace.assert_called_once()

    @pytest.mark.asyncio
    async def test_custom_priority(self, music):
        mg_result = MusicResult(
            audio_path="/tmp/mg.wav", source_used=MusicSource.MUSICGEN,
            duration_seconds=60.0, status=MediaStatus.DONE,
        )
        with patch.object(music, "_generate_musicgen", new_callable=AsyncMock, return_value=mg_result):
            result = await music._process(
                MusicRequest(source_priority=[MusicSource.MUSICGEN])
            )
            assert result.source_used == MusicSource.MUSICGEN
