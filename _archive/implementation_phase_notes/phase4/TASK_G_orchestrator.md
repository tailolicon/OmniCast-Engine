# TASK_G: Media Pipeline Orchestrator

## Model: sonnet | Dependencies: TASK_A-F complete

Orchestrate all media modules into single pipeline: script → TTS → images → video → music → subtitle → thumbnail → FFmpeg render → fingerprint.

## Interface

### src/omnicast/media/orchestrator.py

```python
"""Media Pipeline Orchestrator. Runs all modules in correct order with parallel where possible."""

from __future__ import annotations
import asyncio
import structlog
from omnicast.media.base import BaseMediaModule
from omnicast.media.models import (
    MediaPipelineState, MediaStatus, RenderJob, RenderLayer,
    TTSRequest, TTSResult, ImageGenRequest, ImageGenResult,
    VideoGenRequest, VideoGenResult, MusicRequest, MusicResult,
    SubtitleRequest, SubtitleResult, ThumbnailRequest, ThumbnailResult,
    RenderResult, ContentFingerprint,
)
from omnicast.media.tts import TTSModule
from omnicast.media.image_gen import ImageGenModule
from omnicast.media.video_gen import VideoGenModule
from omnicast.media.music import MusicModule
from omnicast.media.subtitle import SubtitleModule
from omnicast.media.thumbnail import ThumbnailModule
from omnicast.media.ffmpeg import FFmpegModule
from omnicast.media.fingerprint import FingerprintModule
from omnicast.models.schemas import BrandConfig
from omnicast.shared.errors import MediaError

logger = structlog.get_logger()


class MediaPipelineOrchestrator:
    """Run full media pipeline for one video.

    Execution order:
    1. TTS (voiceover from script) — sequential, needed first
    2. Parallel group:
       - Image generation (scene images)
       - Music selection/generation
    3. Video gen (optional, needs images from step 2)
    4. Subtitle (needs TTS audio from step 1)
    5. Thumbnail (needs images from step 2)
    6. FFmpeg render (needs all above)
    7. Content fingerprint (needs rendered video)
    """

    def __init__(
        self,
        tts: TTSModule | None = None,
        image_gen: ImageGenModule | None = None,
        video_gen: VideoGenModule | None = None,
        music: MusicModule | None = None,
        subtitle: SubtitleModule | None = None,
        thumbnail: ThumbnailModule | None = None,
        ffmpeg: FFmpegModule | None = None,
        fingerprint: FingerprintModule | None = None,
    ) -> None:
        self.tts = tts or TTSModule()
        self.image_gen = image_gen or ImageGenModule()
        self.video_gen = video_gen or VideoGenModule()
        self.music = music or MusicModule()
        self.subtitle = subtitle or SubtitleModule()
        self.thumbnail = thumbnail or ThumbnailModule()
        self.ffmpeg = ffmpeg or FFmpegModule()
        self.fingerprint = fingerprint or FingerprintModule()

    async def run(
        self,
        video_id: str,
        channel_id: str,
        script_text: str,
        scene_prompts: list[str],
        brand: BrandConfig,
        output_dir: str,
        existing_fingerprints: list[ContentFingerprint] | None = None,
    ) -> tuple[MediaPipelineState, RenderResult | None, ContentFingerprint | None]:
        """Execute full pipeline. Returns (state, render_result, fingerprint).

        Steps:
        1. Run TTS → get audio path + duration
        2. Parallel: image gen (all scenes) + music search
        3. Optional: video gen (if brand.use_video_gen)
        4. Subtitle from TTS audio
        5. Thumbnail from first scene image
        6. Build RenderJob layers → FFmpeg render
        7. Fingerprint check → reject if duplicate
        """
        state = MediaPipelineState(video_id=video_id, channel_id=channel_id)

        # Step 1: TTS
        tts_result = await self._run_tts(script_text, brand, output_dir)
        state = state.model_copy(update={"tts": MediaStatus.DONE if tts_result else MediaStatus.FAILED})
        if not tts_result:
            return state, None, None

        # Step 2: Parallel — images + music
        image_results, music_result = await self._run_parallel_media(
            scene_prompts, brand, output_dir
        )
        state = state.model_copy(update={
            "images": MediaStatus.DONE if image_results else MediaStatus.FAILED,
            "music": MediaStatus.DONE if music_result else MediaStatus.FAILED,
        })

        # Step 3: Optional video gen
        video_results = None
        if brand.use_video_gen and image_results:
            video_results = await self._run_video_gen(scene_prompts, image_results, brand, output_dir)
            state = state.model_copy(update={
                "video_gen": MediaStatus.DONE if video_results else MediaStatus.FAILED
            })
        else:
            state = state.model_copy(update={"video_gen": MediaStatus.SKIPPED})

        # Step 4: Subtitle
        sub_result = await self._run_subtitle(tts_result, output_dir)
        state = state.model_copy(update={
            "subtitle": MediaStatus.DONE if sub_result else MediaStatus.FAILED
        })

        # Step 5: Thumbnail
        thumb_result = await self._run_thumbnail(
            video_id, image_results, brand, output_dir
        )
        state = state.model_copy(update={
            "thumbnail": MediaStatus.DONE if thumb_result else MediaStatus.FAILED
        })

        if state.has_failure:
            return state, None, None

        # Step 6: FFmpeg render
        render_result = await self._run_render(
            video_id, channel_id, tts_result, image_results, video_results,
            music_result, sub_result, brand, output_dir
        )
        state = state.model_copy(update={
            "render": MediaStatus.DONE if render_result else MediaStatus.FAILED
        })

        if not render_result:
            return state, None, None

        # Step 7: Fingerprint
        fp = self._run_fingerprint(video_id, script_text, image_results, tts_result)
        if existing_fingerprints:
            dup = self.fingerprint.check_duplicate(fp, existing_fingerprints)
            if dup:
                logger.warning("Duplicate detected", video_id=video_id, duplicate_of=dup.video_id)
                state = state.model_copy(update={"fingerprint": MediaStatus.FAILED})
                return state, render_result, fp

        state = state.model_copy(update={"fingerprint": MediaStatus.DONE})
        return state, render_result, fp

    async def _run_tts(self, script_text: str, brand: BrandConfig, output_dir: str) -> TTSResult | None:
        """Build TTSRequest from brand config and run."""
        try:
            req = TTSRequest(
                text=script_text,
                voice_profile=brand.voice_profile,
                voice_clone=brand.voice_clone,
                output_path=f"{output_dir}/voiceover.wav",
            )
            return await self.tts.process(req)
        except Exception as exc:
            logger.error("TTS failed", error=str(exc))
            return None

    async def _run_parallel_media(
        self, scene_prompts: list[str], brand: BrandConfig, output_dir: str,
    ) -> tuple[list[ImageGenResult] | None, MusicResult | None]:
        """Run image gen + music in parallel."""
        image_task = self._run_images(scene_prompts, brand, output_dir)
        music_task = self._run_music(brand, output_dir)
        images, music = await asyncio.gather(image_task, music_task, return_exceptions=True)
        img_result = images if isinstance(images, list) else None
        mus_result = music if isinstance(music, MusicResult) else None
        return img_result, mus_result

    async def _run_images(self, prompts: list[str], brand: BrandConfig, output_dir: str) -> list[ImageGenResult]:
        """Generate all scene images."""
        results = []
        for i, prompt in enumerate(prompts):
            req = ImageGenRequest(
                prompt=prompt,
                backend=brand.image_gen_mode,
                output_path=f"{output_dir}/scene_{i:03d}.png",
            )
            results.append(await self.image_gen.process(req))
        return results

    async def _run_music(self, brand: BrandConfig, output_dir: str) -> MusicResult:
        req = MusicRequest(
            bpm_range=brand.music_bpm_range,
            output_path=f"{output_dir}/music_bg.wav",
        )
        return await self.music.process(req)

    async def _run_video_gen(
        self, prompts: list[str], images: list[ImageGenResult],
        brand: BrandConfig, output_dir: str,
    ) -> list[VideoGenResult] | None:
        try:
            results = []
            for i, (prompt, img) in enumerate(zip(prompts, images)):
                req = VideoGenRequest(
                    prompt=prompt,
                    source_image=img.image_path,
                    output_path=f"{output_dir}/clip_{i:03d}.mp4",
                )
                results.append(await self.video_gen.process(req))
            return results
        except Exception as exc:
            logger.error("Video gen failed", error=str(exc))
            return None

    async def _run_subtitle(self, tts_result: TTSResult, output_dir: str) -> SubtitleResult | None:
        try:
            req = SubtitleRequest(
                audio_path=tts_result.audio_path,
                output_path=f"{output_dir}/subtitle.srt",
            )
            return await self.subtitle.process(req)
        except Exception as exc:
            logger.error("Subtitle failed", error=str(exc))
            return None

    async def _run_thumbnail(
        self, video_id: str, images: list[ImageGenResult] | None,
        brand: BrandConfig, output_dir: str,
    ) -> ThumbnailResult | None:
        try:
            req = ThumbnailRequest(
                title=video_id,
                style=brand.thumbnail_style,
                source_image=images[0].image_path if images else None,
                color_palette=brand.color_palette,
                font=brand.font,
                output_dir=f"{output_dir}/thumbnails",
            )
            return await self.thumbnail.process(req)
        except Exception as exc:
            logger.error("Thumbnail failed", error=str(exc))
            return None

    async def _run_render(
        self, video_id: str, channel_id: str,
        tts_result: TTSResult, images: list[ImageGenResult] | None,
        videos: list[VideoGenResult] | None, music: MusicResult | None,
        subtitle: SubtitleResult | None, brand: BrandConfig, output_dir: str,
    ) -> RenderResult | None:
        try:
            layers = []
            # Video/image layer
            if videos:
                for v in videos:
                    layers.append(RenderLayer(layer_type="video", file_path=v.video_path))
            elif images:
                for img in images:
                    layers.append(RenderLayer(layer_type="video", file_path=img.image_path))

            # Voiceover
            layers.append(RenderLayer(layer_type="voiceover", file_path=tts_result.audio_path))

            # Music
            if music:
                layers.append(RenderLayer(layer_type="music", file_path=music.audio_path, volume_db=-20.0))

            # Subtitle
            if subtitle:
                layers.append(RenderLayer(layer_type="subtitle", file_path=subtitle.srt_path))

            # Intro/outro
            if brand.intro_template:
                layers.append(RenderLayer(layer_type="intro_outro", file_path=brand.intro_template))
            if brand.outro_template:
                layers.append(RenderLayer(layer_type="intro_outro", file_path=brand.outro_template))

            job = RenderJob(
                job_id=f"render_{video_id}",
                channel_id=channel_id,
                layers=layers,
                output_path=f"{output_dir}/final_video.mp4",
            )
            return await self.ffmpeg.process(job)
        except Exception as exc:
            logger.error("Render failed", error=str(exc))
            return None

    def _run_fingerprint(
        self, video_id: str, script_text: str,
        images: list[ImageGenResult] | None, tts_result: TTSResult,
    ) -> ContentFingerprint:
        image_paths = [img.image_path for img in images] if images else []
        return self.fingerprint.build_fingerprint(
            video_id=video_id,
            script_text=script_text,
            image_paths=image_paths,
            audio_path=tts_result.audio_path,
        )
```

## DO NOT

- No actual module processing in tests — mock all modules
- No direct file I/O — all paths are passed through models
- No modifying other media modules
- Orchestrator must use model_copy() for state updates (immutable)
- Duplicate detection MUST check before returning success

## Tests

### tests/unit/test_media_orchestrator.py

```python
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
    return TTSResult(audio_path="/tmp/voice.wav", duration_seconds=60.0, status=MediaStatus.DONE)


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
    return RenderResult(output_path="/tmp/final.mp4", duration_seconds=300.0,
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


@pytest.fixture
def orch(mock_modules):
    return MediaPipelineOrchestrator(**mock_modules)


class TestOrchestratorHappyPath:
    @pytest.mark.asyncio
    async def test_full_pipeline_success(self, orch, brand):
        state, render, fp = await orch.run(
            video_id="v1", channel_id="ch1",
            script_text="Hello world", scene_prompts=["scene1", "scene2", "scene3"],
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
    async def test_video_gen_skipped_by_default(self, orch, brand):
        state, _, _ = await orch.run(
            video_id="v1", channel_id="ch1",
            script_text="Hi", scene_prompts=["s1"],
            brand=brand, output_dir="/tmp",
        )
        assert state.video_gen == MediaStatus.SKIPPED


class TestOrchestratorFailures:
    @pytest.mark.asyncio
    async def test_tts_failure_stops_pipeline(self, mock_modules, brand):
        mock_modules["tts"].process = AsyncMock(side_effect=RuntimeError("TTS crash"))
        orch = MediaPipelineOrchestrator(**mock_modules)
        state, render, fp = await orch.run(
            video_id="v1", channel_id="ch1",
            script_text="Hi", scene_prompts=["s1"],
            brand=brand, output_dir="/tmp",
        )
        assert state.tts == MediaStatus.FAILED
        assert render is None

    @pytest.mark.asyncio
    async def test_image_failure_stops_render(self, mock_modules, brand):
        mock_modules["image_gen"].process = AsyncMock(side_effect=RuntimeError("GPU OOM"))
        orch = MediaPipelineOrchestrator(**mock_modules)
        state, render, _ = await orch.run(
            video_id="v1", channel_id="ch1",
            script_text="Hi", scene_prompts=["s1"],
            brand=brand, output_dir="/tmp",
        )
        assert state.images == MediaStatus.FAILED
        assert render is None


class TestOrchestratorDuplicate:
    @pytest.mark.asyncio
    async def test_duplicate_detected(self, mock_modules, brand):
        existing_fp = ContentFingerprint(
            video_id="v_old", script_hash="abc", visual_hashes=["h1"],
            audio_fingerprint="a", music_fingerprint="m", structure_signature="s",
        )
        mock_modules["fingerprint"].check_duplicate = MagicMock(return_value=existing_fp)
        orch = MediaPipelineOrchestrator(**mock_modules)
        state, render, fp = await orch.run(
            video_id="v1", channel_id="ch1",
            script_text="Hi", scene_prompts=["s1"],
            brand=brand, output_dir="/tmp",
            existing_fingerprints=[existing_fp],
        )
        assert state.fingerprint == MediaStatus.FAILED
        assert render is not None  # render completed, but flagged as duplicate
        assert fp is not None


class TestOrchestratorVideoGen:
    @pytest.mark.asyncio
    async def test_video_gen_enabled(self, mock_modules):
        brand = BrandConfig(channel_id="ch1", use_video_gen=True)
        orch = MediaPipelineOrchestrator(**mock_modules)
        state, _, _ = await orch.run(
            video_id="v1", channel_id="ch1",
            script_text="Hi", scene_prompts=["s1"],
            brand=brand, output_dir="/tmp",
        )
        assert state.video_gen == MediaStatus.DONE


class TestOrchestratorState:
    @pytest.mark.asyncio
    async def test_state_is_immutable(self, orch, brand):
        state, _, _ = await orch.run(
            video_id="v1", channel_id="ch1",
            script_text="Hi", scene_prompts=["s1"],
            brand=brand, output_dir="/tmp",
        )
        assert isinstance(state, MediaPipelineState)
        with pytest.raises(Exception):
            state.tts = MediaStatus.PENDING

    @pytest.mark.asyncio
    async def test_all_done_property(self, orch, brand):
        state, _, _ = await orch.run(
            video_id="v1", channel_id="ch1",
            script_text="Hi", scene_prompts=["s1"],
            brand=brand, output_dir="/tmp",
        )
        assert state.all_done
```
