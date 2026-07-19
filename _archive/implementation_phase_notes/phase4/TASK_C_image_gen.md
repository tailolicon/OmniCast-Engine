# TASK_C: Image Gen Module

## Model: sonnet | Dependencies: TASK_A complete

Implement image generation module wrapping ComfyUI (SDXL + FLUX).

## Interface

### src/omnicast/media/image_gen.py

```python
"""Image generation module. Wraps ComfyUI API for SDXL/FLUX backends."""

from __future__ import annotations
import asyncio
import json
from pathlib import Path
import structlog
from omnicast.media.base import BaseMediaModule
from omnicast.media.models import (
    ImageGenRequest, ImageGenResult, ImageGenBackend, MediaStatus,
)
from omnicast.shared.errors import MediaError

logger = structlog.get_logger()

COMFYUI_DEFAULT_URL = "http://127.0.0.1:8188"


class ImageGenModule(BaseMediaModule):
    name = "image_gen"

    def __init__(self, comfyui_url: str = COMFYUI_DEFAULT_URL) -> None:
        super().__init__()
        self.comfyui_url = comfyui_url

    async def _process(self, request: ImageGenRequest) -> ImageGenResult:
        """Generate image via ComfyUI API. Steps:
        1. Build workflow JSON (SDXL or FLUX)
        2. If reference_image → add IP-Adapter node with ip_adapter_weight
        3. POST to ComfyUI /prompt endpoint
        4. Poll /history until complete
        5. Download output image to output_path
        """
        workflow = self._build_workflow(request)
        prompt_id = await self._queue_prompt(workflow)
        output_path = await self._wait_and_download(prompt_id, request.output_path)
        return ImageGenResult(
            image_path=str(output_path),
            backend_used=request.backend,
            status=MediaStatus.DONE,
        )

    def _build_workflow(self, request: ImageGenRequest) -> dict:
        """Build ComfyUI workflow JSON. SDXL uses KSampler + CLIPTextEncode.
        FLUX uses different checkpoint. IP-Adapter added when reference_image set."""
        ...

    async def _queue_prompt(self, workflow: dict) -> str:
        """POST workflow to ComfyUI /prompt. Returns prompt_id."""
        ...

    async def _wait_and_download(self, prompt_id: str, output_path: str) -> Path:
        """Poll ComfyUI /history/{prompt_id} until done. Download result."""
        ...

    def _dry_run_result(self, request: ImageGenRequest) -> ImageGenResult:
        return ImageGenResult(
            image_path=request.output_path or "dry_run_image.png",
            backend_used=request.backend,
            seed=42,
            status=MediaStatus.DONE,
        )
```

## DO NOT

- No actual ComfyUI server calls in tests — mock HTTP
- No `os.system` — use `aiohttp` or `httpx` for ComfyUI API
- No TTS/music/video logic
- No hardcoded workflow JSONs > 50 lines — load from templates or build programmatically
- IP-Adapter weight must come from request.ip_adapter_weight, not hardcoded

## Tests

### tests/unit/test_image_gen.py

```python
import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from omnicast.media.image_gen import ImageGenModule, COMFYUI_DEFAULT_URL
from omnicast.media.models import (
    ImageGenRequest, ImageGenResult, ImageGenBackend, MediaStatus,
)


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
def img(mock_settings):
    with patch("omnicast.media.base.get_settings", return_value=mock_settings):
        return ImageGenModule()


@pytest.fixture
def img_dry(dry_settings):
    with patch("omnicast.media.base.get_settings", return_value=dry_settings):
        return ImageGenModule()


class TestImageGenDryRun:
    @pytest.mark.asyncio
    async def test_dry_run_returns_result(self, img_dry):
        req = ImageGenRequest(prompt="A sunset over mountains")
        result = await img_dry.process(req)
        assert isinstance(result, ImageGenResult)
        assert result.status == MediaStatus.DONE
        assert result.seed == 42

    @pytest.mark.asyncio
    async def test_dry_run_uses_output_path(self, img_dry):
        req = ImageGenRequest(prompt="Cat", output_path="/tmp/cat.png")
        result = await img_dry.process(req)
        assert result.image_path == "/tmp/cat.png"

    @pytest.mark.asyncio
    async def test_dry_run_backend_preserved(self, img_dry):
        req = ImageGenRequest(prompt="X", backend=ImageGenBackend.FLUX)
        result = await img_dry.process(req)
        assert result.backend_used == ImageGenBackend.FLUX


class TestImageGenProcess:
    @pytest.mark.asyncio
    async def test_process_calls_workflow(self, img):
        with patch.object(img, "_build_workflow", return_value={"nodes": {}}) as mock_bw, \
             patch.object(img, "_queue_prompt", new_callable=AsyncMock, return_value="pid_123") as mock_qp, \
             patch.object(img, "_wait_and_download", new_callable=AsyncMock, return_value="/tmp/out.png"):
            result = await img._process(ImageGenRequest(prompt="Test"))
            mock_bw.assert_called_once()
            mock_qp.assert_called_once()
            assert result.status == MediaStatus.DONE

    @pytest.mark.asyncio
    async def test_process_passes_backend(self, img):
        with patch.object(img, "_build_workflow", return_value={}) as mock_bw, \
             patch.object(img, "_queue_prompt", new_callable=AsyncMock, return_value="pid"), \
             patch.object(img, "_wait_and_download", new_callable=AsyncMock, return_value="/tmp/out.png"):
            req = ImageGenRequest(prompt="X", backend=ImageGenBackend.FLUX)
            result = await img._process(req)
            assert result.backend_used == ImageGenBackend.FLUX


class TestImageGenWorkflow:
    def test_build_workflow_sdxl(self, img):
        req = ImageGenRequest(prompt="A cat", backend=ImageGenBackend.SDXL)
        wf = img._build_workflow(req)
        assert isinstance(wf, dict)

    def test_build_workflow_flux(self, img):
        req = ImageGenRequest(prompt="A cat", backend=ImageGenBackend.FLUX)
        wf = img._build_workflow(req)
        assert isinstance(wf, dict)

    def test_build_workflow_with_reference(self, img):
        req = ImageGenRequest(prompt="A cat", reference_image="/tmp/ref.png", ip_adapter_weight=0.7)
        wf = img._build_workflow(req)
        assert isinstance(wf, dict)


class TestImageGenModule:
    def test_name(self, img):
        assert img.name == "image_gen"

    def test_default_url(self, img):
        assert img.comfyui_url == COMFYUI_DEFAULT_URL

    def test_custom_url(self, mock_settings):
        with patch("omnicast.media.base.get_settings", return_value=mock_settings):
            m = ImageGenModule(comfyui_url="http://gpu-server:8188")
            assert m.comfyui_url == "http://gpu-server:8188"
```
