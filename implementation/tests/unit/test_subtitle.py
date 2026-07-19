import pytest
from unittest.mock import patch, MagicMock
from omnicast.media.subtitle import SubtitleModule
from omnicast.media.models import SubtitleRequest, SubtitleResult, MediaStatus


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
def sub(mock_settings):
    with patch("omnicast.media.base.get_settings", return_value=mock_settings):
        return SubtitleModule()


@pytest.fixture
def sub_dry(dry_settings):
    with patch("omnicast.media.base.get_settings", return_value=dry_settings):
        return SubtitleModule()


class TestSubtitleDryRun:
    @pytest.mark.asyncio
    async def test_dry_run(self, sub_dry):
        req = SubtitleRequest(audio_path="/tmp/audio.wav")
        result = await sub_dry.process(req)
        assert result.status == MediaStatus.DONE
        assert "dry_run" in result.srt_path

    @pytest.mark.asyncio
    async def test_dry_run_custom_path(self, sub_dry):
        req = SubtitleRequest(audio_path="/tmp/audio.wav", output_path="/tmp/sub.srt")
        result = await sub_dry.process(req)
        assert result.srt_path == "/tmp/sub.srt"


class TestSubtitleModule:
    def test_name(self, sub):
        assert sub.name == "subtitle"

    def test_write_srt_format(self, sub):
        segments = [
            {"start": 0.0, "end": 2.5, "text": "Hello world"},
            {"start": 2.5, "end": 5.0, "text": "How are you"},
        ]
        import tempfile, os
        with tempfile.NamedTemporaryFile(suffix=".srt", delete=False, mode="w") as f:
            path = f.name
        try:
            count = sub._write_srt(segments, path)
            assert count >= 4  # at least 4 words
            with open(path) as f:
                content = f.read()
            assert "1\n" in content
            assert "-->" in content
            assert "Hello world" in content
        finally:
            os.unlink(path)
