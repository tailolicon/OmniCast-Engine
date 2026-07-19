import pytest
from unittest.mock import patch, MagicMock
from omnicast.media.base import BaseMediaModule
from omnicast.media.models import TTSRequest, TTSResult, MediaStatus


class MockModule(BaseMediaModule):
    name = "mock_tts"

    def __init__(self, fail=False):
        super().__init__()
        self._fail = fail

    async def _process(self, request):
        if self._fail:
            raise RuntimeError("GPU exploded")
        return TTSResult(audio_path="/tmp/out.wav", duration_seconds=5.0)

    def _dry_run_result(self, request):
        return TTSResult(audio_path="dry_run.wav", duration_seconds=1.0, status=MediaStatus.DONE)


@pytest.fixture
def mock_settings():
    s = MagicMock()
    s.is_dry_run = False
    return s


class TestBaseMediaModule:
    @pytest.mark.asyncio
    async def test_process_success(self, mock_settings):
        with patch("omnicast.media.base.get_settings", return_value=mock_settings):
            mod = MockModule()
            result = await mod.process(TTSRequest(text="Hello"))
            assert isinstance(result, TTSResult)
            assert result.audio_path == "/tmp/out.wav"

    @pytest.mark.asyncio
    async def test_process_error_raises(self, mock_settings):
        with patch("omnicast.media.base.get_settings", return_value=mock_settings):
            mod = MockModule(fail=True)
            with pytest.raises(RuntimeError, match="GPU exploded"):
                await mod.process(TTSRequest(text="Hello"))

    @pytest.mark.asyncio
    async def test_dry_run_mode(self):
        dry_settings = MagicMock()
        dry_settings.is_dry_run = True
        with patch("omnicast.media.base.get_settings", return_value=dry_settings):
            mod = MockModule()
            result = await mod.process(TTSRequest(text="Hello"))
            assert result.audio_path == "dry_run.wav"

    def test_cannot_instantiate_abstract(self, mock_settings):
        with patch("omnicast.media.base.get_settings", return_value=mock_settings):
            with pytest.raises(TypeError):
                BaseMediaModule()

    def test_name_attribute(self, mock_settings):
        with patch("omnicast.media.base.get_settings", return_value=mock_settings):
            assert MockModule().name == "mock_tts"

    @pytest.mark.asyncio
    async def test_dry_run_skips_process(self):
        dry_settings = MagicMock()
        dry_settings.is_dry_run = True
        with patch("omnicast.media.base.get_settings", return_value=dry_settings):
            mod = MockModule(fail=True)  # would fail if _process called
            result = await mod.process(TTSRequest(text="Hello"))
            assert result.status == MediaStatus.DONE
