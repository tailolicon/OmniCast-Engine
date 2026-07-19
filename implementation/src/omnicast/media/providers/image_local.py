"""Local image generation via diffusers (no API key).

Runs on CPU-only torch or small GPUs. Defaults to **SD-Turbo** (1-step,
~2.5GB, 512px) which is the fastest real diffusion model on a CPU box; can
also drive **SDXL-Turbo** (1-4 steps, 1024px, ~7GB) when more VRAM/time exists.

This is the local tier of the dual-provider image strategy: SD/SDXL-Turbo here,
FLUX on a remote GPU host (FLUX needs >=12GB VRAM, cannot run on 4GB).
"""

from __future__ import annotations

from pathlib import Path

from omnicast.media.providers.image_gemini import MediaError
from omnicast.media.providers.interfaces import ModelOption

_MODEL_REPOS = {
    "sd-turbo": "stabilityai/sd-turbo",
    "sdxl-turbo": "stabilityai/sdxl-turbo",
}
_DEFAULT_STEPS = {"sd-turbo": 1, "sdxl-turbo": 2}


class LocalDiffusionProvider:
    """Local Stable Diffusion (Turbo) image provider."""

    id = "local-sd"
    name = "Local Stable Diffusion (Turbo)"
    models = [
        ModelOption(id="sd-turbo", name="SD-Turbo", description="1-step 512px, fastest on CPU/4GB"),
        ModelOption(id="sdxl-turbo", name="SDXL-Turbo", description="1-4 step 1024px, needs more VRAM/time"),
    ]

    def __init__(self) -> None:
        self._pipe = None
        self._loaded_model: str | None = None

    def _ensure_pipe(self, model_id: str):
        if self._pipe is not None and self._loaded_model == model_id:
            return self._pipe
        try:
            import torch
            from diffusers import AutoPipelineForText2Image
        except Exception as exc:  # pragma: no cover - import guard
            raise MediaError(f"diffusers/torch not available: {exc}") from exc

        repo = _MODEL_REPOS.get(model_id)
        if not repo:
            raise MediaError(f"Unknown local model '{model_id}'. Use: {', '.join(_MODEL_REPOS)}")

        has_cuda = bool(getattr(torch, "cuda", None) and torch.cuda.is_available())
        dtype = torch.float16 if has_cuda else torch.float32
        pipe = AutoPipelineForText2Image.from_pretrained(repo, torch_dtype=dtype)
        pipe = pipe.to("cuda" if has_cuda else "cpu")
        try:
            pipe.set_progress_bar_config(disable=True)
        except Exception:
            pass
        self._pipe = pipe
        self._loaded_model = model_id
        return pipe

    async def generate(
        self,
        prompt: str,
        *,
        negative: str = "",
        model: str | None = None,
        resolution: tuple[int, int] | None = None,
        output_path: str,
    ) -> str:
        import asyncio

        model_id = model or "sd-turbo"
        steps = _DEFAULT_STEPS.get(model_id, 1)
        w, h = resolution or (512, 512)
        # Turbo models are trained at fixed sizes; snap to multiples of 8.
        w, h = (w // 8) * 8, (h // 8) * 8
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)

        def _run() -> None:
            pipe = self._ensure_pipe(model_id)
            image = pipe(
                prompt=prompt,
                num_inference_steps=steps,
                guidance_scale=0.0,  # Turbo models run guidance-free
                height=h,
                width=w,
            ).images[0]
            image.save(out)

        await asyncio.to_thread(_run)
        if not out.exists():
            raise MediaError("Local SD produced no image")
        return str(out.resolve())
