# TASK_F: FFmpeg Render + Content Fingerprint

## Model: sonnet | Dependencies: TASK_A-E complete

FFmpeg render (5-layer composition) + content fingerprint (duplicate detection).

## Interface

### src/omnicast/media/ffmpeg.py

```python
"""FFmpeg render module. Composes 5 layers into final video."""

from __future__ import annotations
import asyncio
from pathlib import Path
import structlog
from omnicast.media.base import BaseMediaModule
from omnicast.media.models import (
    RenderJob, RenderResult, RenderLayer, MediaStatus,
)
from omnicast.shared.errors import MediaError

logger = structlog.get_logger()


class FFmpegModule(BaseMediaModule):
    name = "ffmpeg"

    async def _process(self, request: RenderJob) -> RenderResult:
        """Build and run FFmpeg command. 5 layers:
        Layer 1: Video/image clips (crossfade transition)
        Layer 2: Voiceover audio
        Layer 3: Background music (ducking at music_duck_db when voiceover present)
        Layer 4: Subtitles (burn-in from SRT)
        Layer 5: Intro + outro (concat before/after main)

        Steps:
        1. Validate all layer file paths exist
        2. Build complex filter graph
        3. Run via asyncio.create_subprocess_exec
        4. Parse output for duration + file size
        5. Return RenderResult
        """
        self._validate_layers(request.layers)
        cmd = self._build_command(request)
        return await self._run_ffmpeg(cmd, request.output_path)

    def _validate_layers(self, layers: list[RenderLayer]) -> None:
        """Check required layers exist. Raise MediaError if video or voiceover missing."""
        layer_types = {l.layer_type for l in layers}
        for required in ["video", "voiceover"]:
            if required not in layer_types:
                raise MediaError(f"Missing required layer: {required}")

    def _build_command(self, job: RenderJob) -> list[str]:
        """Build FFmpeg CLI args. Returns list of strings for subprocess.
        - Video: concat with crossfade
        - Audio: amix voiceover + music with sidechaincompress for ducking
        - Subtitle: subtitles filter from SRT
        - Output: h264 + aac, resolution from job
        """
        ...

    async def _run_ffmpeg(self, cmd: list[str], output_path: str) -> RenderResult:
        """Execute FFmpeg subprocess. Parse stderr for progress. Return RenderResult."""
        ...

    def _get_file_size_mb(self, path: str) -> float:
        """Return file size in MB."""
        ...

    def _dry_run_result(self, request: RenderJob) -> RenderResult:
        return RenderResult(
            output_path=request.output_path or "dry_run_render.mp4",
            duration_seconds=0.0,
            file_size_mb=0.0,
            status=MediaStatus.DONE,
        )
```

### src/omnicast/media/fingerprint.py

```python
"""Content fingerprinting for duplicate/similarity detection."""

from __future__ import annotations
import hashlib
from pathlib import Path
import structlog
from omnicast.media.models import ContentFingerprint
from omnicast.shared.errors import MediaError

logger = structlog.get_logger()


class FingerprintModule:
    """Not a BaseMediaModule — stateless utility, no dry-run needed."""

    def fingerprint_script(self, script_text: str) -> str:
        """SHA-256 hash of normalized script text."""
        normalized = " ".join(script_text.lower().split())
        return hashlib.sha256(normalized.encode()).hexdigest()

    def fingerprint_visual(self, image_paths: list[str]) -> list[str]:
        """Perceptual hash (pHash) of key frame images using imagehash library.
        Returns list of hex hash strings."""
        ...

    def fingerprint_audio(self, audio_path: str) -> str:
        """Chromaprint fingerprint of audio using librosa + hashlib.
        Steps: load audio → extract chroma features → hash."""
        ...

    def fingerprint_structure(self, intro_duration: float, scene_count: int,
                               transition_types: list[str]) -> str:
        """Hash of structural metadata: intro length, scene count, transitions."""
        sig = f"{intro_duration:.1f}|{scene_count}|{','.join(sorted(transition_types))}"
        return hashlib.sha256(sig.encode()).hexdigest()[:16]

    def build_fingerprint(self, video_id: str, script_text: str = "",
                           image_paths: list[str] | None = None,
                           audio_path: str = "",
                           intro_duration: float = 0.0,
                           scene_count: int = 0,
                           transition_types: list[str] | None = None) -> ContentFingerprint:
        """Build complete ContentFingerprint from raw inputs."""
        return ContentFingerprint(
            video_id=video_id,
            script_hash=self.fingerprint_script(script_text) if script_text else "",
            visual_hashes=self.fingerprint_visual(image_paths) if image_paths else [],
            audio_fingerprint=self.fingerprint_audio(audio_path) if audio_path else "",
            structure_signature=self.fingerprint_structure(
                intro_duration, scene_count, transition_types or []
            ),
        )

    def check_duplicate(self, new: ContentFingerprint,
                         existing: list[ContentFingerprint],
                         threshold: float = 0.7) -> ContentFingerprint | None:
        """Return first existing fingerprint with similarity > threshold, or None."""
        for fp in existing:
            if new.similarity_score(fp) > threshold:
                return fp
        return None
```

## DO NOT

- No actual FFmpeg binary calls in tests — mock subprocess
- No actual imagehash/librosa imports in tests — mock
- No `os.system()` — use `asyncio.create_subprocess_exec`
- FingerprintModule is NOT a BaseMediaModule — no async process(), no dry-run
- Music ducking value must come from RenderJob.music_duck_db, not hardcoded

## Tests

### tests/unit/test_ffmpeg.py

```python
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
```

### tests/unit/test_fingerprint.py

```python
import pytest
from omnicast.media.fingerprint import FingerprintModule
from omnicast.media.models import ContentFingerprint


@pytest.fixture
def fp():
    return FingerprintModule()


class TestScriptFingerprint:
    def test_deterministic(self, fp):
        h1 = fp.fingerprint_script("Hello World")
        h2 = fp.fingerprint_script("Hello World")
        assert h1 == h2

    def test_case_insensitive(self, fp):
        h1 = fp.fingerprint_script("Hello World")
        h2 = fp.fingerprint_script("hello world")
        assert h1 == h2

    def test_whitespace_normalized(self, fp):
        h1 = fp.fingerprint_script("hello  world")
        h2 = fp.fingerprint_script("hello world")
        assert h1 == h2

    def test_different_text_different_hash(self, fp):
        h1 = fp.fingerprint_script("hello")
        h2 = fp.fingerprint_script("world")
        assert h1 != h2

    def test_empty_string(self, fp):
        h = fp.fingerprint_script("")
        assert isinstance(h, str) and len(h) > 0


class TestStructureFingerprint:
    def test_deterministic(self, fp):
        h1 = fp.fingerprint_structure(3.0, 5, ["cut", "fade"])
        h2 = fp.fingerprint_structure(3.0, 5, ["cut", "fade"])
        assert h1 == h2

    def test_order_independent(self, fp):
        h1 = fp.fingerprint_structure(3.0, 5, ["fade", "cut"])
        h2 = fp.fingerprint_structure(3.0, 5, ["cut", "fade"])
        assert h1 == h2

    def test_different_params(self, fp):
        h1 = fp.fingerprint_structure(3.0, 5, ["cut"])
        h2 = fp.fingerprint_structure(4.0, 5, ["cut"])
        assert h1 != h2

    def test_truncated_hash(self, fp):
        h = fp.fingerprint_structure(1.0, 1, [])
        assert len(h) == 16


class TestBuildFingerprint:
    def test_full_build(self, fp):
        result = fp.build_fingerprint(
            video_id="v1", script_text="hello world",
            intro_duration=3.0, scene_count=5,
            transition_types=["cut", "fade"],
        )
        assert isinstance(result, ContentFingerprint)
        assert result.video_id == "v1"
        assert result.script_hash != ""
        assert result.structure_signature != ""

    def test_minimal_build(self, fp):
        result = fp.build_fingerprint(video_id="v2")
        assert result.script_hash == ""
        assert result.visual_hashes == []
        assert result.audio_fingerprint == ""


class TestDuplicateCheck:
    def test_no_duplicates(self, fp):
        new = ContentFingerprint(video_id="v1", script_hash="abc")
        existing = [ContentFingerprint(video_id="v2", script_hash="xyz")]
        assert fp.check_duplicate(new, existing) is None

    def test_finds_duplicate(self, fp):
        target = ContentFingerprint(
            video_id="v1", script_hash="abc", visual_hashes=["h1"],
            audio_fingerprint="a", music_fingerprint="m", structure_signature="s",
        )
        existing = [ContentFingerprint(
            video_id="v2", script_hash="abc", visual_hashes=["h1"],
            audio_fingerprint="a", music_fingerprint="m", structure_signature="s",
        )]
        result = fp.check_duplicate(target, existing)
        assert result is not None
        assert result.video_id == "v2"

    def test_empty_existing(self, fp):
        new = ContentFingerprint(video_id="v1")
        assert fp.check_duplicate(new, []) is None

    def test_custom_threshold(self, fp):
        new = ContentFingerprint(video_id="v1", script_hash="abc")
        existing = [ContentFingerprint(video_id="v2", script_hash="abc")]
        assert fp.check_duplicate(new, existing, threshold=0.1) is not None
        assert fp.check_duplicate(new, existing, threshold=0.5) is None
```
