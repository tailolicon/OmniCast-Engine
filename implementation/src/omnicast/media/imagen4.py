"""Imagen 4 image generation via Google Gemini API.

Reads scene data (visual_prompt per scene) from a script JSON and generates
one 16:9 image per scene using Imagen 4.

Output layout:
  output/scripts/{channel_id}/{topic_slug}/images/scene_{i:03d}.png

Cost: ~$0.03/image (Imagen 4 via Gemini API).
"""

from __future__ import annotations

import asyncio
import base64
import json
import time
from pathlib import Path
from typing import TypedDict

import structlog

logger = structlog.get_logger()

_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent  # implementation/

IMAGEN_MODEL = "imagen-4.0-generate-001"
ASPECT_RATIO = "16:9"
# Imagen 4 API rate limit: 10 QPM on free tier, 50 QPM on paid
CONCURRENCY = 4   # conservative — avoids 429 bursts
RETRY_LIMIT = 3
RETRY_DELAY_S = 5.0


class SceneImage(TypedDict):
    scene_index: int
    segment: str
    voiceover: str
    visual_prompt: str
    image_path: str    # written path, "" if failed
    status: str        # "done" | "failed" | "skipped"


async def _generate_one(
    client: object,
    prompt: str,
    out_path: Path,
    scene_idx: int,
    semaphore: asyncio.Semaphore,
) -> tuple[bool, str]:
    """Generate single image. Returns (ok, error_msg)."""
    async with semaphore:
        for attempt in range(1, RETRY_LIMIT + 1):
            try:
                def _call() -> bytes:
                    from google.genai import types as gtypes
                    result = client.models.generate_images(
                        model=IMAGEN_MODEL,
                        prompt=prompt,
                        config=gtypes.GenerateImagesConfig(
                            number_of_images=1,
                            aspect_ratio=ASPECT_RATIO,
                            output_mime_type="image/png",
                        ),
                    )
                    img = result.generated_images[0]
                    # SDK returns image_bytes directly or base64 string
                    raw = img.image.image_bytes
                    if isinstance(raw, str):
                        return base64.b64decode(raw)
                    return raw  # type: ignore[return-value]

                img_bytes = await asyncio.to_thread(_call)
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_bytes(img_bytes)
                logger.info("imagen4.generated", scene=scene_idx, path=str(out_path))
                return True, ""

            except Exception as exc:
                err = str(exc)[:200]
                if attempt < RETRY_LIMIT:
                    logger.warning(
                        "imagen4.retry",
                        scene=scene_idx,
                        attempt=attempt,
                        error=err,
                    )
                    await asyncio.sleep(RETRY_DELAY_S * attempt)
                else:
                    logger.error("imagen4.failed", scene=scene_idx, error=err)
                    return False, err

    return False, "unreachable"


async def generate_images_for_script(
    script_json_path: str | Path,
    google_api_key: str,
    *,
    dry_run: bool = False,
    max_scenes: int | None = None,
) -> list[SceneImage]:
    """Generate one Imagen 4 image per scene in the script JSON.

    Args:
        script_json_path: Path to script .json file (output of Phase 2).
        google_api_key:   Google AI Studio API key.
        dry_run:          Skip API calls, write placeholder paths.
        max_scenes:       Cap number of scenes (cost control).

    Returns:
        List of SceneImage dicts with image_path and status per scene.
    """
    script_path = Path(script_json_path)
    if not script_path.exists():
        raise FileNotFoundError(f"Script JSON not found: {script_path}")

    data = json.loads(script_path.read_text(encoding="utf-8"))
    channel_id: str = data.get("channel_id", "unknown")
    topic: str = data.get("topic", "unknown")
    scenes: list[dict] = data.get("scenes", [])

    if not scenes:
        logger.warning("imagen4.no_scenes", path=str(script_path))
        return []

    if max_scenes:
        scenes = scenes[:max_scenes]

    # Output dir: same folder as script JSON but inside /images/
    images_dir = script_path.parent / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    if dry_run:
        logger.info("imagen4.dry_run", scenes=len(scenes))
        return [
            SceneImage(
                scene_index=i,
                segment=s.get("segment", ""),
                voiceover=s.get("voiceover", ""),
                visual_prompt=s.get("visual_prompt", ""),
                image_path=str(images_dir / f"scene_{i:03d}.png"),
                status="skipped",
            )
            for i, s in enumerate(scenes)
        ]

    if not google_api_key:
        raise ValueError("GOOGLE_API_KEY is required for Imagen 4 image generation")

    from google import genai as _genai  # type: ignore[import-untyped]
    client = _genai.Client(api_key=google_api_key)

    semaphore = asyncio.Semaphore(CONCURRENCY)
    results: list[SceneImage] = []

    tasks = []
    meta = []
    for i, scene in enumerate(scenes):
        prompt = scene.get("visual_prompt", "")
        out_path = images_dir / f"scene_{i:03d}.png"
        if not prompt:
            results.append(SceneImage(
                scene_index=i,
                segment=scene.get("segment", ""),
                voiceover=scene.get("voiceover", ""),
                visual_prompt="",
                image_path="",
                status="skipped",
            ))
            continue
        tasks.append(_generate_one(client, prompt, out_path, i, semaphore))
        meta.append((i, scene, out_path))

    t0 = time.time()
    task_results = await asyncio.gather(*tasks, return_exceptions=True)
    elapsed = time.time() - t0

    # Merge task results back to ordered results list
    result_map: dict[int, SceneImage] = {r["scene_index"]: r for r in results}
    for (i, scene, out_path), outcome in zip(meta, task_results):
        if isinstance(outcome, Exception):
            ok, err = False, str(outcome)[:200]
        else:
            ok, err = outcome  # type: ignore[misc]
        result_map[i] = SceneImage(
            scene_index=i,
            segment=scene.get("segment", ""),
            voiceover=scene.get("voiceover", ""),
            visual_prompt=scene.get("visual_prompt", ""),
            image_path=str(out_path) if ok else "",
            status="done" if ok else "failed",
        )

    ordered = [result_map[i] for i in sorted(result_map)]
    done = sum(1 for r in ordered if r["status"] == "done")
    failed = sum(1 for r in ordered if r["status"] == "failed")
    logger.info(
        "imagen4.batch_done",
        channel_id=channel_id,
        topic=topic,
        done=done,
        failed=failed,
        elapsed_s=round(elapsed, 1),
        cost_usd=round(done * 0.03, 3),
    )
    return ordered
