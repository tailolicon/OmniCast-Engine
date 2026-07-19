import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from omnicast.media.ffmpeg import FFmpegModule
from omnicast.media.models import (
    RenderJob, RenderResult, RenderLayer, MediaStatus,
)
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
def ffm(mock_settings):
    with patch("omnicast.media.base.get_settings", return_value=mock_settings):
        return FFmpegModule()


@pytest.fixture
def ffm_dry(dry_settings):
    with patch("omnicast.media.base.get_settings", return_value=dry_settings):
        return FFmpegModule()


@pytest.fixture
def valid_layers():
    return [
        RenderLayer(layer_type="video", file_path="/tmp/clips.txt"),
        RenderLayer(layer_type="voiceover", file_path="/tmp/voice.wav"),
        RenderLayer(layer_type="music", file_path="/tmp/bg.wav", volume_db=-20.0),
        RenderLayer(layer_type="subtitle", file_path="/tmp/sub.srt"),
    ]


@pytest.fixture
def valid_job(valid_layers):
    return RenderJob(job_id="j1", channel_id="ch1", layers=valid_layers, output_path="/tmp/final.mp4")


class TestFFmpegDryRun:
    @pytest.mark.asyncio
    async def test_dry_run(self, ffm_dry, valid_job):
        result = await ffm_dry.process(valid_job)
        assert result.status == MediaStatus.DONE

    @pytest.mark.asyncio
    async def test_dry_run_output_path(self, ffm_dry):
        job = RenderJob(job_id="j1", channel_id="ch1", output_path="/out/video.mp4")
        result = await ffm_dry.process(job)
        assert result.output_path == "/out/video.mp4"


class TestFFmpegValidation:
    def test_missing_video_layer(self, ffm):
        layers = [RenderLayer(layer_type="voiceover", file_path="/tmp/v.wav")]
        with pytest.raises(MediaError, match="video"):
            ffm._validate_layers(layers)

    def test_missing_voiceover_layer(self, ffm):
        layers = [RenderLayer(layer_type="video", file_path="/tmp/c.mp4")]
        with pytest.raises(MediaError, match="voiceover"):
            ffm._validate_layers(layers)

    def test_valid_layers_pass(self, ffm, valid_layers):
        ffm._validate_layers(valid_layers)  # should not raise


class TestFFmpegCommand:
    def test_build_command_returns_list(self, ffm, valid_job):
        cmd = ffm._build_command(valid_job)
        assert isinstance(cmd, list)
        assert len(cmd) > 0
        assert cmd[0] == "ffmpeg" or "ffmpeg" in cmd[0]

    def test_build_command_includes_codec(self, ffm, valid_job):
        cmd = ffm._build_command(valid_job)
        cmd_str = " ".join(cmd)
        assert "h264" in cmd_str or "libx264" in cmd_str

    def test_build_command_includes_output(self, ffm, valid_job):
        cmd = ffm._build_command(valid_job)
        assert valid_job.output_path in cmd


class TestFFmpegModule:
    def test_name(self, ffm):
        assert ffm.name == "ffmpeg"

    @pytest.mark.asyncio
    async def test_process_calls_validate(self, ffm, valid_job):
        with patch.object(ffm, "_validate_layers") as mock_v, \
             patch.object(ffm, "_build_command", return_value=["ffmpeg"]), \
             patch.object(ffm, "_run_ffmpeg", new_callable=AsyncMock,
                          return_value=RenderResult(status=MediaStatus.DONE)):
            await ffm._process(valid_job)
            mock_v.assert_called_once()
