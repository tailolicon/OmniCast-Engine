import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from omnicast.media.orchestrator import MediaPipelineOrchestrator
from omnicast.media.models import (
    MediaPipelineState, MediaStatus,
    TTSResult, TTSEngine, ImageGenResult, ImageGenBackend,
    VideoGenResult, VideoGenBackend, MusicResult, MusicSource,
    SubtitleResult, ThumbnailResult, RenderResult,
    ContentFingerprint,
)
from omnicast.models.schemas import BrandConfig


@pytest.fixture
def brand():
    return BrandConfig(channel_id="ch1")


@pytest.fixture
def tts_result():
    return TTSResult(audio_path="/tmp/voice.wav", duration_seconds=600.0, status=MediaStatus.DONE)


@pytest.fixture
def long_script():
    return " ".join(["scriptword"] * 1500)


@pytest.fixture
def image_results():
    return [
        ImageGenResult(image_path=f"/tmp/scene_{i}.png", status=MediaStatus.DONE)
        for i in range(3)
    ]


@pytest.fixture
def music_result():
    return MusicResult(audio_path="/tmp/music.wav", source_used=MusicSource.YT_AUDIO_LIB,
                       duration_seconds=120.0, status=MediaStatus.DONE)


@pytest.fixture
def sub_result():
    return SubtitleResult(srt_path="/tmp/sub.srt", word_count=100, status=MediaStatus.DONE)


@pytest.fixture
def thumb_result():
    return ThumbnailResult(paths=["/tmp/a.jpg", "/tmp/b.jpg", "/tmp/c.jpg"],
                            selected_variant="/tmp/a.jpg", status=MediaStatus.DONE)


@pytest.fixture
def render_result():
    return RenderResult(output_path="/tmp/final.mp4", duration_seconds=600.0,
                         file_size_mb=150.0, status=MediaStatus.DONE)


@pytest.fixture
def mock_fp():
    return ContentFingerprint(video_id="v1", script_hash="abc")


@pytest.fixture
def mock_modules(tts_result, image_results, music_result, sub_result, thumb_result, render_result, mock_fp):
    tts = MagicMock()
    tts.process = AsyncMock(return_value=tts_result)
    img = MagicMock()
    img.process = AsyncMock(side_effect=image_results)
    vg = MagicMock()
    vg.process = AsyncMock(return_value=VideoGenResult(status=MediaStatus.DONE))
    mus = MagicMock()
    mus.process = AsyncMock(return_value=music_result)
    sub = MagicMock()
    sub.process = AsyncMock(return_value=sub_result)
    thumb = MagicMock()
    thumb.process = AsyncMock(return_value=thumb_result)
    ffm = MagicMock()
    ffm.process = AsyncMock(return_value=render_result)
    fp = MagicMock()
    fp.build_fingerprint = MagicMock(return_value=mock_fp)
    fp.check_duplicate = MagicMock(return_value=None)
    return {"tts": tts, "image_gen": img, "video_gen": vg, "music": mus,
            "subtitle": sub, "thumbnail": thumb, "ffmpeg": ffm, "fingerprint": fp}


@pytest.fixture(autouse=True)
def _mock_media_providers(image_results, monkeypatch):
    """Stub the provider registry so orchestrator's _run_images / _run_video_gen
    don't try to hit real Gemini APIs (deferred-validation providers raise on
    missing GOOGLE_API_KEY when generate/convert is called).
    """
    from omnicast.media.providers import registry as _reg

    saved_img = dict(_reg._IMAGE_PROVIDERS)
    saved_vid = dict(_reg._VIDEO_PROVIDERS)

    class _MockImageProvider:
        id = "gemini"
        name = "MockImage"
        models: list = []
        def __init__(self):
            self._i = 0
        async def generate(self, prompt, *, negative="", model=None, resolution=None, output_path):
            r = image_results[self._i % len(image_results)]
            self._i += 1
            return r.image_path

    class _MockVideoProvider:
        id = "gemini"
        name = "MockVideo"
        models: list = []
        async def convert(self, image_path, prompt, *, duration=5, model=None, resolution=None, output_path):
            return output_path

    _reg.register_image_provider("gemini", _MockImageProvider())
    _reg.register_video_provider("gemini", _MockVideoProvider())
    settings = MagicMock()
    settings.media_image_provider = "gemini"
    settings.media_image_model = None
    settings.media_video_provider = "gemini"
    settings.media_video_model = None
    monkeypatch.setattr("omnicast.media.orchestrator.get_settings", lambda: settings)
    monkeypatch.setattr(
        "omnicast.media.orchestrator._resolve_provider",
        lambda kind, default_provider, default_model=None: ("gemini", default_model),
    )

    yield

    _reg._IMAGE_PROVIDERS.clear()
    _reg._IMAGE_PROVIDERS.update(saved_img)
    _reg._VIDEO_PROVIDERS.clear()
    _reg._VIDEO_PROVIDERS.update(saved_vid)


@pytest.fixture
def orch(mock_modules):
    return MediaPipelineOrchestrator(**mock_modules)


class TestOrchestratorHappyPath:
    @pytest.mark.asyncio
    async def test_full_pipeline_success(self, orch, brand, long_script):
        state, render, fp = await orch.run(
            video_id="v1", channel_id="ch1",
            script_text=long_script, scene_prompts=["scene1", "scene2", "scene3"],
            brand=brand, output_dir="/tmp/out",
        )
        assert state.tts == MediaStatus.DONE
        assert state.images == MediaStatus.DONE
        assert state.music == MediaStatus.DONE
        assert state.subtitle == MediaStatus.DONE
        assert state.thumbnail == MediaStatus.DONE
        assert state.render == MediaStatus.DONE
        assert state.fingerprint == MediaStatus.DONE
        assert render is not None
        assert fp is not None

    @pytest.mark.asyncio
    async def test_video_gen_skipped_by_default(self, orch, brand, long_script):
        state, _, _ = await orch.run(
            video_id="v1", channel_id="ch1",
            script_text=long_script, scene_prompts=["s1"],
            brand=brand, output_dir="/tmp",
        )
        assert state.video_gen == MediaStatus.SKIPPED

    @pytest.mark.asyncio
    async def test_short_script_fails_before_tts(self, orch, brand):
        state, render, fp = await orch.run(
            video_id="v1", channel_id="ch1",
            script_text="too short", scene_prompts=["s1"],
            brand=brand, output_dir="/tmp",
        )
        assert state.tts == MediaStatus.FAILED
        assert render is None
        assert fp is None
        orch.tts.process.assert_not_awaited()


class TestOrchestratorFailures:
    @pytest.mark.asyncio
    async def test_tts_failure_stops_pipeline(self, mock_modules, brand, long_script):
        mock_modules["tts"].process = AsyncMock(side_effect=RuntimeError("TTS crash"))
        orch = MediaPipelineOrchestrator(**mock_modules)
        state, render, fp = await orch.run(
            video_id="v1", channel_id="ch1",
            script_text=long_script, scene_prompts=["s1"],
            brand=brand, output_dir="/tmp",
        )
        assert state.tts == MediaStatus.FAILED
        assert render is None

    @pytest.mark.asyncio
    async def test_short_voiceover_stops_before_media(self, mock_modules, brand, long_script):
        mock_modules["tts"].process = AsyncMock(
            return_value=TTSResult(audio_path="/tmp/voice.wav", duration_seconds=300.0, status=MediaStatus.DONE)
        )
        orch = MediaPipelineOrchestrator(**mock_modules)
        state, render, fp = await orch.run(
            video_id="v1", channel_id="ch1",
            script_text=long_script, scene_prompts=["s1"],
            brand=brand, output_dir="/tmp",
        )
        assert state.tts == MediaStatus.DONE
        assert state.render == MediaStatus.FAILED
        assert render is None
        assert fp is None
        mock_modules["image_gen"].process.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_image_failure_stops_render(self, mock_modules, brand, long_script):
        from omnicast.media.providers import registry as _reg

        class _FailingImageProvider:
            id = "gemini"
            name = "FailingImage"
            models: list = []
            async def generate(self, prompt, *, negative="", model=None, resolution=None, output_path):
                raise RuntimeError("GPU OOM")

        _reg.register_image_provider("gemini", _FailingImageProvider())

        orch = MediaPipelineOrchestrator(**mock_modules)
        state, render, _ = await orch.run(
            video_id="v1", channel_id="ch1",
            script_text=long_script, scene_prompts=["s1"],
            brand=brand, output_dir="/tmp",
        )
        assert state.images == MediaStatus.FAILED
        assert render is None


class TestOrchestratorDuplicate:
    @pytest.mark.asyncio
    async def test_duplicate_detected(self, mock_modules, brand, long_script):
        existing_fp = ContentFingerprint(
            video_id="v_old", script_hash="abc", visual_hashes=["h1"],
            audio_fingerprint="a", music_fingerprint="m", structure_signature="s",
        )
        mock_modules["fingerprint"].check_duplicate = MagicMock(return_value=existing_fp)
        orch = MediaPipelineOrchestrator(**mock_modules)
        state, render, fp = await orch.run(
            video_id="v1", channel_id="ch1",
            script_text=long_script, scene_prompts=["s1"],
            brand=brand, output_dir="/tmp",
            existing_fingerprints=[existing_fp],
        )
        assert state.fingerprint == MediaStatus.FAILED
        assert render is not None  # render completed, but flagged as duplicate
        assert fp is not None


class TestOrchestratorVideoGen:
    @pytest.mark.asyncio
    async def test_video_gen_enabled(self, mock_modules, long_script):
        brand = BrandConfig(channel_id="ch1", use_video_gen=True)
        orch = MediaPipelineOrchestrator(**mock_modules)
        state, _, _ = await orch.run(
            video_id="v1", channel_id="ch1",
            script_text=long_script, scene_prompts=["s1"],
            brand=brand, output_dir="/tmp",
        )
        assert state.video_gen == MediaStatus.DONE


class TestOrchestratorState:
    @pytest.mark.asyncio
    async def test_state_is_immutable(self, orch, brand, long_script):
        state, _, _ = await orch.run(
            video_id="v1", channel_id="ch1",
            script_text=long_script, scene_prompts=["s1"],
            brand=brand, output_dir="/tmp",
        )
        assert isinstance(state, MediaPipelineState)
        with pytest.raises(Exception):
            state.tts = MediaStatus.PENDING

    @pytest.mark.asyncio
    async def test_all_done_property(self, orch, brand, long_script):
        state, _, _ = await orch.run(
            video_id="v1", channel_id="ch1",
            script_text=long_script, scene_prompts=["s1"],
            brand=brand, output_dir="/tmp",
        )
        assert state.all_done
