# TASK_E: Video Gen + Subtitle + Thumbnail

## Model: sonnet | Dependencies: TASK_A complete

Three modules in one task (all small). Video gen via Wan 2.1/Ken Burns. Subtitle via WhisperX. Thumbnail via ComfyUI + PIL.

## Interface

### src/omnicast/media/video_gen.py

```python
"""Video generation. Wan 2.1 for complex scenes, Ken Burns (FFmpeg) fallback."""

from __future__ import annotations
import asyncio
from pathlib import Path
import structlog
from omnicast.media.base import BaseMediaModule
from omnicast.media.models import (
    VideoGenRequest, VideoGenResult, VideoGenBackend, MediaStatus,
)
from omnicast.shared.errors import MediaError

logger = structlog.get_logger()


class VideoGenModule(BaseMediaModule):
    name = "video_gen"

    def __init__(self, comfyui_url: str = "http://127.0.0.1:8188") -> None:
        super().__init__()
        self.comfyui_url = comfyui_url

    async def _process(self, request: VideoGenRequest) -> VideoGenResult:
        """Route to backend. Steps:
        1. WAN21: ComfyUI Wan 2.1 workflow → 5-10s clip
        2. KEN_BURNS: source_image required → FFmpeg zoom/pan effect
        """
        if request.backend == VideoGenBackend.WAN21:
            return await self._wan21(request)
        elif request.backend == VideoGenBackend.KEN_BURNS:
            return await self._ken_burns(request)
        raise MediaError(f"Unknown video backend: {request.backend}")

    async def _wan21(self, request: VideoGenRequest) -> VideoGenResult:
        """Generate via Wan 2.1 through ComfyUI API."""
        ...

    async def _ken_burns(self, request: VideoGenRequest) -> VideoGenResult:
        """Apply Ken Burns (zoom+pan) to source_image via FFmpeg.
        Requires request.source_image to be set."""
        if not request.source_image:
            raise MediaError("Ken Burns requires source_image")
        ...

    def _dry_run_result(self, request: VideoGenRequest) -> VideoGenResult:
        return VideoGenResult(
            video_path=request.output_path or "dry_run_video.mp4",
            duration_seconds=request.duration_seconds,
            backend_used=request.backend,
            status=MediaStatus.DONE,
        )
```

### src/omnicast/media/subtitle.py

```python
"""Subtitle generation via WhisperX word-level forced alignment."""

from __future__ import annotations
import asyncio
from pathlib import Path
import structlog
from omnicast.media.base import BaseMediaModule
from omnicast.media.models import SubtitleRequest, SubtitleResult, MediaStatus
from omnicast.shared.errors import MediaError

logger = structlog.get_logger()


class SubtitleModule(BaseMediaModule):
    name = "subtitle"

    async def _process(self, request: SubtitleRequest) -> SubtitleResult:
        """Run WhisperX on audio. Steps:
        1. Load audio via whisperx.load_audio()
        2. Transcribe with whisperx.load_model().transcribe()
        3. Align with whisperx.align() for word-level timestamps
        4. Write SRT file with word-level timing
        """
        ...

    def _write_srt(self, segments: list[dict], output_path: str) -> int:
        """Convert WhisperX segments to SRT format. Return word count."""
        ...

    def _dry_run_result(self, request: SubtitleRequest) -> SubtitleResult:
        return SubtitleResult(
            srt_path=request.output_path or "dry_run_subtitle.srt",
            word_count=0,
            duration_seconds=0.0,
            status=MediaStatus.DONE,
        )
```

### src/omnicast/media/thumbnail.py

```python
"""Thumbnail generation. ComfyUI for base image + PIL for text overlay. 3 variants A/B/C."""

from __future__ import annotations
import asyncio
from pathlib import Path
import structlog
from omnicast.media.base import BaseMediaModule
from omnicast.media.models import ThumbnailRequest, ThumbnailResult, MediaStatus
from omnicast.shared.errors import MediaError

logger = structlog.get_logger()


class ThumbnailModule(BaseMediaModule):
    name = "thumbnail"

    def __init__(self, comfyui_url: str = "http://127.0.0.1:8188") -> None:
        super().__init__()
        self.comfyui_url = comfyui_url

    async def _process(self, request: ThumbnailRequest) -> ThumbnailResult:
        """Generate thumbnail variants. Steps:
        1. Generate base image via ComfyUI (or use source_image)
        2. For each variant (A/B/C):
           - Vary color_palette tint, expression, text position
           - PIL overlay: title text with font + color from request
           - Save as 1280x720 JPEG
        3. Return list of paths, variant A as selected
        """
        ...

    def _overlay_text(self, image_path: str, title: str, font: str,
                      color: str, output_path: str) -> None:
        """PIL: draw title text on image. Bold, outlined, positioned bottom-third."""
        ...

    def _dry_run_result(self, request: ThumbnailRequest) -> ThumbnailResult:
        paths = [f"dry_run_thumb_{chr(65+i)}.jpg" for i in range(request.variants)]
        return ThumbnailResult(
            paths=paths,
            selected_variant=paths[0] if paths else "",
            status=MediaStatus.DONE,
        )
```

## DO NOT

- No actual WhisperX/ComfyUI/PIL calls in tests — mock all
- No FFmpeg render logic — that's TASK_F
- No `os.system()` — subprocess_exec or library calls only
- Ken Burns must require source_image — raise MediaError if missing
- Thumbnail variants count from request.variants, not hardcoded 3

## Tests

### tests/unit/test_video_gen.py

```python
import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from omnicast.media.video_gen import VideoGenModule
from omnicast.media.models import (
    VideoGenRequest, VideoGenResult, VideoGenBackend, MediaStatus,
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
def vg(mock_settings):
    with patch("omnicast.media.base.get_settings", return_value=mock_settings):
        return VideoGenModule()


@pytest.fixture
def vg_dry(dry_settings):
    with patch("omnicast.media.base.get_settings", return_value=dry_settings):
        return VideoGenModule()


class TestVideoGenDryRun:
    @pytest.mark.asyncio
    async def test_dry_run(self, vg_dry):
        req = VideoGenRequest(prompt="Ocean", duration_seconds=5.0)
        result = await vg_dry.process(req)
        assert result.status == MediaStatus.DONE
        assert result.duration_seconds == 5.0

    @pytest.mark.asyncio
    async def test_dry_run_backend(self, vg_dry):
        req = VideoGenRequest(prompt="X", backend=VideoGenBackend.KEN_BURNS)
        result = await vg_dry.process(req)
        assert result.backend_used == VideoGenBackend.KEN_BURNS


class TestVideoGenRouting:
    @pytest.mark.asyncio
    async def test_wan21_route(self, vg):
        with patch.object(vg, "_wan21", new_callable=AsyncMock) as mock_w:
            mock_w.return_value = VideoGenResult(backend_used=VideoGenBackend.WAN21, status=MediaStatus.DONE)
            result = await vg._process(VideoGenRequest(prompt="X"))
            mock_w.assert_called_once()

    @pytest.mark.asyncio
    async def test_ken_burns_route(self, vg):
        with patch.object(vg, "_ken_burns", new_callable=AsyncMock) as mock_kb:
            mock_kb.return_value = VideoGenResult(backend_used=VideoGenBackend.KEN_BURNS, status=MediaStatus.DONE)
            await vg._process(VideoGenRequest(prompt="X", backend=VideoGenBackend.KEN_BURNS, source_image="/img.png"))
            mock_kb.assert_called_once()

    @pytest.mark.asyncio
    async def test_ken_burns_requires_source(self, vg):
        with pytest.raises(MediaError, match="source_image"):
            await vg._ken_burns(VideoGenRequest(prompt="X", backend=VideoGenBackend.KEN_BURNS))


class TestVideoGenModule:
    def test_name(self, vg):
        assert vg.name == "video_gen"
```

### tests/unit/test_subtitle.py

```python
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
```

### tests/unit/test_thumbnail.py

```python
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
```
