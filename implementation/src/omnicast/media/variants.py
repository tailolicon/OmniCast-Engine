"""Render variant exporter for platform-specific aspect ratios."""

from __future__ import annotations

import asyncio
from pathlib import Path

from omnicast.platforms.models import FormatSpec
from omnicast.shared.errors import MediaError


class RenderVariantExporter:
    """Create platform-specific variants from a master MP4."""

    def build_command(self, input_path: str, output_path: str, spec: FormatSpec) -> list[str]:
        if spec.aspect_ratio not in {"16:9", "9:16", "1:1"}:
            raise MediaError(f"Unsupported aspect ratio: {spec.aspect_ratio}")
        width, height = spec.width, spec.height
        vf = self._video_filter(spec)
        return [
            "ffmpeg",
            "-y",
            "-i",
            input_path,
            "-vf",
            vf,
            "-c:v",
            "libx264",
            "-preset",
            "fast",
            "-crf",
            "23",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-movflags",
            "+faststart",
            "-metadata",
            f"omnicast_variant={spec.variant}",
            output_path,
        ]

    async def export(
        self,
        input_path: str,
        output_path: str,
        spec: FormatSpec,
        *,
        dry_run: bool = False,
    ) -> str:
        if not dry_run and not Path(input_path).exists():
            raise MediaError(f"Master video not found: {input_path}")
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        cmd = self.build_command(input_path, output_path, spec)
        if dry_run:
            return output_path
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            message = stderr.decode("utf-8", errors="replace")[-1000:]
            raise MediaError(f"FFmpeg variant export failed: {message}")
        return output_path

    def _video_filter(self, spec: FormatSpec) -> str:
        width, height = spec.width, spec.height
        if spec.aspect_ratio == "9:16":
            return (
                f"scale={width}:{height}:force_original_aspect_ratio=increase,"
                f"crop={width}:{height},setsar=1"
            )
        if spec.aspect_ratio == "1:1":
            return (
                f"scale={width}:{height}:force_original_aspect_ratio=increase,"
                f"crop={width}:{height},setsar=1"
            )
        return (
            f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1"
        )
