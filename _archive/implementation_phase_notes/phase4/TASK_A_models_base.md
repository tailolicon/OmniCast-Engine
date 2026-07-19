# TASK_A: Media Models + Pipeline Base

## Model: sonnet | Dependencies: Phase 1-3 complete

Add `MediaError(OmnicastError)` to `shared/errors.py`. Create `src/omnicast/media/` package.

## Interface

### src/omnicast/media/models.py

```python
"""Pydantic models for Media Pipeline. All frozen, inherit OmnicastSchema."""

from __future__ import annotations
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from pydantic import Field
from omnicast.models.schemas import OmnicastSchema


class TTSEngine(StrEnum):
    KOKORO = "kokoro"
    XTTSV2 = "xttsv2"
    PIPER = "piper"


class ImageGenBackend(StrEnum):
    SDXL = "sdxl"
    FLUX = "flux"


class VideoGenBackend(StrEnum):
    WAN21 = "wan21"
    KEN_BURNS = "ken_burns"


class MusicSource(StrEnum):
    YT_AUDIO_LIB = "yt_audio_lib"
    ROYALTY_FREE = "royalty_free"
    ACE_STEP = "ace_step"
    MUSICGEN = "musicgen"


class MediaStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    SKIPPED = "skipped"


class TTSRequest(OmnicastSchema):
    """Input for TTS module."""
    text: str
    voice_profile: str = "kokoro_en_us_v1"
    voice_clone: str | None = None
    engine: TTSEngine = TTSEngine.KOKORO
    output_path: str = ""
    target_lufs: float = -14.0


class TTSResult(OmnicastSchema):
    audio_path: str = ""
    duration_seconds: float = 0.0
    engine_used: TTSEngine = TTSEngine.KOKORO
    sample_rate: int = 24000
    status: MediaStatus = MediaStatus.DONE


class ImageGenRequest(OmnicastSchema):
    prompt: str
    negative_prompt: str = ""
    backend: ImageGenBackend = ImageGenBackend.SDXL
    width: int = 1920
    height: int = 1080
    output_path: str = ""
    reference_image: str | None = None
    ip_adapter_weight: float = Field(default=0.6, ge=0.0, le=1.0)


class ImageGenResult(OmnicastSchema):
    image_path: str = ""
    backend_used: ImageGenBackend = ImageGenBackend.SDXL
    seed: int = 0
    status: MediaStatus = MediaStatus.DONE


class VideoGenRequest(OmnicastSchema):
    prompt: str
    backend: VideoGenBackend = VideoGenBackend.WAN21
    source_image: str | None = None
    duration_seconds: float = Field(default=5.0, ge=1.0, le=10.0)
    output_path: str = ""


class VideoGenResult(OmnicastSchema):
    video_path: str = ""
    duration_seconds: float = 0.0
    backend_used: VideoGenBackend = VideoGenBackend.WAN21
    status: MediaStatus = MediaStatus.DONE


class MusicRequest(OmnicastSchema):
    mood: str = "cinematic"
    genre: str = ""
    duration_seconds: float = 60.0
    bpm_range: tuple[int, int] = (120, 140)
    source_priority: list[MusicSource] = Field(
        default_factory=lambda: [MusicSource.YT_AUDIO_LIB, MusicSource.ROYALTY_FREE, MusicSource.ACE_STEP]
    )
    output_path: str = ""


class MusicResult(OmnicastSchema):
    audio_path: str = ""
    source_used: MusicSource = MusicSource.YT_AUDIO_LIB
    duration_seconds: float = 0.0
    bpm: int = 0
    license_info: str = ""
    attribution: str = ""
    status: MediaStatus = MediaStatus.DONE


class SubtitleRequest(OmnicastSchema):
    audio_path: str
    language: str = "en"
    output_path: str = ""


class SubtitleResult(OmnicastSchema):
    srt_path: str = ""
    word_count: int = 0
    duration_seconds: float = 0.0
    status: MediaStatus = MediaStatus.DONE


class ThumbnailRequest(OmnicastSchema):
    title: str
    style: str = "dark_contrast"
    source_image: str | None = None
    color_palette: list[str] = Field(default_factory=lambda: ["#1A1A2E", "#E94560", "#FFFFFF"])
    font: str = "Montserrat Bold"
    output_dir: str = ""
    variants: int = Field(default=3, ge=1, le=5)


class ThumbnailResult(OmnicastSchema):
    paths: list[str] = Field(default_factory=list)
    selected_variant: str = ""
    status: MediaStatus = MediaStatus.DONE


class RenderLayer(OmnicastSchema):
    """One layer in FFmpeg render."""
    layer_type: str  # video, voiceover, music, subtitle, intro_outro
    file_path: str
    volume_db: float = 0.0
    start_offset: float = 0.0


class RenderJob(OmnicastSchema):
    """Full FFmpeg render specification."""
    job_id: str
    channel_id: str
    layers: list[RenderLayer] = Field(default_factory=list)
    output_path: str = ""
    resolution: str = "1920x1080"
    codec: str = "h264"
    audio_codec: str = "aac"
    crossfade_seconds: float = 0.5
    music_duck_db: float = -20.0


class RenderResult(OmnicastSchema):
    output_path: str = ""
    duration_seconds: float = 0.0
    file_size_mb: float = 0.0
    status: MediaStatus = MediaStatus.DONE


class ContentFingerprint(OmnicastSchema):
    """Uniqueness fingerprint for duplicate detection."""
    video_id: str
    script_hash: str = ""
    visual_hashes: list[str] = Field(default_factory=list)
    audio_fingerprint: str = ""
    music_fingerprint: str = ""
    structure_signature: str = ""

    def similarity_score(self, other: ContentFingerprint) -> float:
        """Compare two fingerprints. >0.7 = too similar."""
        matches = 0
        total = 5
        if self.script_hash and self.script_hash == other.script_hash:
            matches += 1
        if self.visual_hashes and other.visual_hashes:
            overlap = len(set(self.visual_hashes) & set(other.visual_hashes))
            max_len = max(len(self.visual_hashes), len(other.visual_hashes))
            matches += (overlap / max_len) if max_len > 0 else 0
        if self.audio_fingerprint and self.audio_fingerprint == other.audio_fingerprint:
            matches += 1
        if self.music_fingerprint and self.music_fingerprint == other.music_fingerprint:
            matches += 1
        if self.structure_signature and self.structure_signature == other.structure_signature:
            matches += 1
        return matches / total


class MediaPipelineState(OmnicastSchema):
    """Tracks overall pipeline progress for one video."""
    video_id: str
    channel_id: str
    tts: MediaStatus = MediaStatus.PENDING
    images: MediaStatus = MediaStatus.PENDING
    video_gen: MediaStatus = MediaStatus.PENDING
    music: MediaStatus = MediaStatus.PENDING
    subtitle: MediaStatus = MediaStatus.PENDING
    thumbnail: MediaStatus = MediaStatus.PENDING
    render: MediaStatus = MediaStatus.PENDING
    fingerprint: MediaStatus = MediaStatus.PENDING

    @property
    def all_done(self) -> bool:
        return all(
            s in (MediaStatus.DONE, MediaStatus.SKIPPED)
            for s in [self.tts, self.images, self.video_gen, self.music,
                       self.subtitle, self.thumbnail, self.render, self.fingerprint]
        )

    @property
    def has_failure(self) -> bool:
        return any(
            s == MediaStatus.FAILED
            for s in [self.tts, self.images, self.video_gen, self.music,
                       self.subtitle, self.thumbnail, self.render, self.fingerprint]
        )
```

### src/omnicast/media/base.py

```python
"""Abstract base for all media modules. Subclasses implement _process()."""

from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Any
import time
import structlog
from omnicast.config.settings import get_settings

logger = structlog.get_logger()


class BaseMediaModule(ABC):
    name: str = "base"

    def __init__(self) -> None:
        self.settings = get_settings()

    @property
    def is_dry_run(self) -> bool:
        return self.settings.is_dry_run

    async def process(self, request: Any) -> Any:
        """Call _process() with timing + error logging. Dry-run returns _dry_run_result()."""
        start = time.time()
        try:
            if self.is_dry_run:
                result = self._dry_run_result(request)
                logger.info("Dry-run complete", module=self.name,
                            duration_s=round(time.time() - start, 2))
                return result
            result = await self._process(request)
            logger.info("Process complete", module=self.name,
                        duration_s=round(time.time() - start, 2))
            return result
        except Exception as exc:
            logger.error("Process failed", module=self.name, error=str(exc),
                         duration_s=round(time.time() - start, 2))
            raise

    @abstractmethod
    async def _process(self, request: Any) -> Any: ...

    @abstractmethod
    def _dry_run_result(self, request: Any) -> Any: ...
```

### src/omnicast/media/__init__.py

```python
"""Media Pipeline package."""
```

## DO NOT

- No external tool calls (Kokoro, ComfyUI, FFmpeg) — that's TASK_B-F
- No ORM models — pure Pydantic only
- No imports FROM media in existing modules
- similarity_score must be a method, not a standalone function

## Tests

### tests/unit/test_media_models.py

```python
import pytest
from pydantic import ValidationError
from omnicast.media.models import (
    TTSEngine, ImageGenBackend, VideoGenBackend, MusicSource, MediaStatus,
    TTSRequest, TTSResult, ImageGenRequest, ImageGenResult,
    VideoGenRequest, VideoGenResult, MusicRequest, MusicResult,
    SubtitleRequest, SubtitleResult, ThumbnailRequest, ThumbnailResult,
    RenderLayer, RenderJob, RenderResult,
    ContentFingerprint, MediaPipelineState,
)


class TestEnums:
    def test_tts_engine_values(self):
        assert TTSEngine.KOKORO == "kokoro"
        assert TTSEngine.XTTSV2 == "xttsv2"
        assert TTSEngine.PIPER == "piper"

    def test_media_status_values(self):
        assert MediaStatus.PENDING == "pending"
        assert MediaStatus.DONE == "done"
        assert MediaStatus.FAILED == "failed"

    def test_music_source_values(self):
        assert MusicSource.YT_AUDIO_LIB == "yt_audio_lib"
        assert MusicSource.ACE_STEP == "ace_step"


class TestTTSModels:
    def test_request_defaults(self):
        r = TTSRequest(text="Hello world")
        assert r.voice_profile == "kokoro_en_us_v1"
        assert r.engine == TTSEngine.KOKORO
        assert r.target_lufs == -14.0
        assert r.voice_clone is None

    def test_request_with_clone(self):
        r = TTSRequest(text="Hi", voice_clone="clone_v1", engine=TTSEngine.XTTSV2)
        assert r.voice_clone == "clone_v1"

    def test_result_defaults(self):
        r = TTSResult()
        assert r.status == MediaStatus.DONE
        assert r.sample_rate == 24000

    def test_frozen(self):
        r = TTSRequest(text="X")
        with pytest.raises(ValidationError):
            r.text = "Y"


class TestImageGenModels:
    def test_request_defaults(self):
        r = ImageGenRequest(prompt="A cat")
        assert r.backend == ImageGenBackend.SDXL
        assert r.width == 1920 and r.height == 1080
        assert r.ip_adapter_weight == 0.6

    def test_ip_adapter_bounds(self):
        ImageGenRequest(prompt="X", ip_adapter_weight=0.0)
        ImageGenRequest(prompt="X", ip_adapter_weight=1.0)
        with pytest.raises(ValidationError):
            ImageGenRequest(prompt="X", ip_adapter_weight=1.1)
        with pytest.raises(ValidationError):
            ImageGenRequest(prompt="X", ip_adapter_weight=-0.1)


class TestVideoGenModels:
    def test_request_defaults(self):
        r = VideoGenRequest(prompt="Ocean waves")
        assert r.backend == VideoGenBackend.WAN21
        assert r.duration_seconds == 5.0

    def test_duration_bounds(self):
        VideoGenRequest(prompt="X", duration_seconds=1.0)
        VideoGenRequest(prompt="X", duration_seconds=10.0)
        with pytest.raises(ValidationError):
            VideoGenRequest(prompt="X", duration_seconds=0.5)
        with pytest.raises(ValidationError):
            VideoGenRequest(prompt="X", duration_seconds=11.0)


class TestMusicModels:
    def test_request_defaults(self):
        r = MusicRequest()
        assert r.mood == "cinematic"
        assert r.bpm_range == (120, 140)
        assert len(r.source_priority) == 3
        assert r.source_priority[0] == MusicSource.YT_AUDIO_LIB

    def test_result_with_attribution(self):
        r = MusicResult(attribution="Track by Artist - CC BY 4.0", source_used=MusicSource.ROYALTY_FREE)
        assert r.attribution != ""


class TestSubtitleModels:
    def test_request(self):
        r = SubtitleRequest(audio_path="/tmp/audio.wav")
        assert r.language == "en"

    def test_result(self):
        r = SubtitleResult(srt_path="/tmp/sub.srt", word_count=150, duration_seconds=60.0)
        assert r.word_count == 150


class TestThumbnailModels:
    def test_request_defaults(self):
        r = ThumbnailRequest(title="Top 10 Tips")
        assert r.style == "dark_contrast"
        assert r.variants == 3
        assert len(r.color_palette) == 3

    def test_variants_bounds(self):
        ThumbnailRequest(title="X", variants=1)
        ThumbnailRequest(title="X", variants=5)
        with pytest.raises(ValidationError):
            ThumbnailRequest(title="X", variants=0)
        with pytest.raises(ValidationError):
            ThumbnailRequest(title="X", variants=6)


class TestRenderModels:
    def test_render_layer(self):
        l = RenderLayer(layer_type="music", file_path="/tmp/bg.wav", volume_db=-20.0)
        assert l.volume_db == -20.0

    def test_render_job_defaults(self):
        j = RenderJob(job_id="j1", channel_id="ch1")
        assert j.resolution == "1920x1080"
        assert j.codec == "h264"
        assert j.crossfade_seconds == 0.5
        assert j.music_duck_db == -20.0

    def test_render_result(self):
        r = RenderResult(output_path="/tmp/final.mp4", duration_seconds=300.0, file_size_mb=150.5)
        assert r.file_size_mb == 150.5


class TestContentFingerprint:
    def test_identical_score(self):
        fp = ContentFingerprint(
            video_id="v1", script_hash="abc", visual_hashes=["h1", "h2"],
            audio_fingerprint="af1", music_fingerprint="mf1", structure_signature="s1"
        )
        assert fp.similarity_score(fp) == 1.0

    def test_empty_score(self):
        fp1 = ContentFingerprint(video_id="v1")
        fp2 = ContentFingerprint(video_id="v2")
        assert fp1.similarity_score(fp2) == 0.0

    def test_partial_match(self):
        fp1 = ContentFingerprint(video_id="v1", script_hash="abc", audio_fingerprint="af1")
        fp2 = ContentFingerprint(video_id="v2", script_hash="abc", audio_fingerprint="af2")
        score = fp1.similarity_score(fp2)
        assert 0.0 < score < 1.0

    def test_visual_hash_overlap(self):
        fp1 = ContentFingerprint(video_id="v1", visual_hashes=["h1", "h2", "h3"])
        fp2 = ContentFingerprint(video_id="v2", visual_hashes=["h2", "h3", "h4"])
        score = fp1.similarity_score(fp2)
        assert score > 0.0

    def test_threshold_check(self):
        fp1 = ContentFingerprint(
            video_id="v1", script_hash="x", visual_hashes=["h1"],
            audio_fingerprint="a", music_fingerprint="m", structure_signature="s"
        )
        fp2 = ContentFingerprint(
            video_id="v2", script_hash="x", visual_hashes=["h1"],
            audio_fingerprint="a", music_fingerprint="m", structure_signature="s"
        )
        assert fp2.similarity_score(fp1) > 0.7


class TestMediaPipelineState:
    def test_initial_state(self):
        s = MediaPipelineState(video_id="v1", channel_id="ch1")
        assert not s.all_done
        assert not s.has_failure

    def test_all_done(self):
        s = MediaPipelineState(
            video_id="v1", channel_id="ch1",
            tts=MediaStatus.DONE, images=MediaStatus.DONE,
            video_gen=MediaStatus.SKIPPED, music=MediaStatus.DONE,
            subtitle=MediaStatus.DONE, thumbnail=MediaStatus.DONE,
            render=MediaStatus.DONE, fingerprint=MediaStatus.DONE,
        )
        assert s.all_done
        assert not s.has_failure

    def test_has_failure(self):
        s = MediaPipelineState(
            video_id="v1", channel_id="ch1",
            tts=MediaStatus.DONE, images=MediaStatus.FAILED,
        )
        assert s.has_failure
        assert not s.all_done

    def test_mixed_done_skipped(self):
        s = MediaPipelineState(
            video_id="v1", channel_id="ch1",
            tts=MediaStatus.DONE, images=MediaStatus.DONE,
            video_gen=MediaStatus.SKIPPED, music=MediaStatus.DONE,
            subtitle=MediaStatus.DONE, thumbnail=MediaStatus.DONE,
            render=MediaStatus.DONE, fingerprint=MediaStatus.SKIPPED,
        )
        assert s.all_done

    def test_frozen(self):
        s = MediaPipelineState(video_id="v1", channel_id="ch1")
        with pytest.raises(ValidationError):
            s.video_id = "v2"
```

### tests/unit/test_media_base.py

```python
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
```
